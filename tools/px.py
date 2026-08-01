#!/usr/bin/env python3
"""Sample pixels from a PNG: px.py file.png x,y[:label] ..."""
import struct
import sys
import zlib


def decode(path):
    d = open(path, "rb").read()
    pos, idat, w = 8, b"", None
    while pos < len(d):
        n = struct.unpack(">I", d[pos:pos + 4])[0]
        tag = d[pos + 4:pos + 8]
        body = d[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype in (2, 6), (depth, ctype)
            bpp = 3 if ctype == 2 else 4
        elif tag == b"IDAT":
            idat += body
        pos += n + 12
    raw = zlib.decompress(idat)
    stride = w * bpp
    out, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out.append(bytes(line))
        prev = line
    return out, w, h, bpp


rows, w, h, bpp = decode(sys.argv[1])
for spec in sys.argv[2:]:
    coord, _, label = spec.partition(":")
    x, y = (int(v) for v in coord.split(","))
    p = rows[y][x * bpp:x * bpp + 3]
    print(f"{label or coord:<16} #{p[0]:02x}{p[1]:02x}{p[2]:02x}  at {x},{y}")
