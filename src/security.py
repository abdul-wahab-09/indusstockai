"""Password hashing and input validation (standard library only)."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import string

ALGORITHM = "pbkdf2_sha256"
# OWASP-recommended work factor for PBKDF2-HMAC-SHA256. Tests lower it through the environment.
ITERATIONS = int(os.environ.get("PASSWORD_HASH_ITERATIONS", "600000"))
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,30}$")


def hash_password(password: str) -> str:
    """Return 'pbkdf2_sha256$iterations$salt$hash' using a fresh random salt."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, hash_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one number.")
    if len(password) > 128:
        raise ValueError("Password is too long (maximum 128 characters).")


def normalize_username(username: str) -> str:
    name = (username or "").strip().lower()
    if not USERNAME_PATTERN.match(name):
        raise ValueError("Username must be 3-30 characters: letters, numbers, dot, dash or underscore.")
    return name


def generate_password(length: int = 12) -> str:
    """Random password that always satisfies the policy (no look-alike characters)."""
    letters = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    digits = "23456789"
    chars = [secrets.choice(letters), secrets.choice(letters.upper()), secrets.choice(digits)]
    chars += [secrets.choice(letters + digits) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def generate_recovery_code() -> str:
    """A one-time account recovery code such as 'K7QM-3XWD-R9TA' (about 59 bits of randomness)."""
    from .config import RECOVERY_ALPHABET

    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(12))
    return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def generate_numeric_code(digits: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(digits))
