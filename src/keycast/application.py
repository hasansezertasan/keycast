"""Main entry point for the keycast application."""

import ctypes
import logging
import platform
import signal
import sys
from enum import StrEnum
from typing import TYPE_CHECKING

from keycast import __version__
from keycast.display import DisplayWindow
from keycast.listeners import KeyListener, MouseListener
from keycast.logging_setup import format_event, setup_logging
from keycast.settings import Settings
from keycast.updates import notify_pending_update

if TYPE_CHECKING:
    import types

_MACOS_APP_SERVICES_FRAMEWORK = (
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)


class _InputSourceStatus(StrEnum):
    """Startup status for one input source."""

    ACTIVE = "active"
    DISABLED = "disabled"
    NO_ACCESS = "no_access"
    UNKNOWN = "unknown"


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
        started: dict[str, bool] = {"mouse": False, "keyboard": False}
        if self.settings.auto_start:
            # Attempt both regardless of either's outcome (degrade, don't crash).
            started["mouse"] = self._start_listener("mouse", self.mouse_listener)
            started["keyboard"] = self._start_listener("keyboard", self.key_listener)
        else:
            self.logger.info(format_event("listeners_autostart_disabled"))
        any_source_active = any(started.values())
        system = platform.system()
        precheck = self._startup_permission_precheck(system)
        statuses = self._startup_input_statuses(
            started=started, precheck=precheck, system=system
        )
        self._log_startup_input_status(statuses=statuses, precheck=precheck)

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
        # Briefly show the running version on launch so a user can confirm which
        # build is active at a glance; it fades like any other event. Routed
        # through the same show_text sink the listeners use, so it shares the fade
        # timer and needs no special rendering path. Skipped on a minimized start,
        # whose whole purpose is to stay hidden until the first real input — a
        # splash would defeat that.
        if not start_minimized:
            self.display_window.show_text(f"keycast {__version__}")
            if self.settings.show_startup_status:
                self.display_window.show_text(
                    self._format_startup_status_line(statuses)
                )
            # Surface a cached "update available" notice through the same sink, so
            # it shares the fade timer and needs no special rendering path. The
            # network refresh runs on a background daemon thread; any notice it
            # turns up appears on a later launch (see keycast.updates). Skipped on
            # a minimized start, like the splash, since the overlay is hidden.
            # Tradeoff: when a notice *is* pending it replaces the version splash
            # above on the single overlay — acceptable, the actionable upgrade
            # line is the more useful thing to show, and it only fires when an
            # update actually exists (the common, no-update case keeps the splash).
            notify_pending_update(
                notify=self.display_window.show_text,
                current=__version__,
                enabled=self.settings.check_for_updates,
            )
        # Start the display window last to avoid race conditions.
        self.display_window.start(start_minimized=start_minimized)

    def _startup_permission_precheck(self, system: str) -> bool | None:
        """Return pre-start permission state when the platform can report it."""
        if system != "Darwin":
            return None
        return self._macos_permission_precheck()

    @staticmethod
    def _macos_permission_precheck() -> bool | None:
        """Return a best-effort macOS input permission precheck.

        Returns:
            ``True`` when both checks are explicitly granted, ``False`` when at
            least one check is explicitly denied, and ``None`` when the host
            APIs are unavailable or cannot be read.
        """
        logger = logging.getLogger(__name__)
        try:
            app_services = ctypes.CDLL(_MACOS_APP_SERVICES_FRAMEWORK)
        except OSError as exc:
            logger.debug(
                format_event(
                    "macos_permission_precheck_unavailable",
                    reason=type(exc).__name__,
                    detail=str(exc),
                )
            )
            return None
        except (TypeError, ValueError, ctypes.ArgumentError) as exc:
            logger.debug(
                format_event(
                    "macos_permission_precheck_unavailable",
                    reason=type(exc).__name__,
                    detail=str(exc),
                )
            )
            return None

        ax_check = getattr(app_services, "AXIsProcessTrusted", None)
        if ax_check is not None:
            ax_check.restype = ctypes.c_bool
            ax_check.argtypes = []
            try:
                accessibility_ok: bool | None = ax_check()
            except (OSError, TypeError, ValueError, ctypes.ArgumentError) as exc:
                logger.debug(
                    format_event(
                        "macos_accessibility_precheck_failed",
                        reason=type(exc).__name__,
                    )
                )
                accessibility_ok = None
        else:
            accessibility_ok = None

        input_check = getattr(app_services, "CGPreflightListenEventAccess", None)
        if input_check is not None:
            input_check.restype = ctypes.c_bool
            input_check.argtypes = []
            try:
                input_ok: bool | None = input_check()
            except (OSError, TypeError, ValueError, ctypes.ArgumentError) as exc:
                logger.debug(
                    format_event(
                        "macos_input_monitoring_precheck_failed",
                        reason=type(exc).__name__,
                    )
                )
                input_ok = None
        else:
            input_ok = None

        if accessibility_ok is False or input_ok is False:
            return False
        if accessibility_ok is True and input_ok is True:
            return True
        return None

    def _startup_input_statuses(
        self,
        started: dict[str, bool],
        precheck: bool | None,
        system: str,
    ) -> dict[str, _InputSourceStatus]:
        """Derive startup status per input source."""
        return {
            "keyboard": self._resolve_source_status(
                enabled=self.key_listener.settings.enabled,
                started=started["keyboard"],
                precheck=precheck,
                system=system,
            ),
            "mouse": self._resolve_source_status(
                enabled=self.mouse_listener.settings.enabled,
                started=started["mouse"],
                precheck=precheck,
                system=system,
            ),
        }

    def _resolve_source_status(
        self,
        *,
        enabled: bool,
        started: bool,
        precheck: bool | None,
        system: str,
    ) -> _InputSourceStatus:
        """Resolve one source into a user-facing startup status."""
        if not self.settings.auto_start or not enabled:
            return _InputSourceStatus.DISABLED
        if started:
            return _InputSourceStatus.ACTIVE
        if system == "Darwin":
            if precheck is False:
                return _InputSourceStatus.NO_ACCESS
            return _InputSourceStatus.UNKNOWN
        if system == "Windows":
            return _InputSourceStatus.NO_ACCESS
        return _InputSourceStatus.UNKNOWN

    @staticmethod
    def _format_startup_status_line(statuses: dict[str, _InputSourceStatus]) -> str:
        """Build the one-line startup status for the overlay."""
        labels = {
            _InputSourceStatus.ACTIVE: "OK",
            _InputSourceStatus.DISABLED: "Off",
            _InputSourceStatus.NO_ACCESS: "Permission needed",
            _InputSourceStatus.UNKNOWN: "Unknown",
        }
        keyboard = labels[statuses["keyboard"]]
        mouse = labels[statuses["mouse"]]
        return f"Input status — Keyboard: {keyboard}, Mouse: {mouse}"

    def _log_startup_input_status(
        self,
        *,
        statuses: dict[str, _InputSourceStatus],
        precheck: bool | None,
    ) -> None:
        """Log startup input status as a structured event."""
        if precheck is True:
            precheck_text = "granted"
        elif precheck is False:
            precheck_text = "denied"
        else:
            precheck_text = "unknown"
        self.logger.info(
            format_event(
                "startup_input_status",
                keyboard=statuses["keyboard"],
                mouse=statuses["mouse"],
                precheck=precheck_text,
            )
        )

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
