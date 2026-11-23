"""User accounts, roles, authentication and lock-out rules (UI-independent)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from . import mailer, security
from .database import get_connection, write_audit
from .config import APP_NAME, RESET_CODE_MINUTES, RESET_MAX_REQUESTS_PER_HOUR
from .inventory_service import to_local

log = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 5
GENERIC_LOGIN_ERROR = "Invalid username or password."


class AuthError(ValueError):
    """A problem the person can fix (bad input, locked account, ...)."""


_FMT = "%Y-%m-%d %H:%M:%S"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).strftime(_FMT)


def _public(row) -> dict[str, Any]:
    data = dict(row)
    data.pop("password_hash", None)
    data["has_recovery"] = bool(data.pop("recovery_hash", None))
    return data


def count_users(db_path=None) -> int:
    with get_connection(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def get_user(user_id: int, db_path=None) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public(row) if row else None


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GENERIC_RECOVERY_ERROR = "Invalid username or recovery code."
GENERIC_CODE_ERROR = "Invalid or expired verification code."


def _clean_email(email: str | None) -> str | None:
    value = (email or "").strip().lower()
    if not value:
        return None
    if len(value) > 120 or not EMAIL_PATTERN.match(value):
        raise AuthError("Please enter a valid e-mail address.")
    return value


# ------------------------------------------------------------------ create / authenticate
def create_user(username: str, password: str, *, full_name: str = "", role: str = ROLE_USER,
                must_change: bool = True, actor: str = "system", email: str = "", db_path=None) -> int:
    if role not in ROLES:
        raise AuthError("Role must be 'admin' or 'user'.")
    name = security.normalize_username(username)
    security.validate_password(password)
    clean_email = _clean_email(email)
    with get_connection(db_path) as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone():
            raise AuthError(f"Username '{name}' is already taken.")
        cur = conn.execute(
            """INSERT INTO users (username, full_name, email, role, password_hash, is_active, must_change_password,
                                  created_at, password_changed_at)
               VALUES (?,?,?,?,?,1,?,?,?)""",
            (name, (full_name or "").strip(), clean_email, role, security.hash_password(password),
             1 if must_change else 0, _stamp(), _stamp()),
        )
        user_id = int(cur.lastrowid)
        write_audit(conn, actor, "USER_CREATED", "users", user_id, f"{name} ({role})")
        return user_id


def authenticate(username: str, password: str, db_path=None) -> dict:
    """Return the user record on success; raise AuthError (generic message) otherwise."""
    name = (username or "").strip().lower()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        if row is None:
            security.verify_password(password or "", security.hash_password("dummy-Password-1"))  # constant-ish timing
            write_audit(conn, name or "unknown", "LOGIN_FAILED", "users", None, "unknown username")
            conn.commit()  # keep the audit entry even though we raise
            raise AuthError(GENERIC_LOGIN_ERROR)

        locked_until = row["locked_until"]
        if locked_until and datetime.strptime(locked_until, _FMT).replace(tzinfo=timezone.utc) > _now():
            remaining = datetime.strptime(locked_until, _FMT).replace(tzinfo=timezone.utc) - _now()
            minutes = max(int(remaining.total_seconds() // 60) + 1, 1)
            raise AuthError(f"Account temporarily locked after too many failed attempts. Try again in {minutes} minute(s).")

        if not security.verify_password(password or "", row["password_hash"]):
            attempts = int(row["failed_attempts"] or 0) + 1
            if attempts >= MAX_FAILED_ATTEMPTS:
                conn.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                             (_stamp(_now() + timedelta(minutes=LOCK_MINUTES)), row["id"]))
                write_audit(conn, name, "ACCOUNT_LOCKED", "users", row["id"], f"{LOCK_MINUTES} min lock")
            else:
                conn.execute("UPDATE users SET failed_attempts = ? WHERE id = ?", (attempts, row["id"]))
            write_audit(conn, name, "LOGIN_FAILED", "users", row["id"], f"attempt {attempts}")
            conn.commit()  # keep the counters even though we raise
            raise AuthError(GENERIC_LOGIN_ERROR)

        if not row["is_active"]:
            write_audit(conn, name, "LOGIN_BLOCKED", "users", row["id"], "inactive account")
            conn.commit()
            raise AuthError("This account has been deactivated. Contact the administrator.")

        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? WHERE id = ?",
                     (_stamp(), row["id"]))
        write_audit(conn, name, "LOGIN", "users", row["id"], row["role"])
        refreshed = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        return _public(refreshed)


def record_logout(username: str, user_id: int | None, reason: str = "manual", db_path=None) -> None:
    with get_connection(db_path) as conn:
        write_audit(conn, username, "LOGOUT", "users", user_id, reason)


# ------------------------------------------------------------------ administration
def list_users(db_path=None) -> pd.DataFrame:
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(
            """SELECT id, username, full_name, email, role, is_active, must_change_password, failed_attempts,
                      locked_until, last_login, created_at,
                      CASE WHEN recovery_hash IS NULL THEN 0 ELSE 1 END AS has_recovery
               FROM users ORDER BY username""", conn)
    df["last_login"] = to_local(df["last_login"])
    df["created_at"] = to_local(df["created_at"])
    now = _stamp()
    df["locked"] = df["locked_until"].fillna("") > now
    return df


def _ensure_admin_remains(conn, user_id: int, new_role: str, new_active: bool) -> None:
    row = conn.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and row["role"] == ROLE_ADMIN and row["is_active"] and (new_role != ROLE_ADMIN or not new_active):
        others = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?", (user_id,)
        ).fetchone()[0]
        if others == 0:
            raise AuthError("At least one active administrator is required.")


def update_user(user_id: int, *, full_name: str | None = None, role: str | None = None,
                is_active: bool | None = None, actor: str = "system", actor_id: int | None = None,
                db_path=None) -> None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("User not found.")
        new_role = role if role is not None else row["role"]
        new_active = bool(row["is_active"]) if is_active is None else bool(is_active)
        if new_role not in ROLES:
            raise AuthError("Role must be 'admin' or 'user'.")
        if actor_id is not None and actor_id == user_id and not new_active:
            raise AuthError("You cannot deactivate your own account.")
        _ensure_admin_remains(conn, user_id, new_role, new_active)
        new_name = row["full_name"] if full_name is None else full_name.strip()
        changes = []
        if new_name != row["full_name"]:
            changes.append(f"name -> {new_name!r}")
        if new_role != row["role"]:
            changes.append(f"role {row['role']} -> {new_role}")
        if int(new_active) != int(row["is_active"]):
            changes.append("activated" if new_active else "deactivated")
        if not changes:
            return
        conn.execute("UPDATE users SET full_name = ?, role = ?, is_active = ? WHERE id = ?",
                     (new_name, new_role, int(new_active), user_id))
        write_audit(conn, actor, "USER_UPDATED", "users", user_id, f"{row['username']}: " + "; ".join(changes))


def reset_password(user_id: int, new_password: str, *, must_change: bool = True, actor: str = "system",
                   db_path=None) -> None:
    security.validate_password(new_password)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("User not found.")
        conn.execute(
            """UPDATE users SET password_hash = ?, must_change_password = ?, failed_attempts = 0, locked_until = NULL,
                      password_changed_at = ? WHERE id = ?""",
            (security.hash_password(new_password), int(must_change), _stamp(), user_id),
        )
        write_audit(conn, actor, "PASSWORD_RESET", "users", user_id, row["username"])


def unlock_user(user_id: int, *, actor: str = "system", db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,))
        write_audit(conn, actor, "USER_UNLOCKED", "users", user_id, "")


def change_own_password(user_id: int, current_password: str, new_password: str, db_path=None) -> None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT username, password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not security.verify_password(current_password or "", row["password_hash"]):
            raise AuthError("Current password is incorrect.")
        security.validate_password(new_password)
        if current_password == new_password:
            raise AuthError("The new password must be different from the current one.")
        conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0, password_changed_at = ? WHERE id = ?",
                     (security.hash_password(new_password), _stamp(), user_id))
        write_audit(conn, row["username"], "PASSWORD_CHANGED", "users", user_id, "self-service")


# ================================================================== account recovery
def set_email(user_id: int, email: str, *, actor: str = "system", db_path=None) -> None:
    clean = _clean_email(email)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("User not found.")
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (clean, user_id))
        write_audit(conn, actor, "EMAIL_UPDATED", "users", user_id, row["username"])


def _raise_if_locked(row) -> None:
    locked_until = row["locked_until"]
    if locked_until:
        until = datetime.strptime(locked_until, _FMT).replace(tzinfo=timezone.utc)
        if until > _now():
            minutes = max(int((until - _now()).total_seconds() // 60) + 1, 1)
            raise AuthError(f"Too many failed attempts. Try again in {minutes} minute(s).")


def _bump_failure(conn, row, action: str) -> None:
    attempts = int(row["failed_attempts"] or 0) + 1
    if attempts >= MAX_FAILED_ATTEMPTS:
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                     (_stamp(_now() + timedelta(minutes=LOCK_MINUTES)), row["id"]))
        write_audit(conn, row["username"], "ACCOUNT_LOCKED", "users", row["id"], f"{LOCK_MINUTES} min lock")
    else:
        conn.execute("UPDATE users SET failed_attempts = ? WHERE id = ?", (attempts, row["id"]))
    write_audit(conn, row["username"], action, "users", row["id"], f"attempt {attempts}")
    conn.commit()  # keep counters although the caller raises


# ---- recovery code (works offline, no e-mail needed)
def create_recovery_code(user_id: int, *, actor: str = "system", db_path=None) -> str:
    """Create a new one-time recovery code, replacing any older one. The plain code is returned once."""
    code = security.generate_recovery_code()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("User not found.")
        conn.execute("UPDATE users SET recovery_hash = ?, recovery_created_at = ? WHERE id = ?",
                     (security.hash_password(security.normalize_recovery_code(code)), _stamp(), user_id))
        write_audit(conn, actor, "RECOVERY_CODE_CREATED", "users", user_id, row["username"])
    return code


def reset_with_recovery_code(username: str, code: str, new_password: str, db_path=None) -> str:
    """Set a new password using the one-time recovery code. Returns the replacement recovery code."""
    security.validate_password(new_password)
    name = (username or "").strip().lower()
    normalized = security.normalize_recovery_code(code)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        if row is None or not row["recovery_hash"] or not row["is_active"]:
            security.verify_password(normalized, security.hash_password("dummy-Password-1"))
            write_audit(conn, name or "unknown", "RECOVERY_FAILED", "users", row["id"] if row else None, "no usable code")
            conn.commit()
            raise AuthError(GENERIC_RECOVERY_ERROR)
        _raise_if_locked(row)
        if not security.verify_password(normalized, row["recovery_hash"]):
            _bump_failure(conn, row, "RECOVERY_FAILED")
            raise AuthError(GENERIC_RECOVERY_ERROR)
        new_code = security.generate_recovery_code()
        conn.execute(
            """UPDATE users SET password_hash = ?, must_change_password = 0, failed_attempts = 0, locked_until = NULL,
                      password_changed_at = ?, recovery_hash = ?, recovery_created_at = ? WHERE id = ?""",
            (security.hash_password(new_password), _stamp(),
             security.hash_password(security.normalize_recovery_code(new_code)), _stamp(), row["id"]),
        )
        write_audit(conn, name, "PASSWORD_RESET_RECOVERY", "users", row["id"], "recovery code used")
        return new_code


# ---- e-mailed verification code
def request_email_code(username: str, *, sender=None, db_path=None) -> bool:
    """E-mail a 6-digit reset code if the account exists and has an address. Returns True if a mail was sent.

    The UI must show the same neutral message whatever this returns, so accounts cannot be probed.
    """
    sender = sender or mailer.send_email
    name = (username or "").strip().lower()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        if row is None or not row["is_active"] or not row["email"]:
            write_audit(conn, name or "unknown", "RESET_CODE_SKIPPED", "users", row["id"] if row else None,
                        "unknown, inactive or no e-mail")
            return False
        hour_ago = _stamp(_now() - timedelta(hours=1))
        recent = conn.execute("SELECT COUNT(*) FROM password_resets WHERE user_id = ? AND created_at >= ?",
                              (row["id"], hour_ago)).fetchone()[0]
        if recent >= RESET_MAX_REQUESTS_PER_HOUR:
            write_audit(conn, name, "RESET_CODE_THROTTLED", "users", row["id"], "too many requests")
            return False
        code = security.generate_numeric_code()
        cur = conn.execute(
            "INSERT INTO password_resets (user_id, code_hash, created_at, expires_at) VALUES (?,?,?,?)",
            (row["id"], security.hash_password(code), _stamp(), _stamp(_now() + timedelta(minutes=RESET_CODE_MINUTES))),
        )
        reset_id, address, user_id = cur.lastrowid, row["email"], row["id"]
        write_audit(conn, name, "RESET_CODE_REQUESTED", "users", user_id, "e-mail code")

    body = (f"Hello {row['full_name'] or name},\n\n"
            f"Your {APP_NAME} password-reset code is:\n\n    {code}\n\n"
            f"It is valid for {RESET_CODE_MINUTES} minutes and can be used once.\n"
            "If you did not request this, ignore this e-mail; your password has not been changed.\n")
    try:
        sender(address, f"{APP_NAME}: your password-reset code", body)
        return True
    except Exception as error:  # noqa: BLE001 - SMTP problems must not crash the sign-in page
        log.warning("Could not send reset e-mail: %s", error)
        with get_connection(db_path) as conn:
            conn.execute("UPDATE password_resets SET used = 1 WHERE id = ?", (reset_id,))
            write_audit(conn, name, "RESET_EMAIL_FAILED", "users", user_id, str(error)[:150])
        return False


def reset_with_email_code(username: str, code: str, new_password: str, db_path=None) -> None:
    security.validate_password(new_password)
    name = (username or "").strip().lower()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
        reset = None
        if row is not None and row["is_active"]:
            reset = conn.execute(
                """SELECT * FROM password_resets WHERE user_id = ? AND used = 0 AND expires_at > ?
                   ORDER BY id DESC LIMIT 1""", (row["id"], _stamp())).fetchone()
        if reset is None:
            security.verify_password(code or "", security.hash_password("dummy-Password-1"))
            raise AuthError(GENERIC_CODE_ERROR)
        if not security.verify_password((code or "").strip(), reset["code_hash"]):
            attempts = int(reset["attempts"]) + 1
            conn.execute("UPDATE password_resets SET attempts = ?, used = ? WHERE id = ?",
                         (attempts, 1 if attempts >= MAX_FAILED_ATTEMPTS else 0, reset["id"]))
            write_audit(conn, name, "RESET_CODE_FAILED", "users", row["id"], f"attempt {attempts}")
            conn.commit()
            raise AuthError(GENERIC_CODE_ERROR)
        conn.execute("UPDATE password_resets SET used = 1 WHERE id = ?", (reset["id"],))
        conn.execute(
            """UPDATE users SET password_hash = ?, must_change_password = 0, failed_attempts = 0, locked_until = NULL,
                      password_changed_at = ? WHERE id = ?""",
            (security.hash_password(new_password), _stamp(), row["id"]))
        write_audit(conn, name, "PASSWORD_RESET_EMAIL", "users", row["id"], "e-mail code used")


def send_username_reminders(email: str, *, sender=None, db_path=None) -> int:
    """E-mail the username(s) registered to an address. Returns how many accounts matched (UI stays neutral)."""
    sender = sender or mailer.send_email
    address = (email or "").strip().lower()
    if not EMAIL_PATTERN.match(address):
        return 0
    with get_connection(db_path) as conn:
        names = [r["username"] for r in conn.execute(
            "SELECT username FROM users WHERE LOWER(email) = ? AND is_active = 1 ORDER BY username", (address,))]
        hour_ago = _stamp(_now() - timedelta(hours=1))
        recent = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'USERNAME_REMINDER' AND details = ? AND event_time >= ?",
            (address, hour_ago)).fetchone()[0]
        if not names or recent >= RESET_MAX_REQUESTS_PER_HOUR:
            return 0
        write_audit(conn, "anonymous", "USERNAME_REMINDER", "users", None, address)
    body = (f"Hello,\n\nThe username(s) registered to this e-mail address on {APP_NAME}:\n\n    "
            + "\n    ".join(names) + "\n\nIf you did not request this, you can ignore this e-mail.\n")
    try:
        sender(address, f"{APP_NAME}: your username", body)
    except Exception as error:  # noqa: BLE001
        log.warning("Could not send username reminder: %s", error)
        return 0
    return len(names)


# ---- request help from an administrator
def create_reset_request(identifier: str, note: str = "", db_path=None) -> None:
    """Record a 'please help me sign in' request for the administrators (username or full name accepted)."""
    who = " ".join((identifier or "").split())[:60]
    if not who:
        raise AuthError("Please enter your username or full name.")
    note = " ".join((note or "").split())[:300]
    with get_connection(db_path) as conn:
        matches = conn.execute(
            "SELECT id FROM users WHERE username = ? OR LOWER(full_name) = ?", (who.lower(), who.lower())).fetchall()
        user_id = matches[0]["id"] if len(matches) == 1 else None
        day_ago = _stamp(_now() - timedelta(days=1))
        duplicate = conn.execute(
            "SELECT 1 FROM reset_requests WHERE LOWER(username) = ? AND status = 'pending' AND created_at >= ?",
            (who.lower(), day_ago)).fetchone()
        pending = conn.execute("SELECT COUNT(*) FROM reset_requests WHERE status = 'pending'").fetchone()[0]
        if duplicate or pending >= 200:
            return
        cur = conn.execute(
            "INSERT INTO reset_requests (username, user_id, note, status, created_at) VALUES (?,?,?,'pending',?)",
            (who, user_id, note, _stamp()))
        write_audit(conn, who, "RESET_REQUESTED", "users", user_id, f"request #{cur.lastrowid}")


def pending_request_count(db_path=None) -> int:
    with get_connection(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM reset_requests WHERE status = 'pending'").fetchone()[0])


def list_reset_requests(status: str | None = "pending", db_path=None) -> pd.DataFrame:
    sql = """SELECT r.id, r.username AS identifier, r.user_id, u.username AS matched_username, r.note, r.status,
                    r.created_at, r.resolved_by, r.resolved_at
             FROM reset_requests r LEFT JOIN users u ON u.id = r.user_id"""
    params: list = []
    if status:
        sql += " WHERE r.status = ?"
        params.append(status)
    sql += " ORDER BY r.id DESC"
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    df["created_at"] = to_local(df["created_at"])
    df["resolved_at"] = to_local(df["resolved_at"])
    return df


def resolve_reset_request(request_id: int, status: str = "resolved", *, actor: str = "system", db_path=None) -> None:
    if status not in ("resolved", "dismissed"):
        raise AuthError("Invalid status.")
    with get_connection(db_path) as conn:
        conn.execute("UPDATE reset_requests SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
                     (status, actor, _stamp(), request_id))
        write_audit(conn, actor, "RESET_REQUEST_" + status.upper(), "users", None, f"request #{request_id}")


def check_password(user_id: int, password: str, db_path=None) -> bool:
    """True if `password` is the user's current password (no audit entry; used to confirm sensitive actions)."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and security.verify_password(password or "", row["password_hash"]))
