#!/usr/bin/env bash
# Stops the price-checking bot started by start_bot.sh.
if pkill -f "bot.bot"; then
    echo "Bot stopped."
else
    echo "Bot was not running."
fi
