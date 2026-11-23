"""Outgoing e-mail through any SMTP server (used for password-reset codes and username reminders).

Configure in .streamlit/secrets.toml (see secrets.toml.example): SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_FROM and SMTP_SECURITY ("starttls", "ssl" or "none").
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from .config import APP_NAME, get_secret


class MailError(RuntimeError):
    """The message could not be sent."""


def settings() -> dict:
    return {
        "host": get_secret("SMTP_HOST"),
        "port": int(get_secret("SMTP_PORT", "587") or 587),
        "user": get_secret("SMTP_USER"),
        "password": get_secret("SMTP_PASSWORD"),
        "sender": get_secret("SMTP_FROM") or get_secret("SMTP_USER"),
        "security": (get_secret("SMTP_SECURITY", "starttls") or "starttls").lower(),
    }


def is_configured() -> bool:
    cfg = settings()
    return bool(cfg["host"] and cfg["sender"])


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text e-mail. Raises MailError with a readable reason on failure."""
    cfg = settings()
    if not (cfg["host"] and cfg["sender"]):
        raise MailError("E-mail is not configured (SMTP_HOST / SMTP_FROM missing).")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{APP_NAME} <{cfg['sender']}>"
    message["To"] = to
    message.set_content(body)
    try:
        if cfg["security"] == "ssl":
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)
        with server:
            if cfg["security"] == "starttls":
                server.starttls(context=ssl.create_default_context())
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(f"{type(error).__name__}: {error}") from error
