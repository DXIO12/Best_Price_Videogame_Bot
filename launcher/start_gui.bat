@echo off
REM Runs the desktop GUI (PyQt6).
REM The repo root is the import root: every internal import is absolute and
REM `application.`-prefixed, so we stay here rather than descending into
REM application\.
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
if exist .env (
    icacls .env /inheritance:r /grant:r "%USERNAME%:(R)" >nul 2>&1
)
REM Names the log file, so init_db's output lands in the GUI's log instead of a
REM stray price_bot_app.log. See config\runtime_config.py::process_name.
set PRICE_BOT_PROCESS=gui
REM No forced headless: the GUI honours the debug_mode setting (Settings menu).
python -m application.database.init_db
python -m application.gui.main_window
pause
