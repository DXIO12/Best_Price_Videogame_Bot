@echo off
REM Runs the price-checking bot (headless, no GUI).
REM Must be executed from the project root directory.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python bot.py
pause
