#!/usr/bin/env bash
# Runs the price-checking bot (headless, no GUI).
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate
[ -f .env ] && chmod 600 .env
# Background bot runs in Release mode: no console, headless scraping.
export PRICE_BOT_DEBUG=0
export PRICE_BOT_HEADLESS=1
python -m database.init_db
python -m bot.bot
