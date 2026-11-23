"""Check that the Gemini API key in .streamlit/secrets.toml works and show a clear diagnosis.

Usage:  python scripts/test_gemini_connection.py
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import ai_assistant  # noqa: E402
from src.config import GEMINI_MODEL  # noqa: E402

try:
    with open(ROOT / ".streamlit" / "secrets.toml", "rb") as handle:
        secrets = tomllib.load(handle)
except FileNotFoundError:
    sys.exit("secrets.toml not found. Copy .streamlit/secrets.toml.example to .streamlit/secrets.toml first.")

result = ai_assistant.test_connection(secrets.get("GEMINI_API_KEY"), secrets.get("GEMINI_MODEL", GEMINI_MODEL))
print("\nSUCCESS" if result["ok"] else "\nFAILED")
print(result["message"])
