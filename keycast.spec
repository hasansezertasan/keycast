# PyInstaller spec for keycast — see https://hasansezertasan.github.io/copier-pyproject/context/standalone-executables/#executables-are-named-per-tool-and-os-and-all-target-the-package-main-module.
# Build with: pyinstaller keycast.spec   (or: mise run freeze)
# Produces a single self-contained executable that needs no Python on the target.
# -*- mode: python ; coding: utf-8 -*-

# The frozen `keycast` executable must behave exactly like the installed
# `keycast.cli:app` console script (see [project.scripts] in pyproject.toml):
# `--help`/`version`/`info` stay lazy and never import the GUI stack
# (tkinter/pynput), so the headless CI smoke-run passes, while a bare run
# launches the overlay via main(). `src/keycast/__main__.py` is NOT the entry
# here — it calls main() directly, ignores argv (so `--help` would launch the
# GUI instead of printing help), and imports pynput at module import time.
entry_point = "src/keycast/cli.py"

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
    # Console subsystem (Windows-only flag; ignored on macOS/Linux). The
    # freezer exe is terminal-distributed (Scoop installs the raw Windows
    # binary via `bin`), so `--help`/`version`/`info` must print to the
    # caller's terminal: a windowed build has no stdout and those subcommands
    # silently produce nothing. packaging/keycast.spec deliberately stays
    # windowed — the .app/.msi are desktop bundles launched from a menu,
    # while this artifact doubles as the CLI.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
