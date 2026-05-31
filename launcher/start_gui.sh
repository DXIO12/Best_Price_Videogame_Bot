#!/usr/bin/env bash
# Runs the desktop GUI (PyQt6).
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate
python -m database.init_db
python -m gui.main_window
