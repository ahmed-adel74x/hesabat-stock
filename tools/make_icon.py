"""بيرسم أيقونة البرنامج (صندوق أبيض على مربع أزرق) من غير أي مكتبات، وبيكتب icon.png و icon.ico.
التشغيل:  python3 tools/make_icon.py"""
import math
import os
import struct
import zlib

SIZES = [16, 32, 48, 64, 128, 256]


def _box(u, v, cx, cy, hw, hh, r):
    dx, dy = abs(u - cx) - (hw - r), abs(v - cy) - (hh - r)
    return math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0) - r


def _sample(u, v):
    """لون النقطة (u,v في 0..1) أو None لو برا المربع."""
    if _box(u, v, .5, .5, .47, .47, .20) > 0:
        return None
    t = v
    c = (int(59 + (29 - 59) * t), int(130 + (78 - 130) * t), int(246 + (216 - 246) * t))   # تدرج أزرق
    if _box(u, v, .5, .36, .30, .065, .03) <= 0 or _box(u, v, .5, .605, .25, .165, .03) <= 0:
        c = (255, 255, 255)                                                                  # غطا وجسم الصندوق
        if _box(u, v, .5, .43, .045, .165, 0) <= 0:                                          # شريط اللاصق
            c = (219, 234, 254)
    return c


def render(n, ss=4):
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            r = g = b = cnt = 0
            for sy in range(ss):
                for sx in range(ss):
                    c = _sample((x + (sx + .5) / ss) / n, (y + (sy + .5) / ss) / n)
                    if c:
                        r, g, b, cnt = r + c[0], g + c[1], b + c[2], cnt + 1
            if cnt:
                row += bytes((r // cnt, g // cnt, b // cnt, round(255 * cnt / (ss * ss))))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    return rows


def png(n):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(render(n))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images):
    head = struct.pack("<HHH", 0, 1, len(images))
    offset, entries, blobs = 6 + 16 * len(images), b"", b""
    for n, data in images:
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hesabat", "assets")
    os.makedirs(out, exist_ok=True)
    images = [(n, png(n)) for n in SIZES]
    with open(os.path.join(out, "icon.png"), "wb") as f:
        f.write(images[-1][1])
    with open(os.path.join(out, "icon.ico"), "wb") as f:
        f.write(ico(images))
    print("تم:", out)
