#!/usr/bin/env python3
"""Генерирует производные иконки бренда из уже закоммиченных PNG (без Pillow/ImageMagick).

Запускать вручную после смены логотипа (res/icon.png, res/32x32.png … уже заменены):
    python3 branding/gen_icons.py
Результат коммитится. Что делает:
  res/scalable.svg          — векторная иконка Linux (hicolor/scalable), знак «F» FusionPOS
  res/mac-tray-dark-x2.png  — шаблон (силуэт) для трея macOS
  res/tray-icon.ico         — иконка трея Windows/Linux (32x32, PNG внутри ICO)
  flutter/macos/Runner/AppIcon.icns — иконка приложения macOS
  flutter/android/.../mipmap-*/ic_stat_logo.png — значок уведомлений Android (белый силуэт «F»)
Геометрия знака «F» и цвет заданы ниже (координаты в сетке 512x512, сняты с res/icon.png).
"""
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG = "#009CF3"
RADIUS = 44
# Знак «F»: прямоугольники (x0, y0, x1, y1) в сетке 512
F_RECTS = [(156, 109, 356, 171), (156, 171, 218, 213), (156, 247, 287, 310), (156, 310, 218, 404)]


def path(*p):
    return os.path.join(ROOT, *p)


def png_bytes(w, h, rgba_rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rgba_rows)

    def chunk(t, c):
        return struct.pack(">I", len(c)) + t + c + struct.pack(">I", zlib.crc32(t + c) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def gen_svg():
    d = "".join(f"M{x0} {y0}H{x1}V{y1}H{x0}Z" for x0, y0, x1, y1 in F_RECTS)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">\n'
           f'  <rect width="512" height="512" rx="{RADIUS}" fill="{BG}"/>\n'
           f'  <path fill="#fff" d="{d}"/>\n</svg>\n')
    with open(path("res", "scalable.svg"), "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)


def gen_stat_icons(ss=4):
    """Android: значок в строке уведомлений — белое «F» на прозрачном фоне."""
    x0 = min(r[0] for r in F_RECTS); y0 = min(r[1] for r in F_RECTS)
    x1 = max(r[2] for r in F_RECTS); y1 = max(r[3] for r in F_RECTS)
    side = (y1 - y0) / 0.84  # поле ~8% с каждой стороны
    ox = (x0 + x1) / 2 - side / 2
    oy = (y0 + y1) / 2 - side / 2
    for dens, size in (("mdpi", 24), ("hdpi", 36), ("xhdpi", 48), ("xxhdpi", 72), ("xxxhdpi", 96)):
        k = side / size
        rows = []
        for y in range(size):
            row = bytearray()
            for x in range(size):
                cov = 0
                for sy in range(ss):
                    for sx in range(ss):
                        px = ox + (x + (sx + 0.5) / ss) * k
                        py = oy + (y + (sy + 0.5) / ss) * k
                        if any(a <= px < c and b <= py < d for a, b, c, d in F_RECTS):
                            cov += 1
                row += bytes((255, 255, 255, round(255 * cov / (ss * ss))))
            rows.append(row)
        with open(path("flutter", "android", "app", "src", "main", "res", f"mipmap-{dens}", "ic_stat_logo.png"), "wb") as f:
            f.write(png_bytes(size, size, rows))


def gen_tray_template(size=60, margin=6, ss=4):
    """Силуэт: чёрный скруглённый квадрат с прозрачным «F» (macOS template image)."""
    inner = size - 2 * margin
    k = inner / 512.0
    r = RADIUS * k * 1.3
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            cov = 0
            for sy in range(ss):
                for sx in range(ss):
                    px = (x + (sx + 0.5) / ss - margin) / k
                    py = (y + (sy + 0.5) / ss - margin) / k
                    if not (0 <= px < 512 and 0 <= py < 512):
                        continue
                    # скругление углов
                    rr = r / k
                    cx = min(max(px, rr), 512 - rr)
                    cy = min(max(py, rr), 512 - rr)
                    if (px - cx) ** 2 + (py - cy) ** 2 > rr * rr:
                        continue
                    if any(x0 <= px < x1 and y0 <= py < y1 for x0, y0, x1, y1 in F_RECTS):
                        continue
                    cov += 1
            row += bytes((0, 0, 0, round(255 * cov / (ss * ss))))
        rows.append(row)
    with open(path("res", "mac-tray-dark-x2.png"), "wb") as f:
        f.write(png_bytes(size, size, rows))


def read(p):
    with open(path(*p.split("/")), "rb") as f:
        return f.read()


def gen_tray_ico():
    png = read("res/32x32.png")
    hdr = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png), 6 + 16)
    with open(path("res", "tray-icon.ico"), "wb") as f:
        f.write(hdr + png)


def gen_icns():
    parts = [(b"ic11", "res/32x32.png"), (b"ic12", "res/64x64.png"), (b"ic07", "res/128x128.png"),
             (b"ic13", "res/128x128@2x.png"), (b"ic08", "res/128x128@2x.png"),
             (b"ic14", "res/mac-icon.png"), (b"ic09", "res/mac-icon.png")]
    body = b"".join(t + struct.pack(">I", 8 + len(read(p))) + read(p) for t, p in parts)
    with open(path("flutter", "macos", "Runner", "AppIcon.icns"), "wb") as f:
        f.write(b"icns" + struct.pack(">I", 8 + len(body)) + body)


if __name__ == "__main__":
    gen_svg()
    gen_tray_template()
    gen_tray_ico()
    gen_icns()
    gen_stat_icons()
    print("ok")
