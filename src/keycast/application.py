"""Main entry point for the keycast application."""

import logging
import platform
import signal
import sys
from typing import TYPE_CHECKING

from keycast import __version__
from keycast.display import DisplayWindow
from keycast.listeners import KeyListener, MouseListener
from keycast.logging_setup import format_event, setup_logging
from keycast.settings import Settings

if TYPE_CHECKING:
    import types


class Keycast:
    """Keycast application."""

    def __init__(self) -> None:
        """Initialize the keycast application."""
        # In the normal and corrupt-config-recovery paths this is a fully
        # validated Settings. In the absolute-worst case (the built-in defaults
        # themselves failing validation) create_settings_file falls back to an
        # unvalidated model_construct (see Settings._safe_defaults), so the rest
        # of this class must not assume field invariants beyond what defaults
        # provide. That fallback is near-impossible to reach in practice.
        self.settings = Settings.create_settings_file()
        # debug mode can widen logging beyond the configured level; resolve the
        # effective logging settings in one place (Settings.effective_logging)
        # rather than branching on settings.debug here.
        setup_logging(self.settings.effective_logging())
        self.logger = logging.getLogger(__name__)
        # First line after logging is configured: stamp the version and platform
        # so a user-submitted log identifies the build and OS that produced it.
        # Note: this logs sys.platform ("darwin"/"win32"/"linux"), which is a
        # *different* value set from the platform.system() ("Darwin"/"Windows"/
        # "Linux") that settings.py keys off for key-label normalization; the two
        # are not interchangeable.
        self.logger.info(
            format_event(
                "keycast_starting",
                version=__version__,
                platform=sys.platform,
            )
        )
        self._stopped = False
        self.display_window = DisplayWindow(self.settings.display)
        self.mouse_listener = MouseListener(
            show_text=self.display_window.show_text,
            settings=self.settings.mouse,
        )
        self.key_listener = KeyListener(
            show_text=self.display_window.show_text,
            settings=self.settings.keyboard,
        )

    def start(self) -> None:
        """Start the keycast application.

        Each input listener is started independently. A failure to capture one
        source — most often a missing OS input-monitoring permission
        (Accessibility on macOS), which is the single most likely real-world
        failure for this kind of tool — is logged with an actionable hint but
        does *not* abort startup: the overlay and the other listener still run.
        This keeps the app's "degrade, don't crash" behavior at the point it
        matters most. A genuinely fatal error raised from within this method
        (e.g. an unexpected failure inside ``display_window.start``'s main loop)
        still propagates to :meth:`run`. Note the display window is *constructed*
        in ``__init__``, so a headless ``TclError`` at construction time is
        handled earlier, in ``main``, and never reaches :meth:`run`.
        """
        # auto_start is the app-level master switch: when off, no listeners start
        # regardless of the per-listener keyboard.enabled / mouse.enabled flags.
        any_source_active = False
        if self.settings.auto_start:
            # Attempt both regardless of either's outcome (degrade, don't crash).
            started = [
                self._start_listener("mouse", self.mouse_listener),
                self._start_listener("keyboard", self.key_listener),
            ]
            any_source_active = any(started)
        else:
            self.logger.info(format_event("listeners_autostart_disabled"))

        # Only honor start_minimized when an input source is actually live to
        # re-show the overlay. The restore path is driven by show_text, so with no
        # active listener (all disabled, or all failed to start — e.g. missing OS
        # input permissions) nothing would ever deiconify the window and the app
        # would run invisibly. Degrade to a visible overlay instead.
        start_minimized = self.settings.start_minimized and any_source_active
        if self.settings.start_minimized and not any_source_active:
            self.logger.warning(
                format_event("start_minimized_ignored", reason="no_active_input_source")
            )
        # Start the display window last to avoid race conditions.
        self.display_window.start(start_minimized=start_minimized)

    def _start_listener(self, name: str, listener: MouseListener | KeyListener) -> bool:
        """Start one input listener, degrading to a logged hint on failure.

        Args:
            name: Human-readable listener name used for log context.
            listener: The listener to start.

        Returns:
            Whether the listener is now actively capturing input. A listener's
            ``start()`` is a no-op when it is disabled (``settings.enabled``
            false) and raises on genuine failure, so a source is live only when
            it is enabled *and* started without error. Callers use this to tell
            whether any source can re-show a minimized overlay (see :meth:`start`).
        """
        try:
            listener.start()
        except Exception:
            self.logger.exception(format_event("listener_start_failed", listener=name))
            self._warn_input_unavailable(name)
            return False
        return listener.settings.enabled

    @staticmethod
    def _input_permission_hint() -> str:
        """Return a platform-specific hint for a failed input capture.

        Returns:
            A short, actionable sentence for the host platform.
        """
        system = platform.system()
        if system == "Darwin":
            return (
                "grant keycast Accessibility and Input Monitoring permission in "
                "System Settings > Privacy & Security, then restart it"
            )
        if system == "Linux":
            return (
                "ensure a graphical session is running and your user is allowed "
                "to read input devices"
            )
        return "check that keycast is permitted to monitor keyboard and mouse input"

    def _warn_input_unavailable(self, name: str) -> None:
        """Log an actionable error when a listener cannot capture input.

        Logging is already configured by the time :meth:`start` runs, so this
        reaches both the log file and the console handler rather than silently
        exiting with a bare traceback.

        Args:
            name: The listener that failed to start.
        """
        self.logger.error(
            format_event(
                "input_capture_unavailable",
                listener=name,
                hint=self._input_permission_hint(),
            )
        )

    def stop(self) -> None:
        """Stop the keycast application.

        Idempotent: safe to call multiple times (e.g. from a signal handler
        and again from ``run``'s ``finally`` block).
        """
        if self._stopped:
            return
        self._stopped = True
        # Best-effort, independent teardown: a failure stopping one component
        # must not prevent the others from being stopped (a leaked listener
        # thread or undestroyed window can keep the process alive).
        for name, component in (
            ("mouse_listener", self.mouse_listener),
            ("keyboard_listener", self.key_listener),
            ("display_window", self.display_window),
        ):
            try:
                component.stop()
            except Exception:
                self.logger.exception(
                    format_event("component_stop_error", component=name)
                )
        self.logger.info(format_event("keycast_stopped"))

    def signal_handler(self, _signum: int, _frame: types.FrameType | None) -> None:
        """Stop the application in response to SIGINT/SIGTERM.

        The handler runs on the main thread, which is blocked inside the
        tkinter main loop. It only *requests* the loop to exit (it does not
        tear the window down in place — destroying a window while still nested
        in ``mainloop`` raises Tcl errors). Once ``mainloop`` returns, control
        unwinds to ``run`` where the ``finally`` block performs the actual
        shutdown via :meth:`stop`.
        """
        self.logger.info(format_event("shutdown_signal_received", signum=_signum))
        self.display_window.request_stop()

    def run(self) -> None:
        """Run the keycast application."""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        try:
            self.start()
        except KeyboardInterrupt:
            self.logger.info(
                format_event("application_interrupted", reason="keyboard_interrupt")
            )
        except Exception as exc:
            self.logger.exception(
                format_event("application_error", error=type(exc).__name__)
            )
            sys.exit(1)
        finally:
            self.stop()
