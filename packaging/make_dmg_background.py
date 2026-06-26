#!/usr/bin/env python3
"""Generate the keycast ``.dmg`` background from a single programmatic source.

The background reuses the icon's visual language -- the dark slate gradient and
the ``⌘K`` HUD motif from ``make_icons.py`` -- so the disk image feels like the
same product as the dock icon it installs. It draws a faint wordmark top-left
and a muted arrow guiding the eye from the app icon toward the ``/Applications``
drop target; Finder paints the icon *labels* itself, so we don't.

Like ``make_icons.py`` this is a *build-time* helper, not shipped in the package.
Run it on macOS (it shells out to ``tiffutil`` for the multi-resolution output)
whenever the background needs regenerating:

    uv run --with pillow packaging/make_dmg_background.py

Output is ``packaging/dmg_background.tiff`` -- a multi-resolution TIFF carrying a
640x320 ``@1x`` page and a 1280x640 ``@2x`` page so it stays crisp on Retina.
``dmgbuild`` points at it via ``background`` in ``dmg_settings.py``. Pillow is
pulled in only for this run via ``--with``; it is not a project dependency, and
the committed ``.tiff`` means CI never needs Pillow or the font. Rendering is
done at 4x and downsampled with LANCZOS so edges stay clean.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Palette -- mirrors make_icons.py so the .dmg and the icon read as one product.
SLATE_TOP = (28, 32, 41)  # background gradient, top
SLATE_BOT = (16, 18, 24)  # background gradient, bottom
INK = (244, 246, 248)  # wordmark + arrow ink (alpha applied per element)

SHORTCUT = "⌘K"  # the command-palette motif, echoing the icon

# macOS system fonts that carry the ⌘ (U+2318) glyph; first hit wins. Generation
# is macOS-only (needs tiffutil), so San Francisco is always present.
FONT_CANDIDATES = (
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
)

# Window + icon layout, in logical points. These MUST match window_rect and
# icon_locations in dmg_settings.py: the arrow is drawn into the gap between the
# two icon centres, so the two files share one coordinate system.
WIN_W, WIN_H = 640, 320
APP_CENTER = (160, 170)  # keycast.app icon centre
APPS_CENTER = (480, 170)  # /Applications alias centre

SCALE = 4  # supersampling factor for antialiasing


def _load_font(px: int) -> ImageFont.FreeTypeFont:
    """Load a system font that has the ⌘ glyph, at the given pixel size."""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            font = ImageFont.truetype(path, px)
            try:  # SFNS.ttf is a variable font; pin a Medium instance.
                font.set_variation_by_name("Medium")
            except (OSError, ValueError) as exc:
                # Non-variable font or a renamed/missing "Medium" instance: keep
                # going at the default weight, but announce it — a silent weight
                # drift would otherwise only show up by eyeballing the artifact.
                print(
                    f"warning: could not pin 'Medium' weight on {path}; "
                    f"using default weight ({exc})",
                    file=sys.stderr,
                )
            return font
    msg = f"no system font with the ⌘ glyph found in {FONT_CANDIDATES}"
    raise RuntimeError(msg)


def render_master() -> Image.Image:
    """Render at the @2x size times SCALE, for downsampling to @2x and @1x."""
    k = 2 * SCALE  # logical-point -> master-pixel factor
    w, h = WIN_W * k, WIN_H * k

    # Vertical slate gradient, same routine as the icon's squircle fill.
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        grad.putpixel(
            (0, y),
            tuple(
                round(SLATE_TOP[c] + (SLATE_BOT[c] - SLATE_TOP[c]) * t)
                for c in range(3)
            ),
        )
    img = grad.resize((w, h)).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Wordmark, top-left, slightly dimmed so it reads as branding not a heading.
    font = _load_font(round(22 * k))
    draw.text(
        (round(40 * k), round(28 * k)),
        f"keycast  {SHORTCUT}",
        font=font,
        fill=(*INK, 235),
    )

    # Guiding arrow in the gap between the icons (~35% ink so it never competes
    # with the icons Finder draws on top). Centres at y=170; the app icon ends
    # near x=224 and /Applications starts near x=416, so stay inside (248, 392).
    y = round(APP_CENTER[1] * k)
    x0, x1 = round(248 * k), round(392 * k)
    arrow = (*INK, 90)
    draw.line((x0, y, x1, y), fill=arrow, width=round(3 * k))
    head = round(12 * k)
    draw.polygon(
        [(x1, y - head), (x1 + round(1.6 * head), y), (x1, y + head)], fill=arrow
    )

    return img


def write_background(here: Path) -> None:
    master = render_master()
    img2x = master.resize((WIN_W * 2, WIN_H * 2), Image.LANCZOS)
    img1x = master.resize((WIN_W, WIN_H), Image.LANCZOS)

    if shutil.which("tiffutil") is None:
        # tiffutil is macOS-only. Write a 1x PNG as a preview so the run produces
        # *something*, but it is NOT what the build consumes: dmg_settings.py
        # points `background` at dmg_background.tiff, which we have not touched.
        # Say so loudly so a non-macOS contributor doesn't think they regenerated
        # the committed asset.
        png_path = here / "dmg_background.png"
        img1x.save(png_path)
        print(
            f"WARNING: tiffutil not found (macOS only); wrote 1x-only preview "
            f"{png_path.relative_to(here.parent)}. The committed "
            f"dmg_background.tiff that dmg_settings.py loads was NOT "
            f"regenerated — run this on macOS to update it.",
            file=sys.stderr,
        )
        return

    with tempfile.TemporaryDirectory() as tmp:
        p1 = Path(tmp) / "bg_1x.png"
        p2 = Path(tmp) / "bg_2x.png"
        img1x.save(p1)
        img2x.save(p2)
        tiff_path = here / "dmg_background.tiff"
        # -cathidpicheck marks the second page as the @2x (HiDPI) representation.
        subprocess.run(
            ["tiffutil", "-cathidpicheck", str(p1), str(p2), "-out", str(tiff_path)],
            check=True,
        )
        print(f"wrote {tiff_path.relative_to(here.parent)}")


def main() -> None:
    write_background(Path(__file__).resolve().parent)


if __name__ == "__main__":
    main()
