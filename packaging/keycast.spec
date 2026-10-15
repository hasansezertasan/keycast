# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build recipe for keycast -- the single spec for every frozen
# artifact (see docs/PACKAGING.md and docs/adr/001-desktop-app-packaging.md).
# It defines two independent targets from two entry points:
#
#   - onefile: single-file console executable of the Typer CLI
#     (`src/keycast/cli.py` -> dist/keycast-onefile[.exe]). The frozen CLI must
#     behave exactly like the installed `keycast.cli:app` console script (see
#     [project.scripts] in pyproject.toml): `--help`/`version`/`info` stay lazy
#     and never import the GUI stack (tkinter/pynput), so the headless CI
#     smoke-run passes, while a bare run launches the overlay via main().
#     `src/keycast/__main__.py` is NOT the entry here -- it calls main()
#     directly, ignores argv (so `--help` would launch the GUI instead of
#     printing help), and imports pynput at module import time. This is the
#     terminal-distributed artifact (direct download; Scoop installs the raw
#     Windows binary via `bin`), so it must stay console: a windowed build has
#     no stdout and those subcommands silently produce nothing.
#   - desktop: onedir windowed bundle of the overlay entry (`entry.py` ->
#     dist/keycast[.exe] + deps):
#       - macOS:   BUNDLE wraps the COLLECT output into dist/keycast.app
#       - Windows: BUNDLE is a no-op (`if not is_darwin: return` in PyInstaller),
#                  so the build stops at COLLECT -> dist/keycast/ (keycast.exe +
#                  deps), which CI zips as keycast-windows.zip.
#     The onefile is named `keycast-onefile` (not `keycast`) because a file and
#     the COLLECT directory cannot share `dist/keycast[.exe]`; downstream jobs
#     rename it to the per-OS `keycast-freezer-<label>` release asset.
# The macOS-only EXE/BUNDLE args (argv_emulation, target_arch, codesign_identity,
# entitlements_file, bundle_identifier) are ignored off macOS.
#
# Which targets build is selected with KEYCAST_BUILD ("onefile" | "desktop" |
# "all", default "all"), so the fast paths (`mise run freeze`, the
# build-freezer CI/release jobs) do not pay for the desktop bundle and the
# desktop jobs do not pay for the onefile:
#
#     KEYCAST_BUILD=onefile pyinstaller packaging/keycast.spec   # CLI binary only
#     KEYCAST_BUILD=desktop pyinstaller packaging/keycast.spec   # desktop bundle only
#
# Build from the repo root with a venv on a verified-good Astral CPython build
# (3.14.6 tested good; see ADR-001 -- 3.14.3 ships broken Tk, so bump the pin
# deliberately rather than floating the patch).
#
# Tk/Tcl and the platform input backend (pynput: pyobjc-Quartz on macOS, win32 on
# Windows) are picked up automatically; no hidden imports as of keycast 0.1.0.
# Builds for the host architecture only (Astral standalone builds are single-arch).
#
# Icons are platform-specific: the Windows EXE embeds keycast.ico, the macOS
# BUNDLE wraps keycast.icns. Both live next to this spec (regenerate via
# `uv run --with pillow packaging/make_icons.py`). The unused icon per platform is
# left None so PyInstaller doesn't warn about the wrong format -- BUNDLE is a no-op
# off macOS and the EXE icon is meaningless on macOS.

import os
import sys
from pathlib import Path

_BUILD_TARGETS = os.environ.get("KEYCAST_BUILD", "all")
if _BUILD_TARGETS not in ("onefile", "desktop", "all"):
    raise ValueError(
        f"KEYCAST_BUILD must be one of 'onefile', 'desktop', 'all' (got {_BUILD_TARGETS!r})"
    )

_ROOT = Path(SPECPATH).parent  # noqa: F821 -- PyInstaller injects SPECPATH into the spec namespace
_ICON_DIR = Path(SPECPATH)  # noqa: F821 -- PyInstaller injects SPECPATH into the spec namespace
_EXE_ICON = str(_ICON_DIR / "keycast.ico") if sys.platform == "win32" else None
_BUNDLE_ICON = str(_ICON_DIR / "keycast.icns")

if _BUILD_TARGETS in ("onefile", "all"):
    a_onefile = Analysis(
        [str(_ROOT / "src" / "keycast" / "cli.py")],
        pathex=[str(_ROOT / "src")],
        binaries=[],
        datas=[],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
    )
    pyz_onefile = PYZ(a_onefile.pure)

    exe_onefile = EXE(
        pyz_onefile,
        a_onefile.scripts,
        a_onefile.binaries,
        a_onefile.datas,
        [],
        name="keycast-onefile",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        # TODO @hasansezertasan: UPX is off by default -- it is not preinstalled on CI
        # runners (PyInstaller silently skips it) and has corrupted binaries on macOS
        # and some Windows setups. Install UPX and flip to True if you want compression.
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        # Console subsystem (Windows-only flag; ignored on macOS/Linux).
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

if _BUILD_TARGETS in ("desktop", "all"):
    a = Analysis(
        ["entry.py"],
        pathex=[],
        binaries=[],
        datas=[],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
        optimize=0,
    )
    pyz = PYZ(a.pure)

    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="keycast",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,  # UPX can corrupt Mach-O binaries and breaks code signing/notarization on macOS
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=_EXE_ICON,  # Windows .exe icon; None on macOS (see header)
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,  # UPX can corrupt Mach-O binaries and breaks code signing/notarization on macOS
        upx_exclude=[],
        name="keycast",
    )
    app = BUNDLE(
        coll,
        name="keycast.app",
        icon=_BUNDLE_ICON,  # macOS .app icon; ignored by BUNDLE off macOS
        bundle_identifier="com.hasansezertasan.keycast",
    )
