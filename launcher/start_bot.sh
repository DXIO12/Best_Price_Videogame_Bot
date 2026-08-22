#!/usr/bin/env bash
# Runs the price-checking bot (headless, no GUI).
set -e
# The repo root is the import root — see start_gui.sh.
cd "$(dirname "$0")/.."
source venv/bin/activate
[ -f .env ] && chmod 600 .env
# Names the log file, so init_db's output lands in the bot's log.
export PRICE_BOT_PROCESS=bot
# Background bot runs in Release mode: no console, headless scraping.
export PRICE_BOT_DEBUG=0
export PRICE_BOT_HEADLESS=1
python -m application.database.init_db
python -m application.bot.bot
