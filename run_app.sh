#!/usr/bin/env bash
# Launcher for Linux / macOS
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --quiet
pip install -U google-genai --quiet
streamlit run app.py
