#!/usr/bin/env python3
"""Generate Chrome Web Store listing assets. Stdlib plus macOS sips.

    python3 tools/listing.py                 every theme in dist/
    python3 tools/listing.py gruvbox-dark    just these

Writes assets/<slug>/ with icon-128.png, screenshot-1280x800.png (unless
--no-shots) and promo-440x280.png, the small tile the dashboard requires before it
will let an item publish. All three are exactly the dimensions the store demands.

The icon is drawn from the theme's own colors as a miniature browser window. The
screenshot is a real capture of Chrome wearing the theme, taken by preview.py at
1280x800 logical so the retina image downscales to the required size without
cropping or distortion.
"""

import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).parent.parent
ICON = 128
SHOT_W, SHOT_H = 1280, 800
# The dashboard refuses to publish without this one ("Small tile image is
# missing"). 440x280 is 1.571:1 against the screenshot's 1.6:1, so the shot is
# cropped to the tile's aspect before scaling rather than squashed into it.
TILE_W, TILE_H = 440, 280
# Optional, and only needed to be eligible for featuring. 2.5:1 against the
# screenshot's 1.6:1, so it is cropped from the top rather than centred: a centred
# crop of that ratio would cut the tab strip off, which is the point of the shot.
MARQUEE_W, MARQUEE_H = 1400, 560

spec = importlib.util.spec_from_file_location("build", HERE / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def write_png(path, pixels):
    """pixels: list of rows of (r, g, b)."""
    h, w = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + b"".join(bytes(p) for p in row) for row in pixels)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b""))


def icon(style):
    """A miniature browser window in the theme's colors.

    Light Gruvbox surfaces sit within ~20/255 of each other, so bands of them
    alone read as a blank square at this size. The structure comes from the
    theme's `border` between bands and from `text.muted` bars standing in for
    page content, which is what makes the icon legible.
    """
    title = build.rgb(style["title_bar.background"])
    panel = build.rgb(style["panel.background"])
    editor = build.rgb(style["editor.background"])
    border = build.rgb(style["border"])
    muted = build.rgb(style["text.muted"])

    TAB_X0, TAB_X1 = 8, 64
    px = [[editor] * ICON for _ in range(ICON)]

    def fill(x0, x1, y0, y1, color):
        for y in range(max(0, y0), min(ICON, y1)):
            for x in range(max(0, x0), min(ICON, x1)):
                px[y][x] = color

    fill(0, ICON, 0, 42, title)                      # title bar
    fill(TAB_X0, TAB_X1, 8, 44, panel)               # active tab, running into...
    fill(0, ICON, 44, 72, panel)                     # ...the toolbar
    fill(TAB_X0, TAB_X0 + 1, 8, 42, border)          # tab edges
    fill(TAB_X1 - 1, TAB_X1, 8, 42, border)
    for x in range(ICON):                            # tab strip underline, but not
        if not TAB_X0 <= x < TAB_X1:                 # under the active tab
            px[42][x] = px[43][x] = border
    fill(14, 114, 50, 66, editor)                    # omnibox
    for x in range(14, 114):
        px[50][x] = px[65][x] = border
    for y in range(50, 66):
        px[y][14] = px[y][113] = border
    fill(0, ICON, 72, 74, border)                    # toolbar / page divider
    for i, width in enumerate((78, 92, 60)):         # page content
        fill(16, 16 + width, 88 + i * 16, 94 + i * 16, muted)
    for i in range(ICON):                            # outer border
        px[0][i] = px[ICON - 1][i] = px[i][0] = px[i][ICON - 1] = border
    return px


def screenshot(slug, out):
    """Capture Chrome wearing the theme, then downscale to exactly 1280x800."""
    raw = out.parent / "_raw.png"
    # START_URL avoids an "about:blank" tab in the shot. The new tab page is opened
    # twice because Chrome puts an "Installed theme / Undo" infobar on the tab
    # around the install, and a later tab comes up without it.
    # Chrome ignores chrome:// URLs given on the command line, so the extra tab is
    # created over CDP instead. Two of them: Chrome puts an "Installed theme / Undo"
    # infobar on the tab around the install, and a later tab comes up without it.
    env = dict(os.environ, WIN_W=str(SHOT_W), WIN_H=str(SHOT_H),
               START_URL="chrome://new-tab-page")
    subprocess.run(["pkill", "-f", "chrome-zed-preview-profile"], capture_output=True)
    subprocess.run([sys.executable, str(HERE / "tools/preview.py"), str(HERE / "dist" / slug),
                    str(raw), "chrome://settings", "chrome://new-tab-page"],
                   check=True, env=env,
                   capture_output=True)
    subprocess.run(["sips", "--resampleHeightWidth", str(SHOT_H), str(SHOT_W),
                    str(raw), "--out", str(out)], check=True, capture_output=True)
    raw.unlink()


def listing(name, style, appearance):
    """Store listing copy, with the claims that vary by theme decided per theme.

    Two of them are not true across the board: the address bar can only be aimed
    at the editor background on palettes where the omnibox seed applies, and on
    dark themes the unfocused compensation clips at black, so the wording is
    softened rather than overstated.
    """
    panel = build.rgb(style["panel.background"])
    editor = build.rgb(style["editor.background"])
    seeded = build.omnibox_seed(editor, panel) != panel
    over = (1 - build.INACTIVE_ALPHA) * 255
    clips = any((c - over) / build.INACTIVE_ALPHA < 0
                for c in build.rgb(style["title_bar.background"]))

    bullets = [
        "Title bar and tab strip take Zed's title bar colour, with a soft gradient\n"
        "  along the window's top edge",
        "Toolbar and the active tab take Zed's sidebar colour",
        "Inactive tabs carry no fill of their own \u2014 they disappear into the title\n"
        "  bar, the way Zed's own tab bar reads, in both horizontal and vertical tab\n"
        "  layouts",
        "The new tab page uses Zed's blank-window background",
    ]
    if seeded:
        bullets.append("The address bar is aimed at Zed's editor background")
    bullets.append(
        "The title bar holds its tone when the window loses focus, rather than\n"
        "  washing out to a pale grey" if clips else
        "The title bar keeps its colour when the window loses focus, instead of\n"
        "  washing out to grey the way most themes do")

    summary = (f"Chrome in Zed's {name}: title bar, tabs, toolbar and new tab page "
               "taken from the editor's own theme file.")
    assert len(summary) <= 132, (len(summary), summary)
    body = "\n".join(f"\u2022 {b}" for b in bullets)
    return f"""# {name} (Zed)

## Title ({len(name) + 6}/75)

{name} (Zed)

## Summary ({len(summary)}/132)

{summary}

## Description

{name}, lifted straight from the Zed editor's theme file, so Chrome and Zed can
sit side by side without a colour clash.

What's matched to the editor:

{body}

Generated from Zed's published theme JSON rather than eyeballed, and checked
against real Chrome renders pixel by pixel.

Source and build script: https://github.com/dangh/chrome-zed-themes

## Assets

- Store icon: icon-128.png
- Screenshot: screenshot-1280x800.png
- Small promo tile: promo-440x280.png

## Category

Themes \u00b7 {appearance}
"""


def tile(shot, out):
    """440x280 promo tile from the screenshot, cropped to aspect then scaled."""
    crop_w = round(SHOT_H * TILE_W / TILE_H)
    subprocess.run(["sips", "-c", str(SHOT_H), str(crop_w), str(shot), "--out", str(out)],
                   check=True, capture_output=True)
    subprocess.run(["sips", "--resampleHeightWidth", str(TILE_H), str(TILE_W), str(out)],
                   check=True, capture_output=True)


def read_png(path):
    """Minimal decoder for the screenshots this script produced."""
    data = path.read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", data[pos + 8:pos + 18])
        elif tag == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += n + 12
    bpp = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev = [], bytearray(stride)
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
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * bpp:x * bpp + 3]) for x in range(w)])
        prev = line
    return rows


def marquee(shot, out):
    """1400x560 marquee tile: top-anchored crop of the screenshot, then scaled."""
    keep = round(SHOT_W * MARQUEE_H / MARQUEE_W)
    write_png(out, read_png(shot)[:keep])
    subprocess.run(["sips", "--resampleHeightWidth", str(MARQUEE_H), str(MARQUEE_W),
                    str(out)], check=True, capture_output=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    shots = "--no-shots" not in sys.argv[1:]

    styles = {}
    for path in sorted((HERE / ".zed-themes").glob("*.json")):
        for t in json.loads(path.read_text())["themes"]:
            slug = re.sub(r"[^a-z0-9]+", "-", t["name"].lower()).strip("-")
            styles[slug] = (t["name"], t["style"], t["appearance"])

    slugs = args or sorted(p.name for p in (HERE / "dist").iterdir() if p.is_dir())
    for slug in slugs:
        if slug not in styles:
            sys.exit(f"no Zed theme matches {slug!r}; run build.py --fetch first")
        out = HERE / "assets" / slug
        out.mkdir(parents=True, exist_ok=True)
        name, style, appearance = styles[slug]
        write_png(out / "icon-128.png", icon(style))
        (out / "listing.md").write_text(listing(name, style, appearance))
        print(f"{slug}: icon-128.png + listing.md", end="", flush=True)
        shot = out / "screenshot-1280x800.png"
        if shots:
            screenshot(slug, shot)
            print(" + screenshot-1280x800.png", end="")
        if shot.is_file():
            tile(shot, out / "promo-440x280.png")
            marquee(shot, out / "marquee-1400x560.png")
            print(" + promo-440x280.png + marquee-1400x560.png", end="")
        print()


if __name__ == "__main__":
    main()
