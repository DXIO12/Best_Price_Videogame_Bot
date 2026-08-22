@echo off
REM Runs the price-checking bot (headless, no GUI).
REM The repo root is the import root - see start_gui.bat.
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
if exist .env (
    icacls .env /inheritance:r /grant:r "%USERNAME%:(R)" >nul 2>&1
)
REM Names the log file, so init_db's output lands in the bot's log.
set PRICE_BOT_PROCESS=bot
REM Background bot runs in Release mode: no console, headless scraping.
set PRICE_BOT_DEBUG=0
set PRICE_BOT_HEADLESS=1
python -m application.database.init_db
python -m application.bot.bot
pause
