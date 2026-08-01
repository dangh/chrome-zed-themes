#!/usr/bin/env python3
"""Generate Chrome themes from Zed theme files. Stdlib only.

    python3 build.py                 build every theme in .zed-themes/,
                                     fetching Zed's bundled themes first if empty
    python3 build.py --fetch         re-download those themes, then build
    python3 build.py <path> ...      build from given .json files or directories,
                                     e.g. ~/.config/zed/themes for your own
"""

import json
import re
import shutil
import struct
import sys
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / ".zed-themes"
ZED_THEMES_API = "https://api.github.com/repos/zed-industries/zed/contents/assets/themes"
# Taller than any window, so neither the frame nor the tab image ever tiles.
# 120 was enough for a horizontal tab strip, but a vertical tab strip runs the
# full window height and repeated the gradient as bands down it.
FRAME_H = 2000
# Length of the gradient in the frame image. The frame samples row = window y + 16,
# so the gradient is visible over the window's top RAMP_H - 16 pixels. Keep it
# short: horizontal tabs sample rows 22..50 and are painted flat, so any ramp
# still running at row 22 shows up as a mismatch at the top edge of a tab. At 28
# that residual is about 4/255.
RAMP_H = 28
TOP_SHADE = 0.90  # darken the very top of the title bar for a little depth
# Chrome paints the inactive frame image at ~71% opacity over white, washing the
# title bar out when the window loses focus. Measured on Chrome 151 by rendering
# a gray ramp and fitting it: rendered = 0.708 * source + 74, in dark and light.
# Pre-darkening the inactive image by the inverse cancels it out.
INACTIVE_ALPHA = 0.708
# Chrome does NOT apply that wash to theme_tab_background_inactive -- it draws it
# verbatim (verified: handing it the pre-darkened frame image rendered #c5b285
# against a #d5c8a6 frame). So the inactive tab color has to be aimed at whatever
# the washed frame lands on, which is the title bar color again, minus the
# residual of the rounding on both sides of the wash.
INACTIVE_TAB_TRIM = (1, 1, 2)
# Chrome derives the omnibox fill from the `toolbar` color, ignoring
# omnibox_background entirely. Per-channel fit of that derivation on Chrome 151,
# from two measured renders: rendered = a * seed + b. Only valid near the light
# targets it was fitted around; dark themes fall back (see omnibox_seed).
OMNIBOX_FIT = ((1.571, -118.8), (1.0, 30.0), (0.93, 77.5))
# The fit carries chroma, so it only makes sense when the target has chroma to
# carry. Aiming it at a near-neutral surface -- One Light, Ayu Light -- produces a
# warm seed, which would tint the omnibox and, since the tab divider renders the
# seed directly, put a tan line on a grey frame.
MIN_TARGET_CHROMA = 16


def rgb(hexa):
    """'#rrggbbaa' -> (r, g, b)"""
    return tuple(int(hexa[i:i + 2], 16) for i in (1, 3, 5))


def shade(color, factor):
    return tuple(min(255, round(v * factor)) for v in color)


def gradient(top, bottom, h):
    return [tuple(round(a + (b - a) * i / (h - 1)) for a, b in zip(top, bottom))
            for i in range(h)]


def frame_rows(title):
    """Ramp up to the title bar color, then hold it.

    The ramp deliberately stops at the title bar color rather than continuing
    into the toolbar: blending the two flattens the tab strip and toolbar into
    one wash, losing the step that separates them.
    """
    return gradient(shade(title, TOP_SHADE), title, RAMP_H) + [title] * (FRAME_H - RAMP_H)


def undim(color):
    """Invert Chrome's inactive-frame wash so the result renders as `color`.

    Dark themes clip at black: the wash lifts everything to at least ~#4a4a4a,
    so their unfocused title bar stays slightly greyer than the focused one.
    """
    over = (1 - INACTIVE_ALPHA) * 255
    return tuple(max(0, min(255, round((c - over) / INACTIVE_ALPHA))) for c in color)


def redim(color):
    """What the unfocused frame actually renders as.

    Round-trips `color` through undim and Chrome's wash, so it comes back to
    `color` for light themes and to a neutral grey for dark ones, where undim
    clipped at black. Then trims the rounding residual so an inactive tab drawn
    in this color disappears into the unfocused frame.
    """
    over = (1 - INACTIVE_ALPHA) * 255
    return tuple(max(0, min(255, round(INACTIVE_ALPHA * c + over) - t))
                 for c, t in zip(undim(color), INACTIVE_TAB_TRIM))


def write_png(path, rows, w):
    """Rows of (r, g, b) or (r, g, b, a) tuples."""
    ctype = 6 if len(rows[0]) == 4 else 2
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    raw = b"".join(b"\x00" + bytes(c) * w for c in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, len(rows), 8, ctype, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b""))


def omnibox_seed(target, fallback):
    """Toolbar color that makes Chrome's derived omnibox fill land on `target`.

    The visible toolbar comes from theme_toolbar.png, so the `toolbar` color is
    free to act purely as the seed Chrome derives the omnibox from. Fitted on
    Chrome 151 from two measured renders; returns `fallback` when the solution
    leaves 0-255, which is what happens for dark themes -- their omnibox already
    lands close to the editor background without help.
    """
    if max(target) - min(target) < MIN_TARGET_CHROMA:
        return fallback
    seed = [(t - b) / a for t, (a, b) in zip(target, OMNIBOX_FIT)]
    if any(v < 0 or v > 255 for v in seed):
        return fallback
    return tuple(round(v) for v in seed)


def theme(name, style):
    title = rgb(style["title_bar.background"])
    panel = rgb(style["panel.background"])
    editor = rgb(style["editor.background"])
    # Zed's blank-window background, which is also its title bar / status bar tone
    window = rgb(style["background"])
    text = rgb(style["text"])
    muted = rgb(style["text.muted"])
    link = rgb(style.get("link_text.hover", style["text.accent"]))
    return {
        "manifest_version": 3,
        "version": "1.0.0",
        "name": f"{name} (Zed)",
        "description": f"{name} colors from the Zed editor.",
        "theme": {
            "images": {
                # the inactive image is pre-darkened to survive Chrome's wash
                "theme_frame": "images/frame.png",
                "theme_frame_inactive": "images/frame_inactive.png",
                "theme_frame_incognito": "images/frame.png",
                "theme_frame_incognito_inactive": "images/frame_inactive.png",
                "theme_toolbar": "images/toolbar.png",
                "theme_tab_background": "images/tab.png",
                "theme_tab_background_inactive": "images/tab_inactive.png",
                "theme_tab_background_incognito_inactive": "images/tab_inactive.png",  # same rows as the frame
            },
            "colors": {
                # title bar, gradienting down into the toolbar
                "frame": list(title),
                "frame_inactive": list(title),
                "frame_incognito": list(title),
                "frame_incognito_inactive": list(title),
                # A seed, not what you see: the visible toolbar and bookmark bar
                # are theme_toolbar.png (panel), while this color is what Chrome
                # derives the omnibox fill from -- aimed at Zed's editor surface.
                "toolbar": list(omnibox_seed(editor, panel)),
                "tab_text": list(text),
                "tab_background_text": list(muted),
                "toolbar_text": list(text),
                "bookmark_text": list(text),
                "toolbar_button_icon": list(muted),
                "button_background": list(panel),
                # omnibox_background is ignored by Chrome 151; omnibox_text works
                "omnibox_text": list(text),
                # a color only, no image: an ntp_background *image* makes Chrome
                # treat it as a custom background and force white text over it
                "ntp_background": list(window),
                "ntp_text": list(text),
                "ntp_link": list(link),
            },
            "tints": {"buttons": [-1.0, -1.0, -1.0]},
        },
    }, (title, panel)


def fetch(cache):
    """Mirror Zed's bundled theme JSON into `cache`."""
    cache.mkdir(exist_ok=True)
    with urllib.request.urlopen(ZED_THEMES_API, timeout=30) as r:
        families = [d for d in json.load(r) if d["type"] == "dir"]
    for fam in families:
        with urllib.request.urlopen(fam["url"], timeout=30) as r:
            entries = json.load(r)
        for e in entries:
            if e["name"].endswith(".json"):
                with urllib.request.urlopen(e["download_url"], timeout=30) as r:
                    (cache / f"{fam['name']}_{e['name']}").write_bytes(r.read())
                print(f"fetched {fam['name']}/{e['name']}")


def theme_files(sources):
    for src in sources:
        if src.is_dir():
            yield from sorted(src.glob("*.json"))
        elif src.is_file():
            yield src
        else:
            sys.exit(f"no such file or directory: {src}")


def slug(name):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def main():
    args = [a for a in sys.argv[1:] if a != "--fetch"]
    if "--fetch" in sys.argv[1:] or (not args and not any(CACHE.glob("*.json"))):
        fetch(CACHE)
    sources = [Path(a) for a in args] or [CACHE]

    dist = HERE / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    built = {}
    for path in theme_files(sources):
        for t in json.loads(path.read_text())["themes"]:
            name = t["name"]
            if slug(name) in built:
                print(f"skipping duplicate {name!r} from {path.name}"
                      f" (already built from {built[slug(name)]})")
                continue
            built[slug(name)] = path.name
            emit(dist / slug(name), name, t["style"])
    if not built:
        sys.exit(f"no themes found in {', '.join(str(s) for s in sources)}")
    print(f"\nbuilt {len(built)} themes into {dist}")


def emit(out, name, style):
    manifest, (title, panel) = theme(name, style)
    (out / "images").mkdir(parents=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    rows = frame_rows(title)
    write_png(out / "images" / "frame.png", rows, 16)
    write_png(out / "images" / "frame_inactive.png", [undim(r) for r in rows], 16)
    write_png(out / "images" / "toolbar.png", [panel] * 60, 16)
    # Inactive tabs are a flat title-bar color, so they disappear into the frame
    # in both tab layouts. It cannot carry the gradient: a vertical tab strip
    # restarts this image at row 0 for every pill, so any ramp in the top rows
    # paints a dark patch onto each one, while a horizontal strip reads rows
    # 22..50 of it. Flat is the only value that satisfies both.
    write_png(out / "images" / "tab.png", [title] * FRAME_H, 16)
    write_png(out / "images" / "tab_inactive.png", [redim(title)] * FRAME_H, 16)
    print(f"built {out.name:26} title #{'%02x%02x%02x' % title}  panel #{'%02x%02x%02x' % panel}")


if __name__ == "__main__":
    main()
