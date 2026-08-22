#!/usr/bin/env bash
# Stops the price-checking bot started by start_bot.sh.
#
# Deliberately not a bare `pkill -f`. Matching a pattern against every command
# line on the machine also matches the shell that is running *this* script if
# the pattern happens to appear in its command line — which is how a plain
# `pkill -f "bot.bot"` can kill its own caller and still report success. Each
# candidate is therefore confirmed to be a python process before it is signalled,
# and the current shell is skipped outright.
PATTERN='python -m application\.bot\.bot'

targets=()
for pid in $(pgrep -f "$PATTERN" 2>/dev/null); do
    [ "$pid" = "$$" ] && continue
    # `ps -o comm=` rather than /proc, so this still works on macOS.
    case "$(ps -o comm= -p "$pid" 2>/dev/null | xargs -r basename)" in
        python*) targets+=("$pid") ;;
    esac
done

if [ ${#targets[@]} -eq 0 ]; then
    echo "Bot was not running."
    exit 0
fi

kill "${targets[@]}" 2>/dev/null
echo "Bot stopped. (pid ${targets[*]})"
