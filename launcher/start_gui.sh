#!/usr/bin/env bash
# Runs the desktop GUI (PyQt6).
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate
[ -f .env ] && chmod 600 .env
export PRICE_BOT_HEADLESS=1
python -m database.init_db
python -m gui.main_window
