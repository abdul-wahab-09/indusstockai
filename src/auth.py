"""Sign-in, first-run setup, account recovery (forgot password / username), idle time-out and role checks."""
from __future__ import annotations

import time

import streamlit as st

from . import mailer, security, ui, user_service, widgets
from .config import (APP_FULL_NAME, APP_NAME, APP_TAGLINE, RESET_CODE_MINUTES, SITE_NAME, get_secret)

SESSION_KEY = "auth_user"
ACTIVITY_KEY = "auth_last_active"
NOTICE_KEY = "_login_notice"
VIEW_KEY = "auth_view"            # "login" | "recover"
FAILURES_KEY = "auth_failures"    # timestamps of recent failed sign-ins in this browser session
SETUP_CODE_KEY = "auth_setup_code"
RECOVERED_CODE_KEY = "auth_recovered_code"
EMAIL_SENT_KEY = "auth_email_user"

MAX_SESSION_FAILURES = 5
FAILURE_WINDOW_SECONDS = 60

AUTH_CSS = """
<style>
section[data-testid="stSidebar"], div[data-testid="collapsedControl"],
button[data-testid="stExpandSidebarButton"], div[data-testid="stSidebarCollapsedControl"] {display: none;}
.stApp {background: radial-gradient(1000px 520px at 100% 0%, rgba(34,184,207,.13), transparent 60%),
                    radial-gradient(800px 520px at 0% 100%, rgba(112,72,232,.13), transparent 60%);}
</style>
"""

HERO_FEATURES = [
    ("📦", "Live stock control", "Every receipt and issue is recorded: who, when and why."),
    ("🚨", "Smart reorder alerts", "See what is running low before it stops production."),
    ("🤖", "AI assistant", "Ask in English, Urdu or Roman Urdu, by text or voice."),
    ("🛡️", "Secure and audited", "Role-based access, account recovery and a full audit trail."),
]


# ------------------------------------------------------------------ session helpers
def current_user() -> dict | None:
    return st.session_state.get(SESSION_KEY)


def is_admin() -> bool:
    user = current_user()
    return bool(user and user["role"] == user_service.ROLE_ADMIN)


def require_admin() -> bool:
    """Call at the top of an admin-only view. Shows an error and returns False for non-admins."""
    if is_admin():
        return True
    st.error("🔒 This page is available to administrators only.")
    return False


def _start_session(user: dict) -> None:
    st.session_state[SESSION_KEY] = {k: user[k] for k in ("id", "username", "full_name", "role")}
    st.session_state[ACTIVITY_KEY] = time.time()
    st.session_state[VIEW_KEY] = "login"
    st.session_state.pop(FAILURES_KEY, None)
    st.rerun()


def logout(reason: str = "manual", notice: str | None = None) -> None:
    user = current_user()
    if user:
        try:
            user_service.record_logout(user["username"], user["id"], reason)
        except Exception:  # never block a sign-out on logging problems
            pass
    for key in (SESSION_KEY, ACTIVITY_KEY, "messages", "last_voice_text", "report_bytes", "tip_dismissed",
                "speak_text", "_flash"):
        st.session_state.pop(key, None)
    st.session_state[VIEW_KEY] = "login"
    if notice:
        st.session_state[NOTICE_KEY] = notice
    st.rerun()


def _timeout_minutes() -> int:
    try:
        return max(int(get_secret("SESSION_TIMEOUT_MINUTES", "30") or 30), 1)
    except ValueError:
        return 30


# ------------------------------------------------------------------ brute-force slow-down (per browser session)
def _throttle_wait() -> int:
    """Seconds still to wait after too many failed sign-ins in this session (0 = allowed)."""
    now = time.time()
    recent = [t for t in st.session_state.get(FAILURES_KEY, []) if now - t < FAILURE_WINDOW_SECONDS]
    st.session_state[FAILURES_KEY] = recent
    if len(recent) >= MAX_SESSION_FAILURES:
        return int(FAILURE_WINDOW_SECONDS - (now - recent[0])) + 1
    return 0


def _note_failure() -> None:
    st.session_state.setdefault(FAILURES_KEY, []).append(time.time())


# ------------------------------------------------------------------ layout
def _auth_layout():
    """Two-column sign-in page: brand panel on the left. Returns the right-hand column for the form."""
    st.markdown(AUTH_CSS, unsafe_allow_html=True)
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        ui.html(widgets.auth_hero(APP_NAME, APP_FULL_NAME, APP_TAGLINE, HERO_FEATURES))
    return right


def _title(title: str, subtitle: str) -> None:
    ui.html(f'<div class="auth-title">{widgets._e(title)}</div><div class="auth-sub">{widgets._e(subtitle)}</div>')


def _password_hint() -> str:
    return f"At least {security.MIN_PASSWORD_LENGTH} characters, with a letter and a number."


def _link_button(label: str, key: str) -> bool:
    try:
        return st.button(label, key=key, type="tertiary")
    except Exception:  # older Streamlit without the "tertiary" style
        return st.button(label, key=key)


def _recovery_code_box(code: str, filename: str) -> None:
    ui.html(f'<div class="code-box">{widgets._e(code)}</div>')
    st.download_button("⬇️ Download as text file", f"{APP_NAME} recovery code\n\n{code}\n\n"
                       "Keep this file somewhere safe. It can reset your password once.\n",
                       filename, "text/plain", key=f"dl_{filename}")


# ------------------------------------------------------------------ screens
def _render_setup() -> None:
    right = _auth_layout()
    with right:
        pending = st.session_state.get(SETUP_CODE_KEY)
        if pending:  # step 2: show the recovery code before entering the app
            _title("Save your recovery code", "This is the only time it is shown. It lets you reset your password if you forget it.")
            _recovery_code_box(pending["code"], "indusstock_recovery_code.txt")
            saved = st.checkbox("I have saved my recovery code in a safe place")
            if st.button("Continue to IndusStock AI →", type="primary", disabled=not saved):
                st.session_state.pop(SETUP_CODE_KEY, None)
                _start_session(pending["user"])
            return

        _title("Welcome to IndusStock AI 👋", "Create the administrator account to get started.")
        with st.form("setup_form"):
            username = st.text_input("Username", value="admin", help="Letters, numbers, dot, dash or underscore.")
            full_name = st.text_input("Full name")
            email = st.text_input("E-mail (optional, enables e-mail password reset)", placeholder="you@company.com")
            password = st.text_input("Password", type="password", help=_password_hint())
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create administrator account", type="primary")
        if submitted:
            try:
                if password != confirm:
                    raise ValueError("Passwords do not match.")
                user_id = user_service.create_user(username, password, full_name=full_name,
                                                   role=user_service.ROLE_ADMIN, must_change=False,
                                                   email=email, actor="setup")
                code = user_service.create_recovery_code(user_id, actor="setup")
                st.session_state[SETUP_CODE_KEY] = {"code": code, "user": user_service.authenticate(username, password)}
                st.rerun()
            except ValueError as error:
                st.error(str(error))


def _render_login() -> None:
    right = _auth_layout()
    with right:
        _title("Welcome back 👋", "Sign in to your IndusStock AI workspace.")
        notice = st.session_state.pop(NOTICE_KEY, None)
        if notice:
            st.success(notice) if notice.startswith("✅") else st.info(notice)
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Your username")
            password = st.text_input("Password", type="password", placeholder="Your password")
            submitted = st.form_submit_button("Sign in →", type="primary")
        if submitted:
            wait = _throttle_wait()
            if wait:
                st.error(f"Too many attempts. Please wait {wait} seconds and try again.")
            else:
                try:
                    _start_session(user_service.authenticate(username, password))
                except user_service.AuthError as error:
                    _note_failure()
                    st.error(str(error))
        if _link_button("🔑 Forgot password or username?", "to_recover"):
            st.session_state[VIEW_KEY] = "recover"
            st.rerun()
        ui.html(f'<div class="auth-note">{widgets._e(SITE_NAME)} · Authorised personnel only · Activity is logged</div>')


def _finish_recovery(message: str) -> None:
    st.session_state[NOTICE_KEY] = "✅ " + message
    st.session_state[VIEW_KEY] = "login"
    st.session_state.pop(EMAIL_SENT_KEY, None)
    st.rerun()


def _render_recover() -> None:
    right = _auth_layout()
    with right:
        recovered = st.session_state.get(RECOVERED_CODE_KEY)
        if recovered:  # password was reset with a recovery code: hand out the replacement code
            _title("Password changed ✅", "Your recovery code was used, so here is a new one. Save it now: it is shown once.")
            _recovery_code_box(recovered, "indusstock_new_recovery_code.txt")
            if st.button("Continue to sign in →", type="primary"):
                st.session_state.pop(RECOVERED_CODE_KEY, None)
                _finish_recovery("Password changed. Sign in with your new password.")
            return

        _title("Account recovery", "Choose how you would like to get back in.")
        if st.button("← Back to sign in"):
            st.session_state[VIEW_KEY] = "login"
            st.rerun()
        email_tab, code_tab, admin_tab, name_tab = st.tabs(
            ["📧 E-mail code", "🔑 Recovery code", "🛡️ Ask administrator", "🙋 Forgot username"])

        with email_tab:
            if not mailer.is_configured():
                st.info("E-mail sending is not set up on this system. Use a recovery code or ask the administrator.")
            else:
                st.caption("We e-mail a 6-digit code to the address saved in your account.")
                with st.form("recover_email_request"):
                    username = st.text_input("Username", key="rec_email_username")
                    send = st.form_submit_button("Send verification code")
                if send:
                    if _throttle_wait():
                        st.error("Too many attempts. Please wait a minute.")
                    else:
                        _note_failure()  # counts towards the per-session limit on e-mail requests
                        user_service.request_email_code(username)
                        st.session_state[EMAIL_SENT_KEY] = (username or "").strip().lower()
                        st.success(f"If that account has an e-mail address on file, a 6-digit code has been sent. "
                                   f"It is valid for {RESET_CODE_MINUTES} minutes.")
                if st.session_state.get(EMAIL_SENT_KEY):
                    with st.form("recover_email_confirm"):
                        code = st.text_input("6-digit code", max_chars=6)
                        new = st.text_input("New password", type="password", help=_password_hint())
                        confirm = st.text_input("Confirm new password", type="password")
                        go = st.form_submit_button("Reset password", type="primary")
                    if go:
                        try:
                            if new != confirm:
                                raise ValueError("Passwords do not match.")
                            user_service.reset_with_email_code(st.session_state[EMAIL_SENT_KEY], code, new)
                            _finish_recovery("Password changed. Sign in with your new password.")
                        except ValueError as error:
                            st.error(str(error))

        with code_tab:
            st.caption("Use the one-time recovery code you saved when your account was set up.")
            with st.form("recover_code_form"):
                username = st.text_input("Username", key="rec_code_username")
                code = st.text_input("Recovery code", placeholder="XXXX-XXXX-XXXX")
                new = st.text_input("New password", type="password", help=_password_hint(), key="rec_code_new")
                confirm = st.text_input("Confirm new password", type="password", key="rec_code_confirm")
                go = st.form_submit_button("Reset password", type="primary")
            if go:
                wait = _throttle_wait()
                try:
                    if wait:
                        raise ValueError(f"Too many attempts. Please wait {wait} seconds.")
                    if new != confirm:
                        raise ValueError("Passwords do not match.")
                    st.session_state[RECOVERED_CODE_KEY] = user_service.reset_with_recovery_code(username, code, new)
                    st.session_state.pop(FAILURES_KEY, None)
                    st.rerun()
                except user_service.AuthError as error:
                    _note_failure()
                    st.error(str(error))
                except ValueError as error:
                    st.error(str(error))

        with admin_tab:
            st.caption("No code? Send a request to the administrator. They will give you a temporary password.")
            with st.form("recover_admin_form", clear_on_submit=True):
                who = st.text_input("Your username or full name")
                note = st.text_area("Note for the administrator (optional)", height=80,
                                    placeholder="e.g. how to reach you: department, phone, shift")
                go = st.form_submit_button("Send request", type="primary")
            if go:
                try:
                    user_service.create_reset_request(who, note)
                    st.success("Request sent. The administrator will contact you with a temporary password.")
                except user_service.AuthError as error:
                    st.error(str(error))

        with name_tab:
            st.caption("Forgot your username?")
            if mailer.is_configured():
                with st.form("recover_username_form"):
                    address = st.text_input("E-mail address saved in your account")
                    go = st.form_submit_button("E-mail me my username")
                if go:
                    user_service.send_username_reminders(address)
                    st.success("If that address is registered, your username has been e-mailed to it.")
            st.info("You can also ask the administrator (use the **Ask administrator** tab and enter your full name). "
                    "The first administrator account created during setup is usually named **admin**.")


def _render_force_change(user: dict) -> None:
    right = _auth_layout()
    with right:
        _title("Set a new password 🔑", "For security, choose your own password before continuing.")
        with st.form("force_change_form"):
            current = st.text_input("Current (temporary) password", type="password")
            new = st.text_input("New password", type="password", help=_password_hint())
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Change password", type="primary")
        if submitted:
            try:
                if new != confirm:
                    raise ValueError("Passwords do not match.")
                user_service.change_own_password(user["id"], current, new)
                st.session_state[ACTIVITY_KEY] = time.time()
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        if st.button("Sign out"):
            logout("manual")


# ------------------------------------------------------------------ main gate
def require_login() -> dict:
    """Show setup / sign-in screens until someone is signed in. Returns the active user."""
    if user_service.count_users() == 0 or st.session_state.get(SETUP_CODE_KEY):
        _render_setup()  # also shows the one-time recovery code right after the account is created
        st.stop()

    session = current_user()
    if not session:
        if st.session_state.get(VIEW_KEY) == "recover":
            _render_recover()
        else:
            _render_login()
        st.stop()

    last = st.session_state.get(ACTIVITY_KEY, time.time())
    if time.time() - last > _timeout_minutes() * 60:
        logout("idle timeout", f"You were signed out after {_timeout_minutes()} minutes of inactivity.")
    st.session_state[ACTIVITY_KEY] = time.time()

    fresh = user_service.get_user(session["id"])  # picks up role changes and deactivation immediately
    if not fresh or not fresh["is_active"]:
        logout("account disabled", "Your account is no longer active.")
    st.session_state[SESSION_KEY] = {k: fresh[k] for k in ("id", "username", "full_name", "role")}
    if fresh["must_change_password"]:
        _render_force_change(fresh)
        st.stop()
    return st.session_state[SESSION_KEY]


def display_name(user: dict) -> str:
    return user["full_name"] or user["username"]
