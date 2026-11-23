@echo off
REM One-click launcher for Windows: creates a virtual environment on first run, installs packages, starts the app.
cd /d "%~dp0"
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
pip install -U google-genai --quiet
if not exist .streamlit\secrets.toml (
    echo.
    echo NOTE: .streamlit\secrets.toml not found. The AI assistant needs a Gemini API key.
    echo Copy .streamlit\secrets.toml.example to .streamlit\secrets.toml and add your key.
    echo Inventory features work without it.
    echo.
)
streamlit run app.py
pause
