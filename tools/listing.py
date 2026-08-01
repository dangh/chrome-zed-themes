#!/usr/bin/env python3
"""Generate Chrome Web Store listing assets. Stdlib plus macOS sips.

    python3 tools/listing.py                 every theme in dist/
    python3 tools/listing.py gruvbox-dark    just these

Writes assets/<slug>/icon-128.png and, unless --no-shots is passed,
assets/<slug>/screenshot-1280x800.png. Both dimensions are what the store
requires exactly.

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
    subprocess.run(["pkill", "-f", "chrome-gruvbox-preview-profile"], capture_output=True)
    subprocess.run([sys.executable, str(HERE / "tools/preview.py"), str(HERE / "dist" / slug),
                    str(raw), "chrome://settings", "chrome://new-tab-page"],
                   check=True, env=env,
                   capture_output=True)
    subprocess.run(["sips", "--resampleHeightWidth", str(SHOT_H), str(SHOT_W),
                    str(raw), "--out", str(out)], check=True, capture_output=True)
    raw.unlink()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    shots = "--no-shots" not in sys.argv[1:]

    styles = {}
    for path in sorted((HERE / ".zed-themes").glob("*.json")):
        for t in json.loads(path.read_text())["themes"]:
            styles[re.sub(r"[^a-z0-9]+", "-", t["name"].lower()).strip("-")] = t["style"]

    slugs = args or sorted(p.name for p in (HERE / "dist").iterdir() if p.is_dir())
    for slug in slugs:
        if slug not in styles:
            sys.exit(f"no Zed theme matches {slug!r}; run build.py --fetch first")
        out = HERE / "assets" / slug
        out.mkdir(parents=True, exist_ok=True)
        write_png(out / "icon-128.png", icon(styles[slug]))
        print(f"{slug}: icon-128.png", end="", flush=True)
        if shots:
            screenshot(slug, out / "screenshot-1280x800.png")
            print(" + screenshot-1280x800.png", end="")
        print()


if __name__ == "__main__":
    main()
