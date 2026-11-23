"""Central configuration for Electrical and Electronic Spare Parts Intelligence."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# ------------------------------------------------------------------ branding
APP_NAME = "IndusStock AI"
APP_FULL_NAME = "Electrical and Electronic Spare Parts Intelligence"
APP_TAGLINE = "Smart inventory management for industrial electrical & electronic systems"
SITE_NAME = "Foils and Metals Mill-3"
APP_ICON = "⚡"
APP_VERSION = "3.0.0"
ASSISTANT_NAME = "ElectroBot"

# ------------------------------------------------------------------ paths / runtime
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("INVENTORY_DB_PATH", BASE_DIR / "data" / "inventory.db"))
LOCAL_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Karachi")  # DB stores UTC
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# ------------------------------------------------------------------ inventory rules
CATEGORIES = [
    "Contactor",
    "Circuit Breaker / MCB / MCCB",
    "Fuse",
    "Relay",
    "Sensor / Transducer",
    "VFD / Drive",
    "PLC / I/O Module",
    "HMI / Display",
    "Power Supply",
    "Motor",
    "Bearing",
    "Switch / Push Button",
    "Transformer",
    "Capacitor",
    "PCB / Electronic Card",
    "Cable / Connector",
    "Other",
]
UNITS = ["pcs", "set", "pair", "meter", "kg", "box"]
STOCK_IN = "Stock In"
STOCK_OUT = "Stock Out"
REORDER_MULTIPLIER = 2  # suggested reorder target = minimum stock x this value


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a setting: in-app override, then Streamlit secrets, then environment variables."""
    try:
        import streamlit as st

        override = st.session_state.get(f"override_{name}")
        if override:
            return str(override)
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file, or Streamlit not running
        pass
    return os.environ.get(name, default)


SECRETS_PATH = BASE_DIR / ".streamlit" / "secrets.toml"


def save_secret(name: str, value: str) -> None:
    """Write or update NAME = "value" in .streamlit/secrets.toml (other lines are kept)."""
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = SECRETS_PATH.read_text(encoding="utf-8").splitlines() if SECRETS_PATH.exists() else []
    new_line = f"{name} = {json.dumps(value)}"
    for index, line in enumerate(lines):
        if re.match(rf"\s*{re.escape(name)}\s*=", line):
            lines[index] = new_line
            break
    else:
        lines.append(new_line)
    SECRETS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ account recovery
RESET_CODE_MINUTES = 15          # validity of an emailed verification code
RESET_MAX_REQUESTS_PER_HOUR = 3  # emailed codes per account per hour
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no look-alike characters
