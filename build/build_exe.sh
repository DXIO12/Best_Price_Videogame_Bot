#!/usr/bin/env bash
# Builds a standalone executable for the GUI using PyInstaller.
# The executable ends up in dist/price_bot_gui/
#
# NOTE: Playwright browsers are NOT bundled. After distributing the exe,
# the user must run:  playwright install chromium
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate

pip install pyinstaller --quiet

# Remove local DB so no test data is bundled in the package.
# The app creates a fresh tracker.db next to the executable on first run.
rm -f database/tracker.db

pyinstaller \
    --noconfirm \
    --onedir \
    --windowed \
    --name price_bot_gui \
    --add-data "database:database" \
    --add-data "shops:shops" \
    --add-data "services:services" \
    --add-data "gui:gui" \
    --add-data "bot:bot" \
    --add-data "config:config" \
    --add-data "language_selector:language_selector" \
    --hidden-import "PyQt6.sip" \
    --hidden-import "playwright.sync_api" \
    gui/main_window.py

echo ""
echo "Build complete. Executable is in dist/price_bot_gui/"
echo "Remember: run 'playwright install chromium' on the target machine before using the bot."
