#!/usr/bin/env python3
"""Generate keycast's application icons from a single programmatic source.

The design is a light keycap (the "key" in keycast) on a dark slate squircle,
with a bold accent-colored "K" on the cap. The look mirrors the overlay itself:
crisp glyphs on a dark surface.

This is a *build-time* helper, not part of the shipped package -- run it
on macOS (it shells out to ``iconutil``) whenever the icon needs regenerating:

    uv run --with pillow packaging/make_icons.py            # write .icns + .ico
    uv run --with pillow packaging/make_icons.py preview    # write a contact sheet

Outputs ``packaging/keycast.icns`` (macOS BUNDLE) and ``packaging/keycast.ico``
(Windows EXE). Pillow is pulled in only for this run via ``--with``; it is not a
project dependency. Rendering is done at 4x and downsampled with LANCZOS so the
edges stay clean at every embedded size.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

# Palette. The K is the only colored element; everything else is neutral so the
# icon reads at 16px. The K is two-toned after the Python logo: a blue upper half
# and a yellow lower half, split at the point where the arms meet the stem.
SLATE_TOP = (28, 32, 41)  # background gradient, top
SLATE_BOT = (16, 18, 24)  # background gradient, bottom
KEYCAP = (250, 251, 252, 255)  # keycap face
KEYCAP_EDGE = (206, 211, 219, 255)  # keycap bottom slab (fake 3D depth)
PY_BLUE = (55, 118, 171, 255)  # Python logo blue (#3776AB) -- K upper half
PY_YELLOW = (255, 212, 59, 255)  # Python logo yellow (#FFD43B) -- K lower half

# Named two-tone schemes offered by `preview` mode (label -> (top, bottom) RGBA).
ACCENT_CHOICES = {
    "python": (PY_BLUE, PY_YELLOW),
    "blue": ((76, 141, 255, 255), (76, 141, 255, 255)),
    "violet": ((139, 92, 246, 255), (139, 92, 246, 255)),
    "green": ((52, 211, 153, 255), (52, 211, 153, 255)),
}

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


def _vertical_gradient(
    size: int, top: tuple[int, int, int], bot: tuple[int, int, int]
) -> Image.Image:
    """A 1px-wide vertical gradient stretched to a square -- cheap and smooth."""
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel(
            (0, y),
            tuple(round(top[c] + (bot[c] - top[c]) * t) for c in range(3)),
        )
    return grad.resize((size, size))


def render_master(
    top_color: tuple[int, int, int, int] = PY_BLUE,
    bot_color: tuple[int, int, int, int] = PY_YELLOW,
) -> Image.Image:
    """Render the icon at BASE*SCALE, then downsample to BASE for clean edges.

    ``top_color``/``bot_color`` tint the K's upper and lower halves; pass the same
    value for both to get a single-color K.
    """
    s = BASE * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Background squircle: a soft vertical gradient clipped to a rounded square,
    # with a small transparent margin so it reads well both full-bleed (Windows)
    # and inside macOS's own rounded mask.
    margin = round(s * 0.06)
    radius = round(s * 0.225)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, s - margin, s - margin), radius=radius, fill=255
    )
    grad = _vertical_gradient(s, SLATE_TOP, SLATE_BOT).convert("RGBA")
    img.paste(grad, (0, 0), mask)

    draw = ImageDraw.Draw(img)

    # Keycap: a rounded square with a darker slab peeking out the bottom to fake a
    # 3D key edge. Centered, nudged up a touch to sit optically centered.
    cap = s * 0.50
    cx, cy = s / 2, s * 0.50
    cap_r = cap * 0.22
    depth = s * 0.030
    draw.rounded_rectangle(
        (cx - cap / 2, cy - cap / 2 + depth, cx + cap / 2, cy + cap / 2 + depth),
        radius=cap_r,
        fill=KEYCAP_EDGE,
    )
    draw.rounded_rectangle(
        (cx - cap / 2, cy - cap / 2, cx + cap / 2, cy + cap / 2),
        radius=cap_r,
        fill=KEYCAP,
    )

    # The "K", drawn as three thick strokes (stem + two arms meeting mid-stem) so
    # the joints self-intersect cleanly. No bundled font needed. The upper half
    # (top of stem + upper arm) and lower half (bottom of stem + lower arm) are
    # tinted separately for the Python two-tone look; the split is the junction.
    lw = round(cap * 0.135)  # stroke width
    sx = cx - cap * 0.22  # stem x
    top = cy - cap * 0.30
    bot = cy + cap * 0.30
    tipx = cx + cap * 0.26  # arm tips x
    junction = cy - cap * 0.04  # arms meet just above center for a balanced K

    def _cap(px: float, py: float, color: tuple[int, int, int, int]) -> None:
        draw.ellipse((px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2), fill=color)

    # Lower half first, then upper, so the blue sits on top at the junction.
    draw.line([(sx, junction), (sx, bot)], fill=bot_color, width=lw)
    draw.line([(sx, junction), (tipx, bot)], fill=bot_color, width=lw)
    _cap(sx, bot, bot_color)
    _cap(tipx, bot, bot_color)
    draw.line([(sx, top), (sx, junction)], fill=top_color, width=lw)
    draw.line([(sx, junction), (tipx, top)], fill=top_color, width=lw)
    _cap(sx, top, top_color)
    _cap(tipx, top, top_color)
    _cap(sx, junction, top_color)

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


def write_preview(path: Path) -> None:
    """Render one tile per named accent into a single contact sheet for review."""
    tile = 256
    pad = 24
    labels = list(ACCENT_CHOICES)
    sheet = Image.new(
        "RGBA",
        (tile * len(labels) + pad * (len(labels) + 1), tile + pad * 2),
        (32, 34, 38, 255),
    )
    for i, name in enumerate(labels):
        top, bot = ACCENT_CHOICES[name]
        thumb = render_master(top, bot).resize((tile, tile), Image.LANCZOS)
        sheet.paste(thumb, (pad + i * (tile + pad), pad), thumb)
    sheet.save(path)
    print(f"wrote {path}  (left to right: {', '.join(labels)})")


def main() -> None:
    here = Path(__file__).resolve().parent
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        write_preview(Path(tempfile.gettempdir()) / "keycast_accents.png")
    else:
        write_assets(here)


if __name__ == "__main__":
    main()
