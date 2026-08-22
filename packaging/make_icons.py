"""Generate the desktop-launcher icon assets from ``assets/price-bot.svg``.

Writes ``assets/price-bot.png`` (256x256, used by the Linux ``.desktop`` entry)
and ``assets/price-bot.ico`` (multi-size, used by the Windows shortcut and by
PyInstaller's ``--icon``). Both are committed: the installers reference them by
path and must not depend on anyone having run this first. Re-run it after
editing the SVG — ``build_exe.sh`` does so on every build.

No new dependency. Rendering goes through ``QSvgRenderer``, exactly as
``application.gui.icons`` already does for the in-app glyphs, and Qt writes the
PNGs. The ICO *container* is assembled here by hand because Qt's ICO writer
stores a single image, and a one-size icon is what makes a Windows shortcut
look blurry in the taskbar.
"""

import struct
import sys
from pathlib import Path

# Must be set before QGuiApplication: this renders on a build machine or in CI,
# where there is no display to connect to.
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"
SVG = ASSETS / "price-bot.svg"

# Every size Windows picks between, smallest first. 256 is the one Linux uses.
ICO_SIZES = (16, 32, 48, 64, 128, 256)
PNG_SIZE = 256


def render(renderer: QSvgRenderer, size: int) -> QImage:
    """Rasterise the SVG into a transparent square image of ``size`` px."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    return image


def to_png_bytes(image: QImage) -> bytes:
    # QBuffer() with no argument owns its byte array. Passing one in —
    # QBuffer(QByteArray()) — hands it a pointer to a temporary that Python
    # frees on the next line, and Qt then writes into freed memory.
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError(f"Qt failed to encode a {image.width()}px PNG")
    buffer.close()
    return bytes(buffer.data())


def build_ico(frames: dict[int, bytes]) -> bytes:
    """Wrap already-encoded PNGs in an ICO container.

    PNG-compressed entries are what Windows has accepted since Vista, so the
    frames go in verbatim. Layout: a 6-byte ICONDIR, then one 16-byte
    ICONDIRENTRY per frame, then the payloads."""
    entries, payloads = [], []
    offset = 6 + 16 * len(frames)
    for size in sorted(frames):
        data = frames[size]
        # A 256px side is stored as 0 — the field is a single byte.
        side = 0 if size >= 256 else size
        entries.append(
            struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        )
        payloads.append(data)
        offset += len(data)
    header = struct.pack("<HHH", 0, 1, len(frames))  # reserved, type=icon, count
    return header + b"".join(entries) + b"".join(payloads)


def main() -> int:
    if not SVG.is_file():
        print(f"error: {SVG} not found", file=sys.stderr)
        return 1

    # Held in a local, not discarded: a QGuiApplication that gets garbage
    # collected while a QPainter is alive segfaults the interpreter.
    _app = QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"error: {SVG} is not valid SVG", file=sys.stderr)
        return 1

    frames = {size: to_png_bytes(render(renderer, size)) for size in ICO_SIZES}

    png_path = ASSETS / "price-bot.png"
    png_path.write_bytes(frames[PNG_SIZE])

    ico_path = ASSETS / "price-bot.ico"
    ico_path.write_bytes(build_ico(frames))

    print(f"wrote {png_path.relative_to(REPO_ROOT)}  ({png_path.stat().st_size:,} bytes)")
    print(
        f"wrote {ico_path.relative_to(REPO_ROOT)}  "
        f"({ico_path.stat().st_size:,} bytes, sizes: {', '.join(map(str, ICO_SIZES))})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
