#!/usr/bin/env bash
# Runs the desktop GUI (PyQt6).
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate
[ -f .env ] && chmod 600 .env
# No forced headless: the GUI honours the debug_mode setting (Settings menu).
python -m database.init_db
python -m gui.main_window
