"""Generate extension/icon.png (128x128 marketplace icon) — stdlib only.

A flat 'no vibes' prohibition ring with a slash, on a dark rounded square.
Usage: python tools/gen_icon.py
"""

import math
import os
import struct
import zlib

SIZE = 128
BG = (32, 36, 44, 255)        # dark slate
RING = (245, 166, 35, 255)    # amber
TRANSPARENT = (0, 0, 0, 0)

CX = CY = SIZE / 2
R_OUT, R_IN = 46.0, 36.0
SLASH_HALF_W = 5.0
CORNER = 22.0  # rounded-square corner radius


def rounded_square_alpha(x, y):
    """1 inside the rounded square, 0 outside (hard edge, tiny AA)."""
    dx = max(CORNER - x, x - (SIZE - 1 - CORNER), 0)
    dy = max(CORNER - y, y - (SIZE - 1 - CORNER), 0)
    d = math.hypot(dx, dy)
    return max(0.0, min(1.0, CORNER - d + 1))


def ring_alpha(x, y):
    d = math.hypot(x - CX, y - CY)
    if d > R_OUT + 1 or d < R_IN - 1:
        return 0.0
    outer = max(0.0, min(1.0, R_OUT - d + 0.5))
    inner = max(0.0, min(1.0, d - R_IN + 0.5))
    return min(outer, inner)


def slash_alpha(x, y):
    # diagonal band (top-left to bottom-right) clipped to the ring's outer circle
    if math.hypot(x - CX, y - CY) > R_OUT - 0.5:
        return 0.0
    dist = abs((x - CX) - (y - CY)) / math.sqrt(2)
    return max(0.0, min(1.0, SLASH_HALF_W - dist + 0.5))


def blend(base, top, a):
    return tuple(int(base[i] * (1 - a) + top[i] * a) for i in range(4))


rows = []
for y in range(SIZE):
    row = bytearray([0])  # filter byte
    for x in range(SIZE):
        sq = rounded_square_alpha(x, y)
        px = blend(TRANSPARENT, BG, sq)
        fg = max(ring_alpha(x, y), slash_alpha(x, y))
        if fg > 0:
            px = blend(px, RING, fg * sq)
        row.extend(px)
    rows.append(bytes(row))


def chunk(tag, data):
    c = tag + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))


out = os.path.join(os.path.dirname(__file__), "..", "extension", "icon.png")
with open(out, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n")
    f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)))
    f.write(chunk(b"IDAT", zlib.compress(b"".join(rows), 9)))
    f.write(chunk(b"IEND", b""))
print(f"wrote {os.path.abspath(out)}")
