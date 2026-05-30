#!/usr/bin/env bash
# Runs the desktop GUI (PyQt6).
# Must be executed from the project root directory.
set -e
cd "$(dirname "$0")"
source venv/bin/activate
python -m gui.main_window
