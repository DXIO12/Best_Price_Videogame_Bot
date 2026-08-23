#!/usr/bin/env bash
# Builds a standalone executable for the GUI using PyInstaller.
# The executable ends up in dist/price_bot_gui/
#
# NOTE: Playwright browsers are NOT bundled. After distributing the exe,
# the user must run:  playwright install chromium
set -euo pipefail

# The repo root is the import root, and also where PyInstaller writes its own
# temporary build/ tree — which is why these scripts live in packaging/ and not
# in a folder named build/.
cd "$(dirname "$0")/.."
source venv/bin/activate

pip install pyinstaller --quiet

# Icon assets are generated, not hand-maintained; refresh them so the exe never
# ships a stale one.
python packaging/make_icons.py

# ---------------------------------------------------------------------------
# Staging copy of application/
# ---------------------------------------------------------------------------
# The whole source tree ships as *data*, not just as compiled modules, because
# two places read it off disk at runtime and would come up empty otherwise:
#
#   * gui/add_product_dialog.py builds the shop dropdown from os.listdir() over
#     shops/*.py — inside a bundle those .py files only exist if copied in.
#   * language_selector/translator.py globs languages/*.json.
#
# It is staged rather than added directly so the databases can be left behind.
# --add-data has no exclude switch, and application/database/tracker.db is the
# live database: an earlier version of this script deleted it before building,
# which is not a price worth paying to keep test data out of a bundle.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -r application "$STAGE/application"
find "$STAGE/application" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE/application" -type f \
     \( -name '*.db' -o -name '*.db.*' -o -name '*.bak*' \) -delete

echo "Staged application/ without databases:"
find "$STAGE/application" -name '*.db*' | grep . && \
    { echo "ERROR: a database survived staging" >&2; exit 1; } || echo "  clean."

pyinstaller \
    --noconfirm \
    --onedir \
    --windowed \
    --name price_bot_gui \
    --icon assets/price-bot.ico \
    --add-data "$STAGE/application:application" \
    --hidden-import "PyQt6.sip" \
    --hidden-import "playwright.sync_api" \
    application/gui/main_window.py

# ---------------------------------------------------------------------------
# Browsers
# ---------------------------------------------------------------------------
# Downloaded straight into the distribution rather than copied out of the local
# cache: PLAYWRIGHT_BROWSERS_PATH makes Playwright's own installer lay the files
# out exactly where runtime_config.use_bundled_browsers() will look for them, on
# every OS, with no path guessing.
#
# The full Chromium build, and --no-shell to skip the lightweight "headless
# shell": BrowserManager passes channel="chromium" because some shops render no
# price in the shell, so it would be 257 MB that never runs. ffmpeg comes along
# with the chromium install and is only used for video recording, which nothing
# here does — dropped afterwards.
#
# This is what lets a distributed copy work with no Python on the machine —
# "playwright install chromium", which Playwright's error message tells the user
# to run, is not a command they could execute.
# Downloaded into a cache OUTSIDE dist/ and copied in, not straight into the
# distribution. PyInstaller's --noconfirm deletes dist/price_bot_gui wholesale
# on every build, browsers/ included, so downloading there means re-fetching
# 370 MB on every single rebuild. A local copy takes seconds instead.
BROWSER_CACHE="$PWD/.browser-cache"
export PLAYWRIGHT_BROWSERS_PATH="$BROWSER_CACHE"

echo "Ensuring Chromium is in $BROWSER_CACHE ..."
# ffmpeg comes along with the chromium install and is only used for video
# recording, which nothing here does. It stays in the cache rather than being
# deleted — deleting it just makes the next build download it again — and
# simply never gets copied into the distribution below.
python -m playwright install chromium --no-shell

versions=$(find "$BROWSER_CACHE" -maxdepth 1 -name 'chromium-*' | wc -l)
if [ "$versions" -gt 1 ]; then
    echo "  Note: $versions Chromium versions cached. Delete .browser-cache/ to trim." >&2
fi

echo "Copying Chromium into the distribution..."
mkdir -p dist/price_bot_gui/browsers
cp -r "$BROWSER_CACHE"/chromium-* dist/price_bot_gui/browsers/

echo ""
echo "Build complete. Executable is in dist/price_bot_gui/"
du -sh dist/price_bot_gui/
echo ""
echo "It is self-contained: Python, Chromium and all dependencies are inside."
echo "The only setup left is the Telegram token, entered in Settings on first run."
