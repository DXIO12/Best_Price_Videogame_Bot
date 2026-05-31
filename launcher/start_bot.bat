@echo off
REM Runs the price-checking bot (headless, no GUI).
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
python -m database.init_db
python -m bot.bot
pause
