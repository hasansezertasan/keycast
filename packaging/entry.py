"""PyInstaller entry point for the bundled app (macOS ``.app`` / Windows folder).

One entry script drives both platforms (see ``packaging/keycast.spec``).
Double-clicking the bundled app launches straight into the overlay -- the
behavior of ``keycast`` with no subcommand. This deliberately bypasses the Typer
CLI (``keycast.cli:app``): the CLI subcommands (``version``, ``info``) belong to
the terminal/formula install, while the bundle is the GUI launch surface. See
``docs/PACKAGING.md`` and ``docs/adr/001-desktop-app-packaging.md``.
"""

from keycast.main import main

if __name__ == "__main__":
    main()
