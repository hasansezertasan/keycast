# PyInstaller spec for keycast — see ADR-007.
# Build with: pyinstaller keycast.spec   (or: mise run freeze)
# Produces a single self-contained executable that needs no Python on the target.
# -*- mode: python ; coding: utf-8 -*-

# The single runnable entrypoint (see src/keycast/__main__.py),
# which runs whichever component this project enabled (CLI/GUI/TUI/web/...).
entry_point = "src/keycast/__main__.py"

a = Analysis(
    [entry_point],
    pathex=["src"],
    binaries=[],
    datas=[],
    # TODO @hasansezertasan: add hidden imports if PyInstaller misses any.
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="keycast",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # TODO @hasansezertasan: UPX is off by default — it is not preinstalled on CI
    # runners (PyInstaller silently skips it) and has corrupted binaries on macOS
    # and some Windows setups. Install UPX and flip to True if you want compression.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
