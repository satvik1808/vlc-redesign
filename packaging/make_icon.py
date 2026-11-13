"""Render the cone artwork into packaging/app.ico (multi-size)."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402

from vlcredesign.icons import paint_cone  # noqa: E402


def png_bytes(size: int) -> bytes:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_cone(p, QRectF(size * 0.06, size * 0.04, size * 0.88, size * 0.92))
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def main() -> None:
    QGuiApplication(sys.argv)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [png_bytes(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    with open(out, "wb") as fh:
        fh.write(header + entries + b"".join(images))
    print("wrote", out)


if __name__ == "__main__":
    main()
