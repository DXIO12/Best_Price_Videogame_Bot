@echo off
REM Builds a standalone executable for the GUI using PyInstaller.
REM The executable ends up in dist\price_bot_gui\
REM
REM NOTE: Playwright browsers are NOT bundled. After distributing the exe,
REM the user must run:  playwright install chromium
cd /d "%~dp0\.."
call venv\Scripts\activate.bat

pip install pyinstaller --quiet

REM Remove local DB so no test data is bundled in the package.
REM The app creates a fresh tracker.db next to the executable on first run.
if exist database\tracker.db del /f database\tracker.db

pyinstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name price_bot_gui ^
    --add-data "database;database" ^
    --add-data "shops;shops" ^
    --add-data "services;services" ^
    --add-data "gui;gui" ^
    --add-data "bot;bot" ^
    --add-data "config;config" ^
    --hidden-import "PyQt6.sip" ^
    --hidden-import "playwright.sync_api" ^
    gui\main_window.py

echo.
echo Build complete. Executable is in dist\price_bot_gui\
echo Remember: run "playwright install chromium" on the target machine before using the bot.
pause
