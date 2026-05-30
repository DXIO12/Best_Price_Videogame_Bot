@echo off
REM Runs the desktop GUI (PyQt6).
REM Must be executed from the project root directory.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m gui.main_window
pause
