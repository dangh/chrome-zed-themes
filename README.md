# chrome-gruvbox-theme

Chrome themes generated from Zed theme files, so the colors stay in sync with the
editor. Stdlib only, no dependencies.

## Install

1. `python3 build.py` — fetches Zed's bundled themes from
   [zed/assets/themes](https://github.com/zed-industries/zed/tree/main/assets/themes)
   into `.zed-themes/` on first run and builds every one of them: the Ayu,
   Gruvbox and One families, 11 themes. `--fetch` re-downloads.
2. Open `chrome://extensions`, enable **Developer mode**
3. **Load unpacked** → pick a folder under `dist/`

Chrome allows one theme at a time; loading another replaces it.

To build your own themes instead, pass files or directories:
`python3 build.py ~/.config/zed/themes`. Slugs come from the theme name, so a
theme named "Gruvbox Light Soft Custom" lands in `dist/gruvbox-light-soft-custom`
and will not collide with the upstream one.

## Mapping

| Chrome | Zed |
|---|---|
| title bar | `title_bar.background`, gradienting from 10% darker over the window's top 12px |
| unfocused title bar | same as focused, via a pre-darkened inactive frame image |
| unfocused inactive tabs | `title_bar.background` round-tripped through that wash, so they still vanish |
| toolbar + active tab | `panel.background` (the sidebar), via `theme_toolbar.png` |
| omnibox | `editor.background`, via the `toolbar` color used as a seed, on palettes with enough chroma |
| inactive tabs | flat `title_bar.background`, so they vanish into the frame in both horizontal and vertical layouts |
| new tab page | `background` (Zed's blank window), as a color with no image |
| text / muted text / links | `text` / `text.muted` / `link_text.hover` |

Tuning knobs at the top of `build.py`: `RAMP_H` (gradient length, and see the
vertical-tabs note below before raising it), `TOP_SHADE` (how dark the top edge
starts), `MIN_TARGET_CHROMA` (below which the omnibox seed is skipped).

The omnibox seed is fitted to Gruvbox's warm palette, and the fit carries chroma.
Aimed at a near-neutral surface — One Light, Ayu Light — it produces a warm seed,
which would tint the omnibox and, since the tab divider renders the seed directly,
draw a tan line on a grey frame. `MIN_TARGET_CHROMA` skips the seed there, so
those themes get the honest `panel.background` and Chrome's own omnibox fill.

`VERTICAL=1 python3 tools/preview.py …` enables vertical tabs in the preview
profile via the `vertical_tabs.enabled` pref plus `--enable-features=VerticalTabs`.

## Verifying

`python3 tools/preview.py dist/<variant> shot.png` installs a theme into a
throwaway Chrome profile over the DevTools pipe, opens tabs, and screenshots the
window. `python3 tools/px.py shot.png 950,44 1750,88` samples exact pixels.

It captures by CGWindowID (`screencapture -l`), not by screen rect, and activates
its own window with `Page.bringToFront` rather than AppleScript. Both matter: a
rect capture silently photographs whatever overlaps those coordinates — it caught
a terminal window and, worse, `tell application "Google Chrome"` addresses the app
rather than this instance, so it once raised and captured the user's real browsing
session. Capturing by window id also bypasses the display color transform, so
samples come back in source space for neutral colors; chromatic ones still shift a
few units, since the generated PNGs carry no color profile.

Findings from measuring real renders (Chrome 151), which shape the mapping above:

- **`background_tab` is ignored.** Inactive tabs rendered byte-identical to the
  toolbar. Only the `theme_tab_background` *image* has any effect, and dropping
  that image does not give transparency either — it falls back to the toolbar
  color. A fully transparent RGBA image does let the frame show through, but
  Chrome samples the frame ~11 rows lower behind a tab, so a gradient frame left
  the tabs looking like a lighter patch. Painting `tab.png` with the frame's own
  rows makes each tab pixel identical to the frame beside it.
- **Vertical tabs read the tab image completely differently.** A horizontal strip
  aligns it to the window (row = y + 16, so tabs sample rows 22..50). A vertical
  strip restarts it at row 0 for *every* pill — measured by sampling down two
  pills, which both begin at the image's row 0 and ramp identically. So any
  gradient in the top rows gets painted onto each pill as a dark patch, and no
  single image can both carry the gradient and leave vertical pills flat.
  `tab.png` is therefore a flat title-bar color, and `RAMP_H` is kept short (28,
  a 12px visible gradient) so the frame has already reached that flat color by
  row 22 where horizontal tabs start. Measured residual: 1/255. Raising `RAMP_H`
  reintroduces a light edge along the top of horizontal tabs.
- **Both images must be taller than the window.** They were 120 rows, which a
  horizontal strip never exhausts, but a vertical strip runs the full window
  height and tiled them, repeating the gradient as bands. Both are now 2000 rows
  (~540 bytes each, since near-identical rows compress).
- **An `ntp_background` *image* forces white text.** Chrome treats any new tab
  background image as a custom wallpaper, whitens the Google wordmark and links,
  and adds a scrim under the toolbar. Setting only the `ntp_background` color
  keeps Chrome's dark-on-light text, so no NTP image is shipped.
- **`omnibox_background` is ignored, but the omnibox is still reachable.** Setting
  it to pure red left the field unchanged: Chrome derives the fill from the
  `toolbar` color. That derivation is tone-based rather than a fixed blend - it
  holds lightness roughly constant while carrying the seed's chroma through - so a
  low-chroma toolbar tan yields a near-white field. Because the visible toolbar
  comes from `theme_toolbar.png`, the `toolbar` *color* is free to serve purely as
  a seed: `omnibox_seed()` inverts the fit in `OMNIBOX_FIT` to aim the field at
  `editor.background`. Measured results - light-soft `#f1e5c1` against a `#f2e5bc`
  target, light-hard within 11/255, light within 18/255 on blue. The fit is local
  to the light targets; dark themes fall back to the panel color, which already
  renders `#242427` against a `#282828` target.
- **Chrome washes out the inactive frame.** It paints the inactive frame image at
  ~71% opacity over white. Fitting a rendered gray ramp gave
  `rendered = 0.708 * source + 74`, in both appearances, so `frame_inactive.png`
  is pre-darkened by the inverse to cancel it. Light themes land within 2/255 of
  focused; dark themes clip at black (the wash floors around `#4a4a4a`), so their
  unfocused title bar stays slightly greyer and less warm than focused.
- **That wash is not applied to `theme_tab_background_inactive`.** Chrome draws
  that image verbatim — handing it the pre-darkened frame image rendered `#c5b285`
  against a `#d5c8a6` frame. So while the frame is compensated, inactive tabs were
  drawn at the raw title bar color and sat 1-2/255 lighter than it: a small step,
  but a hard edge across a flat field, so the tab shapes were visible whenever the
  window lost focus. `redim()` round-trips the color through `undim` and the wash
  to get what the frame actually lands on. Light themes then match exactly; dark
  themes land within 2/255, improved from a warm-against-neutral mismatch.
- **Chrome has no tab-border property.** With transparent tabs, the edges are
  Chrome's own separators. A line could be baked into the tab image (it samples
  image row = window y + 16), but that offset shifts in fullscreen and the line
  would drift into the middle of the tab, so it is not shipped.

One theme is emitted per Gruvbox variant in the source file — currently dark,
dark-hard, dark-soft, light, light-hard, light-soft.

## Publishing to the Chrome Web Store

`.github/workflows/publish.yml` runs on a `v*` tag, or manually from the Actions
tab where you can pick individual themes, the audience, and the version. It ships
the committed `dist/` with only the manifest version rewritten, so a tag publishes
exactly the themes in that tag rather than a rebuild against whatever Zed's
upstream themes look like that day.

`python3 tools/publish.py --version 1.0.7 --dry-run` builds the zips locally
without touching the API, and `--check` verifies the credentials mint an access
token without needing any item ids yet. The workflow exposes the latter as the
`check_only` input, so the secrets can be validated in CI before the store has
anything in it.

`python3 tools/listing.py [slug ...]` generates every listing asset the dashboard
demands, into `assets/<slug>/`:

| file | what it is |
|---|---|
| `icon-128.png` | 128x128, drawn from the theme's own colors |
| `screenshot-1280x800.png` | a real capture of Chrome wearing the theme |
| `promo-440x280.png` | the small tile, without which the dashboard refuses to publish ("Small tile image is missing") |

All three are exactly the dimensions the store requires: the preview window is
asked for 1280x800 so the retina capture downscales without cropping, and the tile
is cropped to its own 1.571:1 aspect before scaling rather than squashed into it.
`--no-shots` skips the Chrome runs and reuses the existing screenshot. Only the
description is left to write by hand.

Three things have to be set up once:

1. **An item per theme.** The API can update an item but cannot create one, so
   each theme needs one manual upload in the
   [Developer Dashboard](https://chrome.google.com/webstore/devconsole). Take the
   id from the dashboard URL and add it to `store-items.json` as
   `"theme-slug": "id"`. Only themes listed there are published — with 11 themes
   that is 11 items and 11 one-time uploads, so it is reasonable to list just the
   ones you actually want on the store.
2. **API credentials.** In a Google Cloud project, enable the Chrome Web Store
   API and create an OAuth client of type Desktop app. Authorize it once for the
   `https://www.googleapis.com/auth/chromewebstore` scope and exchange the code
   for a refresh token.
3. **Repository secrets** `CWS_CLIENT_ID`, `CWS_CLIENT_SECRET` and
   `CWS_REFRESH_TOKEN`.

Versions must increase — the store rejects a re-upload at the same version — so a
manual run without an explicit version uses `1.0.<run number>`. Note that the
`default` target submits for review rather than going live immediately;
`trustedTesters` is the safer choice for a first run and is the manual default.
