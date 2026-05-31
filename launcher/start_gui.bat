@echo off
REM Runs the desktop GUI (PyQt6).
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
if exist .env (
    icacls .env /inheritance:r /grant:r "%USERNAME%:(R)" >nul 2>&1
)
python -m database.init_db
python -m gui.main_window
pause
