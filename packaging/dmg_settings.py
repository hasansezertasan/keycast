# dmgbuild settings for the keycast .dmg — a drag-to-Applications layout.
#
# dmgbuild builds the styled volume by writing the Finder ".DS_Store" directly
# (via mac_alias/ds_store), so it needs no Finder/AppleScript and runs headless
# in CI deterministically — unlike create-dmg. See docs/PACKAGING.md.
#
# Invoked as:
#   uvx dmgbuild -s packaging/dmg_settings.py -D app=dist/keycast.app \
#       keycast keycast.dmg
#
# `defines` holds the -D key=value pairs; dmgbuild exec's this file with it
# (and `os`) in scope.
import os.path

# Source .app, overridable with -D app=... so local builds can point elsewhere.
app = defines.get("app", "dist/keycast.app")  # noqa: F821 (provided by dmgbuild)
appname = os.path.basename(app)

# --- Volume contents -------------------------------------------------------
# The .app plus an /Applications alias the user drags onto.
files = [app]
symlinks = {"Applications": "/Applications"}

# --- Disk image format -----------------------------------------------------
format = "UDZO"  # zlib-compressed, read-only — same format as the old hdiutil.
size = None  # auto-size to contents.

# --- Finder window + icon layout -------------------------------------------
default_view = "icon-view"
window_rect = ((200, 200), (640, 320))  # ((x, y), (w, h)) on screen.
icon_size = 128
text_size = 14

# App on the left, the /Applications drop target on the right: the arrow the
# eye expects to follow when dragging. These centres MUST match APP_CENTER /
# APPS_CENTER in make_dmg_background.py, whose arrow is drawn (hard-coded to the
# gap, x=248..392) between them — move an icon here and the arrow misaligns
# silently until the background is regenerated.
icon_locations = {
    appname: (160, 170),
    "Applications": (480, 170),
}

# Branded background: dark slate gradient + wordmark + a drag arrow, generated
# by packaging/make_dmg_background.py. Multi-resolution .tiff (@1x + @2x) so it
# stays crisp on Retina. icon_locations above are positioned for its arrow.
background = "packaging/dmg_background.tiff"
