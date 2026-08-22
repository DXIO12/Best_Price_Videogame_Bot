#!/usr/bin/env bash
# Installs (or removes) the "Price Bot" desktop entry for the current user.
#
# Left click on the entry opens the GUI; right click offers the two bot
# actions, so one icon covers all three launcher scripts and the application
# menu does not gain three near-identical entries.
#
#   ./launcher/install_launcher.sh              install
#   ./launcher/install_launcher.sh --uninstall  remove
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_ID="price-bot"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DESKTOP_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_FILE="$DESKTOP_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.png"

refresh_menu() {
    # Both are best-effort: plenty of desktops pick the change up on their own,
    # and neither exists on a minimal install.
    command -v update-desktop-database >/dev/null && \
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null && \
        gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$DESKTOP_FILE" "$ICON_FILE"
    refresh_menu
    echo "Removed $DESKTOP_FILE"
    exit 0
fi

if [ ! -f "$REPO/assets/$APP_ID.png" ]; then
    echo "Icon missing — generating it." >&2
    "$REPO/venv/bin/python" "$REPO/packaging/make_icons.py"
fi

mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
install -m 644 "$REPO/assets/$APP_ID.png" "$ICON_FILE"

# The icon is referenced by absolute path rather than by theme name: the theme
# cache may not have been rebuilt yet, and an unresolvable Icon= silently
# renders as a blank tile.
sed -e "s|@REPO@|$REPO|g" -e "s|@ICON@|$ICON_FILE|g" \
    "$REPO/launcher/$APP_ID.desktop.in" > "$DESKTOP_FILE"

# GNOME refuses to launch an entry that is not executable.
chmod +x "$DESKTOP_FILE"

if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate "$DESKTOP_FILE" && echo "desktop-file-validate: OK"
fi

refresh_menu

echo "Installed $DESKTOP_FILE"
echo "  icon:  $ICON_FILE"
echo "  repo:  $REPO"
echo
echo "\"Price Bot\" should now be in your application menu. Right-click it for"
echo "the headless start/stop actions."
