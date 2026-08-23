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

REM ---------------------------------------------------------------------------
REM Browsers
REM ---------------------------------------------------------------------------
REM Downloaded straight into the distribution rather than copied out of the local
REM cache: PLAYWRIGHT_BROWSERS_PATH makes Playwright's own installer lay the files
REM out exactly where runtime_config.use_bundled_browsers() will look for them.
REM
REM The full Chromium build, and --no-shell to skip the lightweight "headless
REM shell": BrowserManager passes channel="chromium" because some shops render no
REM price in the shell, so it would be 257 MB that never runs. ffmpeg comes along
REM with the chromium install and is only used for video recording - dropped.
REM Downloaded into a cache OUTSIDE dist\ and copied in, not straight into the
REM distribution. PyInstaller's --noconfirm deletes dist\price_bot_gui wholesale
REM on every build, browsers\ included, so downloading there means re-fetching
REM 370 MB on every single rebuild. A local copy takes seconds instead.
set "BROWSER_CACHE=%CD%\.browser-cache"
set "PLAYWRIGHT_BROWSERS_PATH=%BROWSER_CACHE%"

echo Ensuring Chromium is in %BROWSER_CACHE% ...
REM ffmpeg comes along with the chromium install and is only used for video
REM recording, which nothing here does. It stays in the cache rather than being
REM deleted - deleting it just makes the next build download it again - and the
REM robocopy below excludes it from the distribution.
python -m playwright install chromium --no-shell

echo Copying Chromium into the distribution...
mkdir "dist\price_bot_gui\browsers" 2>nul
robocopy "%BROWSER_CACHE%" "dist\price_bot_gui\browsers" /E /XD ffmpeg-* >nul
if %errorlevel% geq 8 (
    echo ERROR: could not copy the browsers into the distribution >&2
    exit /b 1
)

echo.
echo Build complete. Executable is in dist\price_bot_gui\
echo.
echo It is self-contained: Python, Chromium and all dependencies are inside.
echo The only setup left is the Telegram token, entered in Settings on first run.
pause
