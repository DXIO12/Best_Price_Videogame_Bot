@echo off
REM Runs the price-checking bot (headless, no GUI).
cd /d "%~dp0\.."
call venv\Scripts\activate.bat
if exist .env (
    icacls .env /inheritance:r /grant:r "%USERNAME%:(R)" >nul 2>&1
)
REM Background bot runs in Release mode: no console, headless scraping.
set PRICE_BOT_DEBUG=0
set PRICE_BOT_HEADLESS=1
python -m database.init_db
python -m bot.bot
pause
