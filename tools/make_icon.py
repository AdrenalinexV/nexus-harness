"""Draw the app icon and write it as a PNG, with no imaging library.

`rust` tooling wants an `.ico` and a few PNG sizes; `tauri icon` derives all of them from one 1024 px
source. This script is that source: a rounded dark tile with the harness mark (a diamond ring, the same
shape the plan uses for a closed phase).

    python tools/make_icon.py apps/desktop/src-tauri/app-icon.png
"""
import struct
import sys
import zlib
from pathlib import Path

SIZE = 1024
BG = (14, 18, 25, 255)
TILE = (18, 23, 32, 255)
TEAL = (79, 209, 197, 255)
BLUE = (122, 162, 247, 255)


def rounded(x, y, radius, inset):
    """True when (x, y) is inside the rounded square of that radius, inset from the canvas edge."""
    left, top = inset, inset
    right, bottom = SIZE - inset, SIZE - inset
    if not (left <= x <= right and top <= y <= bottom):
        return False
    for corner_x, corner_y in ((left + radius, top + radius), (right - radius, top + radius),
                               (left + radius, bottom - radius), (right - radius, bottom - radius)):
        if abs(x - corner_x) < radius and abs(y - corner_y) < radius:
            return (x - corner_x) ** 2 + (y - corner_y) ** 2 <= radius ** 2
    return True


def pixel(x, y):
    if not rounded(x, y, 190, 40):
        return (0, 0, 0, 0)
    dx, dy = abs(x - SIZE // 2), abs(y - SIZE // 2)
    distance = dx + dy
    if 300 <= distance <= 356:
        return TEAL
    if distance <= 104:
        return BLUE
    if 150 <= distance <= 190:
        return (79, 209, 197, 120)
    return TILE if distance < 470 else BG


def png(path):
    rows = bytearray()
    for y in range(SIZE):
        rows.append(0)  # filter: none
        for x in range(SIZE):
            rows.extend(pixel(x, y))

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    return path


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "apps/desktop/src-tauri/app-icon.png"
    print(png(target))
