"""Main entry point for the keycast application."""

import ctypes
import logging
import platform
import signal
import sys
from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

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
    """Startup status for one input source.

    Each member carries both its stable ``value`` (used verbatim as the
    structured-log token, e.g. ``keyboard=active``) and its user-facing
    ``label`` (shown on the overlay). Co-locating the two means adding a state
    forces its label to be supplied here, rather than in a separate mapping that
    could silently fall out of sync.
    """

    ACTIVE = ("active", "OK")
    DISABLED = ("disabled", "Off")
    NO_ACCESS = ("no_access", "Permission needed")
    FAILED = ("failed", "Not capturing")
    UNKNOWN = ("unknown", "Unknown")

    label: str

    def __new__(cls, value: str, label: str) -> "_InputSourceStatus":
        """Build a StrEnum member that also carries an overlay ``label``."""
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member


class _PermissionPrecheck(StrEnum):
    """Tri-state outcome of a platform input-permission precheck.

    ``UNKNOWN`` is a first-class value, not the absence of one: it means the
    platform cannot report permission state (every non-macOS platform) or the
    macOS query could not be read. Callers compare against members explicitly
    rather than leaning on truthiness, so "denied" and "indeterminate" never
    collapse together. The value doubles as the structured-log token.
    """

    GRANTED = "granted"
    DENIED = "denied"
    UNKNOWN = "unknown"


class _ListenersStarted(NamedTuple):
    """Whether each input listener is actively capturing after startup."""

    keyboard: bool
    mouse: bool


class _StartupStatuses(NamedTuple):
    """Resolved startup status per input source."""

    keyboard: _InputSourceStatus
    mouse: _InputSourceStatus


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
        # resolve_preset layers the selected preset ("modes") over the loaded
        # config; "custom" (the default) is a no-op. Applied here so every
        # component below sees the resolved settings, while the on-disk config
        # keeps the user's raw values (see Settings.resolve_preset).
        self.settings = Settings.create_settings_file().resolve_preset()
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
        # Set by signal_handler to the received signum; logged in run() after the
        # main loop returns. Not logged in the handler itself -- see signal_handler.
        self._pending_signal: int | None = None
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
        if self.settings.auto_start:
            # Attempt both regardless of either's outcome (degrade, don't crash).
            # Mouse is started before keyboard; keep that order so the wiring
            # test that pins listener start ordering stays meaningful.
            mouse_started = self._start_listener("mouse", self.mouse_listener)
            keyboard_started = self._start_listener("keyboard", self.key_listener)
            started = _ListenersStarted(keyboard=keyboard_started, mouse=mouse_started)
        else:
            started = _ListenersStarted(keyboard=False, mouse=False)
            self.logger.info(format_event("listeners_autostart_disabled"))
        any_source_active = any(started)
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

    def _startup_permission_precheck(self, system: str) -> _PermissionPrecheck:
        """Return the platform's current input-permission state without prompting.

        Only macOS can report this (via :meth:`_macos_permission_precheck`);
        every other platform returns ``UNKNOWN``. This runs *after* the listener
        start attempts — the query never prompts, so ordering is safe, and if
        the first listener start triggered the OS permission dialog we read the
        post-grant state rather than a stale pre-grant one.

        The macOS query is best-effort: it must never abort startup, so any
        unexpected error degrades to ``UNKNOWN`` (logged with a traceback,
        because reaching here means a real bug rather than a missing symbol,
        which :meth:`_macos_permission_precheck` already handles).
        """
        if system != "Darwin":
            return _PermissionPrecheck.UNKNOWN
        try:
            return self._macos_permission_precheck()
        except Exception:
            self.logger.exception(format_event("macos_permission_precheck_error"))
            return _PermissionPrecheck.UNKNOWN

    @staticmethod
    def _macos_permission_precheck() -> _PermissionPrecheck:
        """Return a best-effort macOS input-permission precheck.

        Queries the two System Settings > Privacy & Security panes this kind of
        tool needs, using APIs that report state without triggering a prompt:
        Accessibility via ``AXIsProcessTrusted`` and Input Monitoring via
        ``CGPreflightListenEventAccess``.

        Returns:
            ``GRANTED`` when both panes are explicitly granted, ``DENIED`` when
            at least one is explicitly denied, and ``UNKNOWN`` when the host
            APIs are unavailable or cannot be read (including a partial read,
            which must never be reported as granted).
        """
        logger = logging.getLogger(__name__)
        try:
            app_services = ctypes.CDLL(_MACOS_APP_SERVICES_FRAMEWORK)
        except (OSError, TypeError, ValueError, ctypes.ArgumentError) as exc:
            # Failing to load ApplicationServices on macOS is a genuine anomaly
            # (broken install / exotic sandbox), so surface it above DEBUG.
            logger.warning(
                format_event(
                    "macos_permission_precheck_unavailable",
                    reason=type(exc).__name__,
                    detail=str(exc),
                )
            )
            return _PermissionPrecheck.UNKNOWN

        accessibility_ok = Keycast._read_macos_permission(
            app_services, "AXIsProcessTrusted"
        )
        input_ok = Keycast._read_macos_permission(
            app_services, "CGPreflightListenEventAccess"
        )

        if accessibility_ok is False or input_ok is False:
            return _PermissionPrecheck.DENIED
        if accessibility_ok is True and input_ok is True:
            return _PermissionPrecheck.GRANTED
        return _PermissionPrecheck.UNKNOWN

    @staticmethod
    def _read_macos_permission(app_services: ctypes.CDLL, symbol: str) -> bool | None:
        """Read one macOS permission symbol, or ``None`` when it can't be read.

        Both the missing-symbol and call-raising paths log at INFO (not DEBUG):
        they only ever fire on macOS, where these symbols are expected to exist,
        so either firing means something is wrong on the host and would
        otherwise be invisible at the default log level.
        """
        logger = logging.getLogger(__name__)
        check = getattr(app_services, symbol, None)
        if check is None:
            logger.info(
                format_event("macos_permission_precheck_symbol_missing", symbol=symbol)
            )
            return None
        check.restype = ctypes.c_bool
        check.argtypes = []
        try:
            return bool(check())
        except (OSError, TypeError, ValueError, ctypes.ArgumentError) as exc:
            logger.info(
                format_event(
                    "macos_permission_precheck_read_failed",
                    symbol=symbol,
                    reason=type(exc).__name__,
                    detail=str(exc),
                )
            )
            return None

    def _startup_input_statuses(
        self,
        started: _ListenersStarted,
        precheck: _PermissionPrecheck,
        system: str,
    ) -> _StartupStatuses:
        """Derive startup status per input source."""
        return _StartupStatuses(
            keyboard=self._resolve_source_status(
                enabled=self.key_listener.settings.enabled,
                started=started.keyboard,
                precheck=precheck,
                system=system,
            ),
            mouse=self._resolve_source_status(
                enabled=self.mouse_listener.settings.enabled,
                started=started.mouse,
                precheck=precheck,
                system=system,
            ),
        )

    def _resolve_source_status(
        self,
        *,
        enabled: bool,
        started: bool,
        precheck: _PermissionPrecheck,
        system: str,
    ) -> _InputSourceStatus:
        """Resolve one source into a user-facing startup status.

        The overlay must never lie that capture works when it doesn't. On macOS
        that is the whole point of the precheck: ``Listener.start()`` there is a
        thread start that succeeds even when Accessibility / Input Monitoring is
        denied — the tap fails *asynchronously* on the listener thread and never
        raises back to us. So an explicit ``DENIED`` precheck overrides an
        apparently-successful start; the observed ``started`` flag is trusted
        only in the absence of that contradiction.

        When a source is enabled but not capturing and the cause is not a known
        permission denial, the honest status is ``FAILED`` ("not capturing"),
        not ``UNKNOWN`` — we know capture failed, only the cause is undetermined.
        ``UNKNOWN`` is reserved for a platform we don't recognize at all.
        """
        if not self.settings.auto_start or not enabled:
            return _InputSourceStatus.DISABLED
        # Observed-vs-predicted: a macOS denial is believed over a "successful"
        # start, because that start does not prove the event tap was installed.
        if system == "Darwin" and precheck is _PermissionPrecheck.DENIED:
            return _InputSourceStatus.NO_ACCESS
        if started:
            return _InputSourceStatus.ACTIVE
        # started is False here: the listener genuinely failed to start.
        if system in ("Darwin", "Windows", "Linux"):
            return _InputSourceStatus.FAILED
        return _InputSourceStatus.UNKNOWN

    @staticmethod
    def _format_startup_status_line(statuses: _StartupStatuses) -> str:
        """Build the one-line startup status for the overlay."""
        return (
            f"Input status — Keyboard: {statuses.keyboard.label}, "
            f"Mouse: {statuses.mouse.label}"
        )

    def _log_startup_input_status(
        self,
        *,
        statuses: _StartupStatuses,
        precheck: _PermissionPrecheck,
    ) -> None:
        """Log startup input status as a structured event.

        Fires unconditionally on every launch (regardless of
        ``show_startup_status`` or a minimized start), so the machine-readable
        record can never be configured away with the overlay line.
        """
        self.logger.info(
            format_event(
                "startup_input_status",
                keyboard=statuses.keyboard,
                mouse=statuses.mouse,
                precheck=precheck,
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

        Idempotent: safe to call more than once. In practice only ``run``'s
        ``finally`` block calls it -- the signal handler merely *requests* the
        loop to exit (see :meth:`signal_handler`), so the two-phase shutdown does
        the teardown here on the main thread once ``mainloop`` has returned. The
        guard keeps a future direct caller from double-stopping.
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

    def signal_handler(self, signum: int, _frame: types.FrameType | None) -> None:
        """Stop the application in response to SIGINT/SIGTERM.

        The handler runs on the main thread, which is blocked inside the
        tkinter main loop. It only *requests* the loop to exit (it does not
        tear the window down in place — destroying a window while still nested
        in ``mainloop`` raises Tcl errors). Once ``mainloop`` returns, control
        unwinds to ``run`` where the ``finally`` block performs the actual
        shutdown via :meth:`stop`.

        Does no logging here: ``logging`` takes a non-reentrant lock, and a
        signal can interrupt the main thread mid-emit (a ``root.after`` callback
        that logs), so logging from the handler could deadlock. Instead it records
        the signum and :meth:`run` logs it after the loop returns.
        """
        self._pending_signal = signum
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
            # Deferred from signal_handler (which must not log; see there). Logged
            # here on the main thread after mainloop has returned, where the
            # logging lock is safe to take.
            if self._pending_signal is not None:
                self.logger.info(
                    format_event(
                        "shutdown_signal_received", signum=self._pending_signal
                    )
                )
            self.stop()
