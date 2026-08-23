"""Every icon the GUI uses, as inline SVG rendered to QIcon on demand.

The SVGs are Material Design glyph paths kept **inline as bytes** rather than as
image files: no asset to ship, and no PyInstaller ``--add-data`` entry to keep in
sync with the build scripts.

Colour vocabulary, so a new icon lands on the right side of it:

* ``#9e9e9e`` grey — neutral. Anything that opens a panel, edits, or controls the
  bot without destroying data.
* ``#4caf50`` green — "make it go": Start and Continue.
* ``#cc3333`` red — **destructive only**. Currently just the per-row delete
  button, which draws its own glyph as text. Nothing else may borrow this red, or
  it stops meaning "this throws something away" — which is why Stop Bot is grey.

Icons are rendered lazily and cached: a ``QIcon`` cannot be built before a
``QApplication`` exists, so nothing here may run at import time. Call the
accessors from widget construction onwards and the cache makes repeat calls (the
per-row edit pencil, say) free.
"""

from functools import lru_cache

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer


# =========================================================
# SVG SOURCES
# =========================================================

# Pencil (Material "edit"), for the per-row quick-edit button. Grey, not red, so
# it doesn't read as destructive next to the delete icon it sits beside.
_EDIT_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25z'
    b'M20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0'
    b'l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>'
)

# Gear (Material "settings"), for the top-right settings button. Grey because it
# opens a configuration panel — it must not read as an action button.
_SETTINGS_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94'
    b'l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96'
    b'c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84'
    b'c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96'
    b'c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58'
    b'c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61'
    b'l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54'
    b'c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94'
    b'l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58z'
    b'M12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>'
    b'</svg>'
)

# Transport controls for the bot button row (Material "play_arrow", "pause",
# "stop", "refresh"). Play is the green one and is shared by Start and Continue.
_PLAY_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#4caf50" d="M8 5v14l11-7z"/></svg>'
)

_PAUSE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>'
)

_STOP_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M6 6h12v12H6z"/></svg>'
)

_RESTART_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M17.65 6.35A7.958 7.958 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08'
    b'A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>'
)

# Double circular arrow (Material "sync"), for the resolve-URLs button in the
# Shops column. Grey: it re-runs a search, it destroys nothing. Deliberately a
# different glyph from _RESTART_SVG, which already owns the single circular
# arrow over in the bot transport row — two distinct actions, two distinct
# glyphs.
_SYNC_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8'
    b'l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6'
    b' 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>'
    b'</svg>'
)


# Up + down arrows (Material "import_export"), for the header button that opens
# Settings on the Data tab. Grey: it opens a panel, it destroys nothing by
# itself — the destructive half of importing is guarded by its own dialog.
_DATA_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M9 3L5 6.99h3V14h2V6.99h3L9 3zm7 14.01V10h-2v7.01h-3'
    b'L15 21l4-3.99h-3z"/></svg>'
)

# =========================================================
# RENDERING
# =========================================================

# 64 px source: rendered well above the 16-22 px the buttons ask for, so Qt
# scales down (sharp) instead of up (blurry) on any display scaling factor.
_RENDER_SIZE = 64


@lru_cache(maxsize=None)
def render_svg_icon(svg_bytes: bytes, size: int = _RENDER_SIZE) -> QIcon:
    """Render an inline SVG to a QIcon. A QApplication must already exist.

    Cached on its arguments, so each icon is rasterised once per process no
    matter how many widgets ask for it. Exposed (rather than kept private) for
    one-off icons that don't warrant their own accessor below."""
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# =========================================================
# ACCESSORS
# =========================================================

def edit_icon() -> QIcon:
    """Grey pencil — per-row quick edit."""
    return render_svg_icon(_EDIT_SVG)


def settings_icon() -> QIcon:
    """Grey gear — opens the Settings dialog."""
    return render_svg_icon(_SETTINGS_SVG)


def play_icon() -> QIcon:
    """Green play triangle — Start Bot, and Continue Bot while paused."""
    return render_svg_icon(_PLAY_SVG)


def pause_icon() -> QIcon:
    """Grey pause bars — Pause Bot."""
    return render_svg_icon(_PAUSE_SVG)


def stop_icon() -> QIcon:
    """Grey stop square — Stop Bot. Grey, not red: see the module docstring."""
    return render_svg_icon(_STOP_SVG)


def restart_icon() -> QIcon:
    """Grey circular arrow — Restart Bot, shown in place of Start while paused."""
    return render_svg_icon(_RESTART_SVG)


def sync_icon() -> QIcon:
    """Grey double arrow — resolve missing shop URLs, in the Shops column."""
    return render_svg_icon(_SYNC_SVG)


def data_icon() -> QIcon:
    """Grey up/down arrows — opens Settings on the Data tab."""
    return render_svg_icon(_DATA_SVG)
