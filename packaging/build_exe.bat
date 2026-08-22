@echo off
setlocal
REM Builds a standalone executable for the GUI using PyInstaller.
REM The executable ends up in dist\price_bot_gui\
REM
REM NOTE: Playwright browsers are NOT bundled. After distributing the exe,
REM the user must run:  playwright install chromium
REM
REM The repo root is the import root, and also where PyInstaller writes its own
REM temporary build\ tree - which is why these scripts live in packaging\ and
REM not in a folder named build\.
cd /d "%~dp0\.."
call venv\Scripts\activate.bat

pip install pyinstaller --quiet

REM Icon assets are generated, not hand-maintained; refresh them so the exe
REM never ships a stale one.
python packaging\make_icons.py

REM ---------------------------------------------------------------------------
REM Staging copy of application\
REM ---------------------------------------------------------------------------
REM The whole source tree ships as *data*, not just as compiled modules, because
REM two places read it off disk at runtime and would come up empty otherwise:
REM
REM   * gui\add_product_dialog.py builds the shop dropdown from os.listdir() over
REM     shops\*.py - inside a bundle those .py files only exist if copied in.
REM   * language_selector\translator.py globs languages\*.json.
REM
REM It is staged rather than added directly so the databases can be left behind.
REM --add-data has no exclude switch, and application\database\tracker.db is the
REM live database: an earlier version of this script deleted it before building,
REM which is not a price worth paying to keep test data out of a bundle.
set "STAGE=%TEMP%\price_bot_build_stage"
if exist "%STAGE%" rd /s /q "%STAGE%"
robocopy application "%STAGE%\application" /E /XD __pycache__ /XF *.db *.db.* *.bak* >nul
REM robocopy uses 0-7 for success and 8+ for failure, unlike every other tool.
if %errorlevel% geq 8 (
    echo ERROR: could not stage application\ >&2
    exit /b 1
)

pyinstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name price_bot_gui ^
    --icon assets\price-bot.ico ^
    --add-data "%STAGE%\application;application" ^
    --hidden-import "PyQt6.sip" ^
    --hidden-import "playwright.sync_api" ^
    application\gui\main_window.py

rd /s /q "%STAGE%"

echo.
echo Build complete. Executable is in dist\price_bot_gui\
echo Remember, on the target machine:
echo   1. run "playwright install chromium"
echo   2. put your .env NEXT TO the executable - a frozen build resolves it
echo      from the working directory, not from the source tree.
pause
