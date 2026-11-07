#!/usr/bin/env python3
"""Builds the self-hosted sprite for the pinned Voyager style.

    python3 -I build-sprite.py            # writes out/sprite/voyager{,@2x}.{json,png}

The Voyager style uses one icon, circle-11 (city dots at zooms 4-8). CARTO's style
repository ships no sprite, so this draws the same dot ourselves: a dark disc with a
thin white halo on a 17 px cell (34 px at 2x), the Maki circle-11 shape (CC0).
"""
import json
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "sprite")


def png_gray_alpha(width, height, pixels):
    """pixels: rows of (gray, alpha) tuples -> PNG bytes (colour type 4, 8 bit)."""
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 4, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def circle(scale):
    size = 17 * scale
    centre = size / 2
    disc, halo = 4.55 * scale, 5.6 * scale  # radii in px
    samples = 8
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            dark = ring = 0
            for sy in range(samples):
                for sx in range(samples):
                    d = math.hypot(x + (sx + 0.5) / samples - centre, y + (sy + 0.5) / samples - centre)
                    if d <= disc:
                        dark += 1
                    elif d <= halo:
                        ring += 1
            n = samples * samples
            dark_a, ring_a = dark / n, 0.25 * ring / n
            alpha = dark_a + ring_a
            if alpha <= 0:
                row.append((0, 0))
                continue
            gray = (68 * dark_a + 255 * ring_a) / alpha
            row.append((round(gray), round(min(1.0, alpha) * 255)))
        rows.append(row)
    return size, rows


os.makedirs(OUT, exist_ok=True)
for scale, suffix in ((1, ""), (2, "@2x")):
    size, rows = circle(scale)
    with open(os.path.join(OUT, f"voyager{suffix}.png"), "wb") as handle:
        handle.write(png_gray_alpha(size, size, rows))
    with open(os.path.join(OUT, f"voyager{suffix}.json"), "w") as handle:
        json.dump({"circle-11": {"height": size, "pixelRatio": scale, "width": size, "x": 0, "y": 0}}, handle, separators=(",", ":"))
print("wrote", sorted(os.listdir(OUT)))
