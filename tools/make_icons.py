#!/usr/bin/env python3
"""Build the app icons from assets/PhoneBKP_Logo.webp (needs only PySide6).

    .venv/bin/python tools/make_icons.py

Writes:
    assets/icon.png                     512 px, transparent background (window icon)
    assets/icon.ico                     Windows icon, 16-256 px (program file, window)
    assets/hicolor/<N>x<N>/apps/fast-smartphone-media-backup.png   Linux icon theme sizes

The white background is turned transparent ("colour to alpha" from white, only in the area
connected to the image border), so the soft shadow stays as a faint shadow and the white
inside the arrow stays white.
"""

import struct
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "PhoneBKP_Logo.webp"
NAME = "fast-smartphone-media-backup"
LINUX_SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
BG_MIN = 200          # a pixel belongs to the background area if all channels are at least this bright


def transparent_background(img: QImage) -> QImage:
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    buf = bytearray(img.constBits().tobytes())        # BGRA per pixel
    stride = img.bytesPerLine()

    def px(x, y):
        i = y * stride + x * 4
        return buf[i], buf[i + 1], buf[i + 2]

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))
    while q:
        x, y = q.popleft()
        k = y * w + x
        if seen[k]:
            continue
        b, g, r = px(x, y)
        if min(r, g, b) < BG_MIN:
            continue
        seen[k] = 1
        # colour to alpha (from white)
        a = max(255 - r, 255 - g, 255 - b) / 255.0
        i = y * stride + x * 4
        if a <= 0.02:
            buf[i:i + 4] = b"\0\0\0\0"
        else:
            for c in range(3):
                buf[i + c] = max(0, min(255, round(255 - (255 - buf[i + c]) / a)))
            buf[i + 3] = round(a * 255)
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))
    return QImage(bytes(buf), w, h, stride, QImage.Format_ARGB32).copy()


def square_crop(img: QImage, margin=0.04) -> QImage:
    """Crop to the visible content (ignoring the faint shadow) and centre it on a square."""
    w, h = img.width(), img.height()
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if (img.pixel(x, y) >> 24) > 96:
                xs.append(x)
                ys.append(y)
    box = QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    side = int(max(box.width(), box.height()) * (1 + 2 * margin))
    out = QImage(side, side, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawImage((side - box.width()) // 2, (side - box.height()) // 2, img, box.x(), box.y(),
                box.width(), box.height())
    p.end()
    return out


def scaled(img: QImage, n: int) -> QImage:
    # Several halving steps give cleaner small icons than one big jump.
    cur = img
    while cur.width() > 2 * n:
        cur = cur.scaled(cur.width() // 2, cur.height() // 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return cur.scaled(n, n, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.WriteOnly)
    img.save(b, "PNG")
    return bytes(ba)


def write_ico(path: Path, images):
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    blobs = [png_bytes(im) for im in images]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for im, data in zip(images, blobs):
        s = im.width()
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(out + b"".join(blobs))


def main():
    QGuiApplication(sys.argv[:1])
    src = QImage(str(SRC))
    if src.isNull():
        sys.exit(f"Cannot read {SRC}")
    master = square_crop(transparent_background(src))
    print(f"source {src.width()}x{src.height()} -> master {master.width()}x{master.height()}")
    assets = ROOT / "assets"
    scaled(master, 512).save(str(assets / "icon.png"))
    for n in LINUX_SIZES:
        d = assets / "hicolor" / f"{n}x{n}" / "apps"
        d.mkdir(parents=True, exist_ok=True)
        scaled(master, n).save(str(d / f"{NAME}.png"))
    write_ico(assets / "icon.ico", [scaled(master, n) for n in ICO_SIZES])
    print("written: assets/icon.png, assets/icon.ico, assets/hicolor/*")


if __name__ == "__main__":
    main()
