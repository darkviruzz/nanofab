"""Render `nanofab_v3/assets/nanofab.svg` into the `.ico` the delivery uses (E20).

    python scripts/make_icon.py

Run by hand when the SVG changes; the result is **committed**, because a build
that had to rasterise its own icon would need Qt's SVG plugin on the build
machine and would produce a slightly different file on every Qt version. The SVG
is the source, the `.ico` is the artefact, and `tests/test_icon.py` checks that
the artefact is an `.ico` with the four sizes rather than re-rendering it — which
would pin somebody else's rasteriser as if it were our number.

Four sizes, because that is what Windows asks for: 16 (tab and taskbar), 32
(title bar), 48 (Explorer's medium view), 256 (its large one). The three small
ones are written as 32-bit DIBs and 256 as an embedded PNG, which is the layout
every ICO reader since Vista handles and the one PyInstaller's resource writer
expects.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "nanofab_v3" / "assets" / "nanofab.svg"
ICO = ROOT / "nanofab_v3" / "assets" / "nanofab.ico"
SIZES = (16, 32, 48, 256)


def _render(size: int) -> "QImage":  # noqa: F821 - Qt is imported inside main()
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    image = QImage(QSize(size, size), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(str(SVG)).render(painter)
    painter.end()
    return image


def _dib(image) -> bytes:
    """One icon entry as a 32-bit bottom-up DIB with an empty AND mask."""
    width, height = image.width(), image.height()
    header = struct.pack(
        "<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, 0, 0, 0, 0, 0
    )
    rows = []
    for y in range(height - 1, -1, -1):
        row = bytearray()
        for x in range(width):
            pixel = image.pixelColor(x, y)
            row += bytes((pixel.blue(), pixel.green(), pixel.red(), pixel.alpha()))
        rows.append(bytes(row))
    mask_stride = ((width + 31) // 32) * 4
    return header + b"".join(rows) + b"\x00" * (mask_stride * height)


def _png(image) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def build() -> Path:
    entries: list[bytes] = []
    for size in SIZES:
        image = _render(size)
        entries.append(_png(image) if size >= 256 else _dib(image))
    offset = 6 + 16 * len(entries)
    directory = struct.pack("<HHH", 0, 1, len(entries))
    for size, payload in zip(SIZES, entries):
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)
    ICO.write_bytes(directory + b"".join(entries))
    return ICO


def main() -> int:
    if not SVG.is_file():
        print(f"no SVG at {SVG}", file=sys.stderr)
        return 2
    written = build()
    print(f"wrote {written} ({written.stat().st_size} bytes, sizes {SIZES})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
