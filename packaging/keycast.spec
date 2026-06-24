# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build recipe for keycast, used on BOTH macOS and Windows (see
# docs/PACKAGING.md and docs/adr/001-desktop-app-packaging.md):
#   - macOS:   BUNDLE wraps the COLLECT output into dist/keycast.app
#   - Windows: BUNDLE is a no-op (`if not is_darwin: return` in PyInstaller), so
#              the build stops at COLLECT -> dist/keycast/ (keycast.exe + deps),
#              which CI zips as keycast-windows.zip.
# The macOS-only EXE/BUNDLE args (argv_emulation, target_arch, codesign_identity,
# entitlements_file, bundle_identifier) are ignored off macOS.
#
# Build from the repo root with a venv on a verified-good Astral CPython build
# (3.14.6 tested good; see ADR-001 -- 3.14.3 ships broken Tk, so bump the pin
# deliberately rather than floating the patch):
#
#     pyinstaller packaging/keycast.spec
#
# Tk/Tcl and the platform input backend (pynput: pyobjc-Quartz on macOS, win32 on
# Windows) are picked up automatically; no hidden imports as of keycast 0.1.0.
# Builds for the host architecture only (Astral standalone builds are single-arch).

a = Analysis(
    ['entry.py'],
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
    name='keycast',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,  # UPX can corrupt Mach-O binaries and breaks code signing/notarization on macOS
    upx_exclude=[],
    name='keycast',
)
app = BUNDLE(
    coll,
    name='keycast.app',
    icon=None,
    bundle_identifier='com.hasansezertasan.keycast',
)
