"""Tkinter display window for showing events."""

import importlib
import logging
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from keycast.logging_setup import _ErrorThrottler

if TYPE_CHECKING:
    # tkinter is imported lazily in _setup_window so the module stays importable
    # on a Python built without the _tkinter C-extension (e.g. some Homebrew
    # builds) or in headless tooling like slotscheck. The runtime tk.* calls
    # (tk.Tk(), tk.Label()) use that lazy import; the tk.* names appearing
    # elsewhere are only in type hints — string forward-refs and local-variable
    # annotations, neither of which is evaluated at import — so this
    # TYPE_CHECKING-only import is enough to satisfy them.
    import tkinter as tk

    from keycast.settings import DisplaySettings


class DisplayWindow:
    """A transparent overlay window that displays events."""

    def __init__(self, settings: DisplaySettings) -> None:
        """Initialize the display window.

        Args:
            settings: Display settings
        """
        self.settings = settings

        self.logger = logging.getLogger(__name__)
        self.root: tk.Tk | None = None
        self.label: tk.Label | None = None
        # Holds the runtime icon's PhotoImage. Tk's garbage collector blanks an
        # icon whose PhotoImage is no longer referenced, so it must outlive the
        # _apply_window_icon call that sets it (see that method).
        self._icon_image: tk.PhotoImage | None = None
        self.events: list[tuple[str, float]] = []  # (event_text, timestamp)
        # Guards ``events`` and ``root``: ``show_text`` runs on pynput listener
        # threads while ``_fade_timer``/``stop`` run on the Tk main thread.
        #
        # Reentrant (``RLock``) on purpose: a SIGINT/SIGTERM is delivered on the
        # main thread *between bytecodes*, so the handler can fire while the main
        # thread is already inside a locked section (``_fade_timer`` /
        # ``_update_display``). The handler calls ``request_stop``, which takes
        # this lock again on the same thread; a plain ``Lock`` would self-deadlock
        # and hang shutdown. ``request_stop`` only reads ``root`` and schedules a
        # callback (it never mutates ``events``), so re-entering an interrupted
        # locked section cannot corrupt the state the outer frame is building.
        self._lock = threading.RLock()
        # Throttles repeated errors from the Tk callbacks (``_fade_timer`` and
        # ``_update_display``), which fire continuously: the fade tick every
        # 100ms and the update on every event. Without this, a persistent
        # rendering fault (e.g. a font tkinter rejects on every ``label.config``)
        # would write a full traceback many times a second. Both callbacks run
        # on the Tk main loop, so a single, lock-free throttler is safe here.
        self._error_throttler = _ErrorThrottler(self.logger)
        # Set when started with start_minimized: the overlay is withdrawn until
        # the first captured event re-shows it (see _restore_from_minimized).
        # Read on pynput threads (show_text) and written on the Tk main loop, so
        # access is guarded by _lock.
        self._minimized = False
        # Cursor offset within the window at drag start, used by the optional
        # drag-to-move handlers so the window follows the cursor without jumping.
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._setup_window()

    def _setup_window(self) -> None:
        """Set up the tkinter window with proper styling."""
        import tkinter as tk  # noqa: PLC0415  # lazy: see the import note at module top

        self.root = tk.Tk()
        self.root.title("keycast")
        self._apply_window_icon()

        # Configure window properties
        self.root.configure(bg=str(self.settings.background_color))
        self.root.overrideredirect(boolean=True)  # Remove window decorations
        # Lock the size independently of decorations. overrideredirect is meant to
        # strip the frame (and with it the resize grips), but on macOS Aqua Tk 9
        # it is unreliable, leaving the window resizable; resizable(False, False)
        # disables resize/zoom regardless of whether the frame is actually gone.
        self.root.resizable(width=False, height=False)
        self.root.attributes("-alpha", self.settings.alpha)

        if self.settings.always_on_top:
            self.root.attributes("-topmost", True)  # noqa: FBT003

        # Position window. The settings bounds on x/y are only a generous sanity
        # check (they reject absurd values but not merely off-screen ones), so
        # clamp into the actual screen here: an explicit position past the screen
        # edge would otherwise render the overlay invisibly off-screen.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        if self.settings.x_position == "center":
            x = (screen_width - self.settings.width) // 2
        else:
            x = min(
                self.settings.x_position, max(0, screen_width - self.settings.width)
            )
        y = min(self.settings.y_position, max(0, screen_height - self.settings.height))

        self.root.geometry(f"{self.settings.width}x{self.settings.height}+{x}+{y}")

        # Create label for displaying events
        self.label = tk.Label(
            self.root,
            text="",
            bg=str(self.settings.background_color),
            fg=str(self.settings.text_color),
            font=(
                self.settings.font_family,
                self.settings.font_size,
                self.settings.font_weight,
            ),
            wraplength=self.settings.width - 20,
            justify="left",
        )
        self.label.pack(expand=True, fill="both", padx=10, pady=10)

        if self.settings.draggable:
            # Pass the just-created widgets so the helper takes non-optional
            # types: both are guaranteed set here, so no in-loop None check (and
            # its never-taken branch) is needed.
            self._enable_dragging(self.root, self.label)

        # Route a window-manager close through the graceful request_stop path
        # (schedule root.quit, let mainloop return, then tear down in stop())
        # instead of letting the WM destroy the Tcl app in place — which makes
        # mainloop return with the app already gone and turns the orderly
        # two-phase shutdown into a teardown race. overrideredirect(True) means
        # most desktop WMs deliver no close button so this rarely fires, but
        # some environments (and a future decorated mode) still send
        # WM_DELETE_WINDOW; registering it costs nothing and keeps every close
        # path uniform.
        self.root.protocol("WM_DELETE_WINDOW", self.request_stop)

        # On macOS Aqua (Tk 9) the overrideredirect(True) above is frequently
        # ignored when set before the window is first mapped, so the overlay comes
        # up with a title bar and a draggable resize frame. Re-assert it here.
        self._force_frameless()

        # Start fade timer
        self._fade_timer()

    def _force_frameless(self) -> None:
        """Re-assert borderless state on macOS, where Tk 9 ignores it at creation.

        ``overrideredirect(True)`` in :meth:`_setup_window` is supposed to strip
        the title bar and frame, but Aqua Tk 9.0 honours it only once the window
        has been mapped. Force the window through a layout pass and toggle the
        flag off/on so Aqua reprocesses it and actually drops the decorations.

        macOS-only and best-effort: other platforms remove the frame correctly on
        the first call, and a transient ``TclError`` (e.g. window mid-teardown)
        must never stop the overlay from starting — it is logged and skipped.
        """
        import tkinter as tk  # noqa: PLC0415  # lazy: see the import note at module top

        if sys.platform != "darwin" or self.root is None:
            return

        try:
            # update_idletasks runs the pending geometry/map work so the toggle
            # below acts on a realized window; the off/on flip is what makes Aqua
            # re-evaluate the decorations.
            self.root.update_idletasks()
            self.root.overrideredirect(boolean=False)
            self.root.overrideredirect(boolean=True)
        except tk.TclError as exc:
            self.logger.debug("could not force frameless window: %s", exc)

    def _apply_window_icon(self) -> None:
        """Brand the taskbar / dock icon when keycast runs from source.

        The packaged ``.app``/``.exe`` get their icon from PyInstaller
        (``keycast.icns`` / ``keycast.ico``); a plain ``uv run keycast`` has no
        bundle, so the icon is set here at runtime from the PNG shipped inside the
        package (``assets/keycast.png``, generated by ``packaging/make_icons.py``).

        Two mechanisms, because no single API covers every platform:

        - ``iconphoto`` sets the Windows/Linux taskbar icon. Tk's ``PhotoImage``
          reads PNG (not the build-time .ico/.icns), and the image must outlive
          this call or Tk's GC blanks it — hence ``self._icon_image``.
        - On macOS the overlay has no title bar (``overrideredirect``) and Aqua Tk
          ignores ``iconphoto`` for the dock, so the dock icon is set through
          AppKit (importable because pynput pulls in pyobjc on macOS).

        Best-effort: a missing asset or any backend error is logged and skipped —
        a default icon must never stop the overlay from starting.
        """
        import tkinter as tk  # noqa: PLC0415  # lazy: see the import note at module top

        if self.root is None:  # pragma: no cover — _setup_window always sets it first
            return

        icon_path = Path(__file__).parent / "assets" / "keycast.png"
        if not icon_path.exists():
            self.logger.debug("window icon asset missing, using default: %s", icon_path)
            return

        try:
            self._icon_image = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self._icon_image)  # noqa: FBT003
        except (tk.TclError, RuntimeError) as exc:
            # RuntimeError covers "no default root" if Tk isn't fully up yet;
            # TclError covers a malformed/unreadable image. Either way, skip.
            self.logger.debug("could not set Tk window icon: %s", exc)

        if sys.platform == "darwin":
            try:
                # Load AppKit dynamically: pyobjc generates its members at import
                # time and ships no stubs, so its symbols are invisible to static
                # analysis. ``import_module`` keeps mypy/pyright happy; ty still
                # resolves the "AppKit" literal, so the two member lookups carry a
                # narrow ty ignore (kept on short lines so formatting can't move
                # the pragma off them).
                appkit = importlib.import_module("AppKit")
                ns_image = appkit.NSImage  # ty: ignore[unresolved-attribute]
                ns_app = appkit.NSApplication  # ty: ignore[unresolved-attribute]
                image = ns_image.alloc().initWithContentsOfFile_(str(icon_path))
                if image is not None:
                    ns_app.sharedApplication().setApplicationIconImage_(image)
            except Exception as exc:  # noqa: BLE001 — pyobjc raises many unrelated types
                self.logger.debug("could not set macOS dock icon: %s", exc)

    def _enable_dragging(self, root: "tk.Tk", label: "tk.Label") -> None:
        """Bind press-and-drag handlers so the overlay can be moved by mouse.

        ``overrideredirect(True)`` removes the title bar, so the window manager
        has nothing to grab; bind directly on both the root and the label (the
        label fills the window, so most clicks land on it). The cursor offset
        within the window is captured on press so the window tracks the pointer
        smoothly instead of snapping its top-left corner under the cursor.

        Args:
            root: The overlay's top-level window.
            label: The label widget filling the window.
        """
        for widget in (root, label):
            widget.bind("<Button-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)

    def _on_drag_start(self, event: "tk.Event[tk.Misc]") -> None:
        """Record where inside the window the drag began.

        Args:
            event: The button-press event; ``x``/``y`` are window-relative.
        """
        self._drag_offset_x = event.x
        self._drag_offset_y = event.y

    def _on_drag_motion(self, event: "tk.Event[tk.Misc]") -> None:
        """Move the window to follow the cursor during a drag.

        Args:
            event: The motion event (unused; absolute pointer position is read
                from the root so the math is independent of which widget the
                cursor is currently over).
        """
        if not self.root:
            return
        x = self.root.winfo_pointerx() - self._drag_offset_x
        y = self.root.winfo_pointery() - self._drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _fade_timer(self) -> None:
        """Timer callback for fading out old events.

        Runs on the Tk main loop and reschedules itself. The body is guarded so a
        transient failure (e.g. a ``TclError`` while a widget is mid-teardown, or
        an error rendering text) is *logged* rather than silently killing the
        fade loop. The reschedule lives in ``finally`` so one bad tick cannot
        freeze stale events on screen forever.
        """
        if not self.root or not self.root.winfo_exists():
            return

        try:
            current_time = time.time()
            # Remove events older than fade_duration_ms
            with self._lock:
                self.events = [
                    (event_text, timestamp)
                    for event_text, timestamp in self.events
                    if (current_time - timestamp) * 1000
                    < self.settings.fade_duration_ms
                ]
            self._update_display()
        except Exception as exc:
            self._error_throttler.log("fade_timer_error", exc)
        finally:
            # Schedule next fade check in 100ms. The re-check is defensive: the
            # loop is ended by root.quit (scheduled by request_stop), and once
            # mainloop returns no further after() callbacks fire, so a torn-down
            # root is never actually observed here today. stop() (which nulls
            # root) also runs on this same main thread, only after mainloop has
            # returned, so it cannot interleave with this callback — this is
            # ordering within the loop, not a cross-thread race. The guard keeps a
            # torn-down root from being rescheduled (which would raise TclError)
            # should the teardown lifecycle ever change.
            if self.root:
                self.root.after(100, self._fade_timer)

    def _update_display(self) -> None:
        """Update the display with current events.

        Always runs on the Tk main loop, never on a pynput thread. Reached two
        ways: directly from ``_fade_timer`` (already on the main loop), and via
        ``root.after`` enqueued by ``show_text`` (which itself runs on a pynput
        thread; ``after`` marshals this callback onto the main loop). That is why
        the ``label.config`` below is safe to call unguarded for thread affinity.

        In the ``after`` case a stale tick may run after teardown has begun, so
        guard against a torn-down root/label and wrap the body the same way
        ``_fade_timer`` does: a stale scheduled tick racing ``stop`` would
        otherwise raise an unhandled ``TclError`` on the main loop. The
        label-config call is cheap, so logging-and-continuing here costs nothing
        in the normal path.
        """
        if not self.root or not self.root.winfo_exists() or not self.label:
            return

        try:
            # Limit to max_events
            with self._lock:
                recent_events = self.events[-self.settings.max_events :]

            # Format events for display
            event_texts = [event_text for event_text, _ in recent_events]
            display_text = "\n".join(event_texts)

            self.label.config(text=display_text)
        except Exception as exc:
            self._error_throttler.log("update_display_error", exc)

    def show_text(self, text: str) -> None:
        """Display a text.

        Args:
            text: The text to display
        """
        import tkinter as tk  # noqa: PLC0415  # lazy: see the import note at module top

        # Marshal the update onto the Tk main loop; show_text runs on a pynput
        # listener thread, and tkinter widgets may only be touched from the
        # thread that owns the main loop. The ``after`` call stays inside the
        # lock so ``stop`` cannot null and ``destroy`` ``root`` between the check
        # and the enqueue (which would raise TclError); ``after`` only schedules,
        # so holding the lock briefly here does not block the main loop.
        with self._lock:
            if not self.root:
                # Normal during shutdown (stop() nulled root); drop the event.
                # Logged at debug so an *unexpected* null — events vanishing
                # while the app is still meant to be running — is diagnosable
                # without adding noise at the default INFO level.
                self.logger.debug("show_text_dropped_no_root")
                return
            self.events.append((text, time.time()))
            try:
                # A minimized start hides the overlay until the first event;
                # re-show it now. Scheduled on the main loop (not done inline)
                # because Tk widgets may only be touched from the thread owning
                # the main loop — the same reason _update_display is marshalled
                # via after.
                if self._minimized:
                    self.root.after(0, self._restore_from_minimized)
                self.root.after(0, self._update_display)
            except RuntimeError, tk.TclError:
                # The ``root is not None`` check above is not enough: the Tk loop
                # can already be dead while ``root`` still exists, in the gap
                # between mainloop() returning and stop() nulling root. This
                # happens when the OS tears the app down out from under us (a
                # native window close / app-quit, which is *not* the
                # request_stop -> root.quit path the rest of teardown assumes),
                # while an in-flight pynput callback is still calling show_text.
                # ``after`` then raises RuntimeError ("main thread is not in main
                # loop") or, if the app is already destroyed, TclError. The race
                # is inherent to external teardown and untimeable, so tolerate it
                # here — exactly as _fade_timer/_update_display tolerate a stale
                # tick — and drop the event at debug level rather than letting it
                # surface as a key_sink_error/mouse_sink_error traceback from the
                # listener's sink-call handler.
                self.logger.debug("show_text_dropped_loop_gone")

    def _restore_from_minimized(self) -> None:
        """Re-show the overlay after a minimized start, on the Tk main loop.

        Scheduled by :meth:`show_text` the first time an event is captured. Like
        the other Tk callbacks it tolerates a torn-down window (a stale tick can
        race teardown) and routes a failure through the throttler rather than
        crashing the loop. Idempotent: several events may queue this before the
        flag clears, but ``deiconify`` on a shown window is harmless.
        """
        if not self.root or not self.root.winfo_exists():
            return
        try:
            self.root.deiconify()
        except Exception as exc:
            # _minimized stays set (cleared only after a successful deiconify), so
            # a persistent failure leaves the overlay hidden for the whole
            # session. Name that user-visible consequence in the log so the
            # throttled summary is not just an opaque recurring traceback.
            self._error_throttler.log(
                "restore_minimized_error", exc, consequence="overlay_remains_hidden"
            )
            return
        with self._lock:
            self._minimized = False

    def start(self, *, start_minimized: bool = False) -> None:
        """Start the tkinter main loop.

        Args:
            start_minimized: If true, withdraw the overlay before entering the
                loop so it starts hidden; the first captured event re-shows it
                via :meth:`_restore_from_minimized`.
        """
        if self.root:
            if start_minimized:
                with self._lock:
                    self._minimized = True
                self.root.withdraw()
                self.logger.info("display_starting_minimized")
            self.logger.info("display_mainloop_starting")
            self.root.mainloop()

    def request_stop(self) -> None:
        """Ask the main loop to exit, safe to call from any thread.

        Schedules ``root.quit`` on the Tk event loop so ``mainloop`` returns
        control to the caller of :meth:`start`. The actual window teardown
        happens later in :meth:`stop`, once we are no longer nested inside the
        (possibly signal-interrupted) main loop, where calling ``destroy``
        directly would raise Tcl errors.

        The ``after`` call stays inside the lock for the same reason as
        :meth:`show_text`: this method is contracted to be callable from any
        thread, so a non-main-thread caller could otherwise race the main-thread
        :meth:`stop` and let it null and destroy ``root`` between the check and
        the enqueue (which would raise TclError). ``after`` only schedules, so
        holding the lock briefly does not block the main loop. The lock is an
        ``RLock`` so a signal handler invoking this method while the main thread
        already holds the lock (mid ``_fade_timer``/``_update_display``) re-enters
        instead of self-deadlocking — see the lock's definition in ``__init__``.
        """
        with self._lock:
            if self.root:
                self.root.after(0, self.root.quit)

    def stop(self) -> None:
        """Destroy the window.

        Must run on the main thread after ``mainloop`` has returned. The normal
        loop-exit path is :meth:`request_stop` (which schedules ``root.quit``);
        the ``quit()`` here is belt-and-suspenders for a direct or abnormal
        ``stop()`` call where ``request_stop`` never ran, and is a harmless no-op
        once ``mainloop`` has already returned. ``destroy()`` is what actually
        tears the window down.

        ``quit``/``destroy`` are wrapped because the OS can tear the Tcl
        application down before we get here: a native window close / app-quit
        makes ``mainloop`` return with the app *already destroyed*, so
        ``destroy()`` raises ``TclError: application has been destroyed``. That
        is the desired end state, so treat it as a successful teardown rather
        than re-raising into ``Keycast.stop``'s component-stop handler (which
        would log a spurious ``component_stop_error`` traceback on every native
        close).
        """
        import tkinter as tk  # noqa: PLC0415  # lazy: see the import note at module top

        with self._lock:
            root = self.root
            self.root = None
        if root:
            try:
                root.quit()
                root.destroy()
            except tk.TclError:
                self.logger.debug("display_already_destroyed")
            else:
                self.logger.info("display_mainloop_stopped")
