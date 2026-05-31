@echo off
REM Runs the desktop GUI (PyQt6).
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
python -m database.init_db
python -m gui.main_window
pause
