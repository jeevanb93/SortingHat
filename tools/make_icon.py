"""
Generate a placeholder application icon (assets/sortinghat.ico) using only the
standard library — no Pillow, no ImageMagick.

It draws a neutral wizard-hat silhouette on an indigo disc and writes it as a
PNG-in-ICO (the modern icon format Windows Vista+ accepts). Replace the output
with a properly-licensed icon whenever you have one; this only exists so the
build has a real .ico to embed today.

    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 256


# ── tiny geometry helpers ─────────────────────────────────────────────────────

def _in_circle(x, y, cx, cy, r):
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _in_ellipse(x, y, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def _in_triangle(px, py, a, b, c):
    def sign(p, q, r):
        return (px - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (py - r[1])
    d1, d2, d3 = sign(px, a, b), sign(px, b, c), sign(px, c, a)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def _draw() -> bytearray:
    """Return SIZE*SIZE RGBA bytes for the hat design."""
    indigo   = (43, 45, 92, 255)
    charcoal = (35, 35, 48, 255)
    brim     = (26, 26, 34, 255)
    gold     = (184, 134, 11, 255)
    clear    = (0, 0, 0, 0)

    apex = (140, 38)
    base_l, base_r = (86, 182), (172, 182)

    px = bytearray(SIZE * SIZE * 4)
    for y in range(SIZE):
        for x in range(SIZE):
            colour = clear
            if _in_circle(x, y, 128, 128, 124):
                colour = indigo
            if _in_ellipse(x, y, 128, 182, 106, 24):
                colour = brim
            if _in_triangle(x, y, apex, base_l, base_r):
                colour = charcoal
            if _in_ellipse(x, y, 128, 166, 42, 11) and _in_triangle(x, y, apex, base_l, base_r):
                colour = gold  # hat band
            i = (y * SIZE + x) * 4
            px[i:i + 4] = bytes(colour)
    return px


# ── PNG / ICO writers ─────────────────────────────────────────────────────────

def _png(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # no per-row filter
        raw += rgba[y * width * 4:(y + 1) * width * 4]

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _ico(png: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)                    # reserved, type=icon, one image
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32,      # 0/0 width/height => 256
                        len(png), 6 + 16)                    # size, offset past dir
    return header + entry + png


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "assets" / "sortinghat.ico"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(_ico(_png(SIZE, SIZE, bytes(_draw()))))
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
