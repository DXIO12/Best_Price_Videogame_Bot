#!/usr/bin/env bash
# Runs the price-checking bot (headless, no GUI).
# Must be executed from the project root directory.
set -e
cd "$(dirname "$0")"
source venv/bin/activate
python bot.py
