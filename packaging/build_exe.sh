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

echo ""
echo "Build complete. Executable is in dist/price_bot_gui/"
echo "Remember, on the target machine:"
echo "  1. run 'playwright install chromium'"
echo "  2. put your .env NEXT TO the executable — a frozen build resolves it"
echo "     from the working directory, not from the source tree."
