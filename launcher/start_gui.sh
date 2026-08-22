#!/usr/bin/env bash
# Runs the desktop GUI (PyQt6).
set -e
# The repo root is the import root: every internal import is absolute and
# `application.`-prefixed, so we stay here rather than descending into
# application/.
cd "$(dirname "$0")/.."
source venv/bin/activate
[ -f .env ] && chmod 600 .env
# Names the log file, so init_db's output lands in the GUI's log instead of a
# stray price_bot_app.log. See config/runtime_config.py::process_name.
export PRICE_BOT_PROCESS=gui
# No forced headless: the GUI honours the debug_mode setting (Settings menu).
python -m application.database.init_db
python -m application.gui.main_window
