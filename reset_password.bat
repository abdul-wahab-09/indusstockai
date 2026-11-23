@echo off
REM Double-click to reset a forgotten password (close the app first).
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo Please run run_app.bat once first so the environment is created.
    pause
    exit /b
)
call .venv\Scripts\activate.bat
echo.
echo Accounts on this system:
python scripts\reset_admin_password.py --list
echo.
set /p TARGET=Type the username to reset (for example admin): 
python scripts\reset_admin_password.py %TARGET%
echo.
pause
