"""Main entry point for the keycast application."""

import logging
import sys

from keycast.application import Keycast
from keycast.logging_setup import format_event


def main() -> None:
    """Main entry point for the keycast application.

    ``Keycast()`` builds the tkinter window during construction (before
    ``run()``'s own error handling is entered), so a failure there would
    otherwise escape as an uncaught traceback. Catch it here so startup degrades
    to a logged error and a non-zero exit, matching the app's "degrade, don't
    crash" behavior. ``Keycast.__init__`` configures logging before building the
    window, so these log lines reach the file and console.

    The headless case is singled out for an actionable hint, since a bare
    traceback would not tell the user what to fix. It covers both a host with no
    display server (``tk.TclError`` -- no ``$DISPLAY`` / not a desktop session)
    and a Python built without the ``_tkinter`` C-extension (``ImportError`` on
    the lazy import below, e.g. some Homebrew builds).
    """
    # Imported lazily (not at module top) so keycast.main stays importable on a
    # Python built without the _tkinter C-extension or in headless tooling like
    # slotscheck; tk is only needed once the app actually starts. A missing
    # _tkinter raises ImportError here, which the headless branch also handles.
    try:
        import tkinter as tk  # noqa: PLC0415
    except ImportError:
        logging.getLogger("keycast").exception(
            format_event(
                "application_startup_failed",
                reason="no_display",
                hint="keycast needs the tkinter GUI toolkit, but this Python was "
                "built without it; install a Python that includes _tkinter (e.g. "
                "the python.org build, or 'brew install python-tk')",
            )
        )
        sys.exit(1)

    try:
        app = Keycast()
    except tk.TclError:
        logging.getLogger("keycast").exception(
            format_event(
                "application_startup_failed",
                reason="no_display",
                hint="keycast needs a graphical display but none was found; "
                "run it in a desktop session (or set DISPLAY)",
            )
        )
        sys.exit(1)
    except Exception:
        logging.getLogger("keycast").exception(
            format_event("application_startup_failed")
        )
        sys.exit(1)
    app.run()


if __name__ == "__main__":
    main()
