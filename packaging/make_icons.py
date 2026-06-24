#!/usr/bin/env python3
"""Generate keycast's application icons from a single programmatic source.

The design is a command-palette HUD: the keyboard ``⌘K`` shortcut in white on a
dark gradient squircle. It mirrors what keycast actually draws -- light key text
on a dark overlay -- rather than depicting a physical key.

This is a *build-time* helper, not part of the shipped package -- run it on macOS
(it shells out to ``iconutil`` and uses the system San Francisco font for the ⌘
glyph) whenever the icon needs regenerating:

    uv run --with pillow packaging/make_icons.py

Outputs ``packaging/keycast.icns`` (macOS BUNDLE) and ``packaging/keycast.ico``
(Windows EXE). Pillow is pulled in only for this run via ``--with``; it is not a
project dependency. The committed .icns/.ico mean CI never needs Pillow or the
font. Rendering is done at 4x and downsampled with LANCZOS so the edges stay
clean at every embedded size.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Palette. The glyphs are a single neutral ink so the icon reads at 16px; all the
# colour is in the dark background gradient.
SLATE_TOP = (28, 32, 41)  # background gradient, top
SLATE_BOT = (16, 18, 24)  # background gradient, bottom
INK = (244, 246, 248, 255)  # the "⌘K" glyphs

SHORTCUT = "⌘K"  # what the HUD shows -- the universal "command palette" shortcut

# macOS system fonts that carry the ⌘ (U+2318) glyph; first hit wins. Generation
# is macOS-only (needs iconutil), so San Francisco is always present.
FONT_CANDIDATES = (
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
)

SCALE = 4  # supersampling factor for antialiasing
BASE = 1024  # logical icon size (master is BASE * SCALE)

# macOS .iconset members: (filename, pixel size). iconutil derives .icns from these.
ICONSET = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]
# Windows .ico embeds several sizes; the OS picks per display context.
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def _load_font(px: int) -> ImageFont.FreeTypeFont:
    """Load a bold system font that has the ⌘ glyph, at the given pixel size."""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            font = ImageFont.truetype(path, px)
            try:  # SFNS.ttf is a variable font; pin the Bold instance.
                font.set_variation_by_name("Bold")
            except OSError, ValueError:
                pass
            return font
    msg = f"no system font with the ⌘ glyph found in {FONT_CANDIDATES}"
    raise RuntimeError(msg)


def render_master() -> Image.Image:
    """Render the icon at BASE*SCALE, then downsample to BASE for clean edges."""
    s = BASE * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Background squircle: a soft vertical gradient clipped to a rounded square,
    # with a small transparent margin so it reads well both full-bleed (Windows)
    # and inside macOS's own rounded mask.
    grad = Image.new("RGB", (1, s))
    for y in range(s):
        t = y / (s - 1)
        grad.putpixel(
            (0, y),
            tuple(
                round(SLATE_TOP[c] + (SLATE_BOT[c] - SLATE_TOP[c]) * t)
                for c in range(3)
            ),
        )
    grad = grad.resize((s, s)).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    margin = round(s * 0.06)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, s - margin, s - margin), radius=round(s * 0.225), fill=255
    )
    img.paste(grad, (0, 0), mask)

    draw = ImageDraw.Draw(img)

    # "⌘K", centred. The two glyphs have different ink heights, so place each one
    # by its own bounding box (horizontally packed, each vertically centred) for
    # clean optical alignment.
    font = _load_font(round(s * 0.40))
    cmd, key = SHORTCUT[0], SHORTCUT[1]
    gap = s * 0.015
    cb = draw.textbbox((0, 0), cmd, font=font)
    kb = draw.textbbox((0, 0), key, font=font)
    cw, kw = cb[2] - cb[0], kb[2] - kb[0]
    x = s / 2 - (cw + gap + kw) / 2
    cy = s / 2
    draw.text((x - cb[0], cy - (cb[3] + cb[1]) / 2), cmd, font=font, fill=INK)
    draw.text(
        (x + cw + gap - kb[0], cy - (kb[3] + kb[1]) / 2), key, font=font, fill=INK
    )

    return img.resize((BASE, BASE), Image.LANCZOS)


def write_assets(here: Path) -> None:
    master = render_master()

    ico_path = here / "keycast.ico"
    master.save(ico_path, sizes=[(n, n) for n in ICO_SIZES])
    print(f"wrote {ico_path.relative_to(here.parent)}")

    if shutil.which("iconutil") is None:
        print("iconutil not found (macOS only); skipped keycast.icns")
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "keycast.iconset"
        iconset.mkdir()
        for name, size in ICONSET:
            master.resize((size, size), Image.LANCZOS).save(iconset / name)
        icns_path = here / "keycast.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
            check=True,
        )
        print(f"wrote {icns_path.relative_to(here.parent)}")


def main() -> None:
    write_assets(Path(__file__).resolve().parent)


if __name__ == "__main__":
    main()
