#!/usr/bin/env bash
# Turns dist/price_bot_gui/ into a single zip ready to hand to someone.
#
# Run packaging/build_exe.sh first. This only packages what that produced; it
# does not build, so a mistake here costs seconds rather than ten minutes.
#
#   ./packaging/make_release.sh          -> dist/price-bot-linux.zip
#   ./packaging/make_release.sh windows  -> dist/price-bot-windows.zip
#
# (The Windows zip is normally produced by the GitHub Actions workflow, which is
# the only way to build a Windows .exe from a Linux machine — PyInstaller does
# not cross-compile.)
set -euo pipefail
cd "$(dirname "$0")/.."

PLATFORM="${1:-linux}"
SRC="dist/price_bot_gui"
OUT="dist/price-bot-$PLATFORM.zip"

[ -d "$SRC" ] || { echo "No $SRC — run packaging/build_exe.sh first." >&2; exit 1; }

# Refuse to ship a database or a .env. Both are things a developer accumulates
# in dist/ by running the build output, and either one would hand a tester
# someone else's data — or, in the case of .env, a live bot token.
leaked="$(find "$SRC" \( -name '*.db' -o -name '.env' \) 2>/dev/null || true)"
if [ -n "$leaked" ]; then
    echo "Refusing to package. Remove these first:" >&2
    echo "$leaked" >&2
    exit 1
fi

[ -d "$SRC/browsers" ] || { echo "No browsers/ in the build — testers would have no Chromium." >&2; exit 1; }

# The end-user guide travels inside the zip; it is the first thing they open.
cp packaging/DISTRIBUTION_README.md "$SRC/LEEME.md"

rm -f "$OUT"
( cd dist && zip -qr "../$OUT" price_bot_gui )

echo "Wrote $OUT"
echo "  unpacked: $(du -sh "$SRC" | cut -f1)"
echo "  zipped:   $(du -sh "$OUT" | cut -f1)"
echo
echo "Hand the zip over as-is. The person unzips it and opens the executable;"
echo "the only setup left is pasting a Telegram token into Settings."
