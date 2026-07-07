"""Tests for the display module."""

import threading
from collections.abc import Callable, Iterator
from unittest.mock import Mock, call, patch

import pytest
from pydantic_extra_types.color import Color

from keycast.display import _MAX_RETAINED_EVENTS, DisplayWindow
from keycast.settings import DisplaySettings


@pytest.fixture
def mock_tk() -> Iterator[tuple[Mock, Mock]]:
    """Patch tkinter so DisplayWindow can be built without a real window.

    Yields:
        A tuple of (mock root, mock label instance).
    """
    # _apply_window_icon needs a real Tk root (PhotoImage) and, on macOS, sets the
    # process dock icon via AppKit — both unwanted side effects here. It is an
    # independent concern covered directly by TestWindowIcon, so stub it out.
    with (
        patch("tkinter.Tk") as tk_cls,
        patch("tkinter.Label") as label_cls,
        patch.object(DisplayWindow, "_apply_window_icon"),
    ):
        mock_root = Mock()
        tk_cls.return_value = mock_root
        mock_root.winfo_screenwidth.return_value = 1920
        mock_root.winfo_screenheight.return_value = 1080
        mock_root.winfo_exists.return_value = True

        mock_label = Mock()
        label_cls.return_value = mock_label

        yield mock_root, mock_label


class TestDisplayWindow:
    """Test cases for DisplayWindow class."""

    def test_init_default_parameters(self, mock_tk: tuple[Mock, Mock]) -> None:
        """Test initialization with default parameters."""
        window = DisplayWindow(DisplaySettings())

        assert window.settings.width == 400
        assert window.settings.height == 100
        assert window.settings.x_position == "center"
        assert window.settings.y_position == 50
        assert str(window.settings.background_color) == "black"
        assert str(window.settings.text_color) == "white"
        assert window.settings.font_family == "Arial"
        assert window.settings.font_size == 16
        assert window.settings.font_weight == "bold"
        assert window.settings.alpha == 0.8
        assert window.settings.always_on_top is True
        assert window.settings.fade_duration_ms == 2000
        assert window.settings.max_events == 5

    def test_init_custom_parameters(self, mock_tk: tuple[Mock, Mock]) -> None:
        """Test initialization with custom parameters."""
        settings = DisplaySettings(
            width=600,
            height=200,
            x_position=100,
            y_position=150,
            background_color=Color("#FF0000"),
            text_color=Color("#00FF00"),
            font_family="Courier",
            font_size=20,
            font_weight="normal",
            alpha=0.5,
            always_on_top=False,
            fade_duration_ms=3000,
            max_events=10,
        )
        window = DisplayWindow(settings)

        assert window.settings.width == 600
        assert window.settings.height == 200
        assert window.settings.x_position == 100
        assert window.settings.y_position == 150
        assert str(window.settings.background_color) == "red"
        assert str(window.settings.text_color) == "lime"
        assert window.settings.font_family == "Courier"
        assert window.settings.font_size == 20
        assert window.settings.font_weight == "normal"
        assert window.settings.alpha == 0.5
        assert window.settings.always_on_top is False
        assert window.settings.fade_duration_ms == 3000
        assert window.settings.max_events == 10

    def test_show_text_records_event(self, mock_tk: tuple[Mock, Mock]) -> None:
        """show_text appends an (text, timestamp) event."""
        window = DisplayWindow(DisplaySettings())
        window.show_text("A")

        assert len(window.events) == 1
        assert window.events[0][0] == "A"
        assert isinstance(window.events[0][1], float)

    def test_show_text_marshals_update_onto_main_loop(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """show_text must hand the UI update to the Tk loop via after(0, ...).

        show_text runs on a pynput listener thread, so the update must not touch
        widgets directly.
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.after.reset_mock()  # ignore the after() from the fade timer

        window.show_text("A")

        mock_root.after.assert_called_once_with(0, window._update_display)

    def test_show_text_without_root_is_noop(self, mock_tk: tuple[Mock, Mock]) -> None:
        """show_text after teardown drops the event instead of crashing."""
        window = DisplayWindow(DisplaySettings())
        window.root = None

        window.show_text("A")

        assert window.events == []

    def test_update_display_limits_to_max_events(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """_update_display renders only the last max_events lines on the label."""
        _, mock_label = mock_tk
        window = DisplayWindow(DisplaySettings(max_events=3))

        for i in range(5):
            window.show_text(f"Key{i}")
        window._update_display()

        # All events are retained; only the most recent three are displayed.
        assert len(window.events) == 5
        mock_label.config.assert_called_with(text="Key2\nKey3\nKey4")

    def test_update_display_without_label_is_noop(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """_update_display returns early if the label is gone (post-teardown)."""
        window = DisplayWindow(DisplaySettings())
        window.label = None

        window._update_display()  # must not raise

    def test_update_display_logs_on_render_error(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """A render failure (e.g. TclError mid-teardown) is logged, not raised.

        Mirrors the _fade_timer guard: a stale scheduled tick racing teardown
        must not crash the Tk main loop.
        """
        _, mock_label = mock_tk
        window = DisplayWindow(DisplaySettings())
        window._error_throttler = Mock()
        mock_label.config.side_effect = RuntimeError("boom")
        window.events = [("A", 0.0)]

        window._update_display()  # must not raise

        # The render error is routed through the throttler (which dedupes the
        # flood of identical tracebacks a persistent fault would otherwise emit),
        # tagged with the event name and the caught exception.
        window._error_throttler.log.assert_called_once()
        event, exc = window._error_throttler.log.call_args.args
        assert event == "update_display_error"
        assert isinstance(exc, RuntimeError)

    def test_x_position_center_centers_horizontally(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """An "center" x_position centers the window on the screen width.

        With screen width 1920 and window width 400, the left edge is
        (1920 - 400) // 2 == 760; y uses the configured offset.
        """
        mock_root, _ = mock_tk
        DisplayWindow(DisplaySettings(width=400, x_position="center", y_position=50))

        mock_root.geometry.assert_called_once_with("400x100+760+50")

    def test_explicit_x_position_is_used_verbatim(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """An explicit x_position bypasses centering."""
        mock_root, _ = mock_tk
        DisplayWindow(DisplaySettings(width=400, x_position=100, y_position=50))

        mock_root.geometry.assert_called_once_with("400x100+100+50")

    def test_x_position_is_clamped_on_screen(self, mock_tk: tuple[Mock, Mock]) -> None:
        """An in-bounds-but-off-screen x is clamped to the visible right edge.

        x_position=5000 passes the schema (le=20000) but is past the 1920-wide
        screen; with a 400-wide window the furthest visible left edge is
        1920 - 400 == 1520.
        """
        mock_root, _ = mock_tk
        DisplayWindow(DisplaySettings(width=400, x_position=5000, y_position=50))

        mock_root.geometry.assert_called_once_with("400x100+1520+50")

    def test_y_position_is_clamped_on_screen(self, mock_tk: tuple[Mock, Mock]) -> None:
        """An in-bounds-but-off-screen y is clamped to the visible bottom edge.

        y_position=5000 passes the schema but is past the 1080-tall screen;
        with a 100-tall window the furthest visible top edge is 1080 - 100 == 980.
        """
        mock_root, _ = mock_tk
        DisplayWindow(DisplaySettings(width=400, x_position=100, y_position=5000))

        mock_root.geometry.assert_called_once_with("400x100+100+980")

    def test_fade_timer_evicts_stale_events(self, mock_tk: tuple[Mock, Mock]) -> None:
        """_fade_timer drops events older than fade_duration_ms, keeps fresh ones."""
        window = DisplayWindow(DisplaySettings(fade_duration_ms=2000))

        with patch("keycast.display.time.monotonic", return_value=100.0):
            # 100.0 - 97.0 = 3s old -> stale (>2000ms); 99.5 -> 0.5s -> fresh.
            # Timestamps are monotonic (not wall-clock) so fade timing survives
            # system-clock jumps.
            window.events = [("old", 97.0), ("fresh", 99.5)]
            window._fade_timer()

        assert [text for text, _ in window.events] == ["fresh"]

    def test_fade_timer_reschedules_itself(self, mock_tk: tuple[Mock, Mock]) -> None:
        """_fade_timer schedules the next tick in 100ms."""
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.after.reset_mock()

        window._fade_timer()

        mock_root.after.assert_called_once_with(100, window._fade_timer)

    def test_fade_timer_stops_when_window_gone(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """_fade_timer does not reschedule once the window no longer exists."""
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.winfo_exists.return_value = False
        mock_root.after.reset_mock()

        window._fade_timer()

        mock_root.after.assert_not_called()

    def test_fade_timer_logs_and_reschedules_on_error(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """A failure mid-tick is logged but must not kill the fade loop.

        If updating the display raises, the error is logged and the next tick is
        still scheduled in the ``finally`` block, so events cannot freeze on
        screen forever.
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window._error_throttler = Mock()
        mock_root.after.reset_mock()

        with patch.object(window, "_update_display", side_effect=RuntimeError("boom")):
            window._fade_timer()  # must not raise

        # The error is throttled (not logged raw on every 100ms tick) and the
        # next tick is still scheduled in the finally block.
        window._error_throttler.log.assert_called_once()
        event, exc = window._error_throttler.log.call_args.args
        assert event == "fade_timer_error"
        assert isinstance(exc, RuntimeError)
        mock_root.after.assert_called_once_with(100, window._fade_timer)

    def test_fade_timer_skips_reschedule_if_torn_down_mid_tick(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """If stop() nulls root during a tick, the finally must not reschedule.

        Rescheduling on a torn-down window would raise TclError, so the finally
        re-checks root before calling after().
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.after.reset_mock()

        def tear_down() -> None:
            window.root = None

        with patch.object(window, "_update_display", side_effect=tear_down):
            window._fade_timer()

        mock_root.after.assert_not_called()

    def test_stop_destroys_window(self, mock_tk: tuple[Mock, Mock]) -> None:
        """stop quits, destroys, and clears the root reference."""
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        window.stop()

        mock_root.quit.assert_called_once()
        mock_root.destroy.assert_called_once()
        assert window.root is None

    def test_stop_without_root(self, mock_tk: tuple[Mock, Mock]) -> None:
        """stop is a no-op when the window is already gone."""
        window = DisplayWindow(DisplaySettings())
        window.root = None

        window.stop()  # should not raise

    def test_stop_tolerates_already_destroyed_app(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """stop must not re-raise when the OS already destroyed the Tcl app.

        A native window close / app-quit makes mainloop() return with the
        application already torn down, so root.destroy() raises
        ``TclError: application has been destroyed``. stop() treats that as a
        successful teardown (the window is gone, which is the goal) rather than
        letting it bubble up as a component_stop_error in Keycast.stop().
        """
        import tkinter as tk

        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.destroy.side_effect = tk.TclError(
            'cannot invoke "destroy" command: application has been destroyed'
        )

        window.stop()  # must not raise

        assert window.root is None

    def test_request_stop_schedules_quit(self, mock_tk: tuple[Mock, Mock]) -> None:
        """request_stop asks the loop to quit without destroying in place."""
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.after.reset_mock()

        window.request_stop()

        mock_root.after.assert_called_once_with(0, mock_root.quit)
        # The window itself is left intact for stop() to tear down later.
        mock_root.destroy.assert_not_called()
        assert window.root is mock_root

    def test_request_stop_without_root(self, mock_tk: tuple[Mock, Mock]) -> None:
        """request_stop is safe after teardown."""
        window = DisplayWindow(DisplaySettings())
        window.root = None

        window.request_stop()  # should not raise

    def test_request_stop_is_reentrant_under_held_lock(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """request_stop must not deadlock when the caller already holds the lock.

        A SIGINT/SIGTERM is delivered on the main thread *between bytecodes*, so
        the signal handler can invoke request_stop while the main thread is
        already inside a locked section (``_fade_timer``/``_update_display``).
        ``_lock`` is an ``RLock`` so the re-entry succeeds; a plain ``Lock`` would
        self-deadlock and hang shutdown. Driven from a worker thread with a join
        timeout so a regression surfaces as a failed assertion, not a hung suite.
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.after.reset_mock()

        done = threading.Event()

        def hold_then_request() -> None:
            # Hold the lock to emulate being mid locked-section, then re-enter via
            # request_stop on the same thread (as the signal handler would).
            with window._lock:
                window.request_stop()
            done.set()

        worker = threading.Thread(target=hold_then_request)
        worker.start()
        worker.join(timeout=5)

        assert done.is_set(), "request_stop deadlocked while the lock was held"
        mock_root.after.assert_called_once_with(0, mock_root.quit)

    def test_fade_evicts_expired_events_but_keeps_recent(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """A fade pass drops events older than fade_duration_ms, keeps recent ones.

        The concurrent long-fade test never actually evicts (nothing ages out),
        so the eviction branch of ``_fade_timer``'s list rebuild is only pinned
        here. Time is controlled so the result is deterministic: the older event
        ages past the window while the just-appended one survives.
        """
        window = DisplayWindow(DisplaySettings(fade_duration_ms=500))
        with patch("keycast.display.time.monotonic") as now:
            now.return_value = 1000.0
            window.show_text("old")
            now.return_value = 1000.4  # 400ms later: still inside the 500ms window
            window.show_text("recent")
            now.return_value = 1000.6  # 600ms after "old", 200ms after "recent"
            window._fade_timer()

        assert [text for text, _ in window.events] == ["recent"]

    def test_events_list_is_capped_by_runaway_backstop(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """show_text caps ``events`` so a wedged fade tick cannot grow it forever.

        The fade tick normally keeps the list tiny; this pins the independent
        backstop that bounds it even if the tick never runs. Only the oldest rows
        are dropped -- the most recent (all that max_events renders) survive.
        """
        window = DisplayWindow(DisplaySettings(fade_duration_ms=10000))

        for i in range(_MAX_RETAINED_EVENTS + 5):
            window.show_text(f"event-{i}")

        assert len(window.events) == _MAX_RETAINED_EVENTS
        # Oldest five were dropped; the newest event is retained.
        assert window.events[0][0] == "event-5"
        assert window.events[-1][0] == f"event-{_MAX_RETAINED_EVENTS + 4}"

    def test_update_display_noop_when_window_destroyed_with_live_label(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """A stale update tick after the Tcl window is gone is a silent no-op.

        This is the exact race the method guards: a ``root.after(0,
        _update_display)`` enqueued by ``show_text`` fires after the underlying
        Tcl window was destroyed (``winfo_exists()`` is False) while ``root`` and
        ``label`` are both still set. It must return without touching the label,
        otherwise the stale ``label.config`` would raise ``TclError``.
        """
        mock_root, mock_label = mock_tk
        window = DisplayWindow(DisplaySettings())
        window.events.append(("X", 0.0))
        mock_label.config.reset_mock()
        mock_root.winfo_exists.return_value = False

        window._update_display()

        mock_label.config.assert_not_called()

    def test_start_runs_mainloop(self, mock_tk: tuple[Mock, Mock]) -> None:
        """start enters the tkinter main loop."""
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        window.start()

        mock_root.mainloop.assert_called_once()

    def test_start_without_root(self, mock_tk: tuple[Mock, Mock]) -> None:
        """start is a no-op when the window is already gone."""
        window = DisplayWindow(DisplaySettings())
        window.root = None

        window.start()  # should not raise

    def test_concurrent_show_text_and_fade_is_consistent(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """The lock protects ``events`` against concurrent listener threads.

        This pins the ``_lock`` that guards the ``events`` list: ``show_text``
        (pynput threads) appends while ``_fade_timer`` rebuilds the list, and
        driving both concurrently must not raise (e.g. ``list`` mutated during
        iteration) nor lose an appended event. Note ``root.after`` is mocked, so
        the Tk *marshalling* path (``after(0, _update_display)``) is deliberately
        not exercised here — only the shared-state locking is.
        """
        window = DisplayWindow(DisplaySettings(fade_duration_ms=10000))
        threads_count = 8
        per_thread = 200

        def producer(tag: int) -> None:
            for i in range(per_thread):
                window.show_text(f"{tag}-{i}")

        def fader(stop: threading.Event) -> None:
            while not stop.is_set():
                window._fade_timer()

        stop = threading.Event()
        fade_thread = threading.Thread(target=fader, args=(stop,))
        fade_thread.start()
        producers = [
            threading.Thread(target=producer, args=(t,)) for t in range(threads_count)
        ]
        for thread in producers:
            thread.start()
        for thread in producers:
            thread.join()
        stop.set()
        fade_thread.join()

        # fade_duration is long enough that nothing was evicted: every event
        # appended by every producer is present, with no lost or duplicated rows.
        assert len(window.events) == threads_count * per_thread

    def test_show_text_defers_update_off_the_producer_thread(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """The widget update never runs inline on the calling (pynput) thread.

        This is the architecture's central invariant: ``show_text`` runs on a
        pynput listener thread, but tkinter widgets may only be touched from the
        thread that owns the main loop. Unlike
        ``test_show_text_marshals_update_onto_main_loop`` (which only checks the
        ``after`` argument shape against a Mock), this drives ``show_text`` from a
        worker thread with a real recording ``after`` and asserts ``_update_display``
        does *not* execute on that producer thread — it runs only when the queued
        callback is later drained on the main thread. A regression that called
        ``_update_display()`` directly from ``show_text`` would fail here while
        passing the lock-only and arg-shape tests.
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        # Real recording after(): store the callback instead of executing it,
        # exactly as the Tk loop would defer it to its own thread.
        queued: list[tuple[int, object]] = []
        mock_root.after.side_effect = lambda delay, cb: queued.append((delay, cb))

        update_threads: list[threading.Thread] = []
        real_update = window._update_display

        def recording_update() -> None:
            update_threads.append(threading.current_thread())
            real_update()

        window._update_display = recording_update  # type: ignore[method-assign]

        producer: dict[str, threading.Thread] = {}

        def produce() -> None:
            producer["thread"] = threading.current_thread()
            window.show_text("A")

        worker = threading.Thread(target=produce)
        worker.start()
        worker.join()

        # Deferred, not run inline: nothing executed on the producer thread, and
        # the update was enqueued with delay 0.
        assert update_threads == []
        assert queued and queued[0][0] == 0

        # Draining the queue (as the main loop would) is the only place the
        # widget update actually runs — and not on the producer thread.
        _, callback = queued[0]
        callback()  # type: ignore[operator]
        assert update_threads == [threading.current_thread()]
        assert update_threads[0] is not producer["thread"]

    def test_show_text_drops_event_when_loop_gone(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """show_text tolerates root.after failing after the loop has died.

        An in-flight pynput callback can call show_text in the gap between
        mainloop() returning (after a native window close) and stop() nulling
        root: root is still set, but root.after raises RuntimeError ("main
        thread is not in main loop") or TclError if the app is destroyed. This
        must be swallowed so the listener does not surface it as a
        key_sink_error/mouse_sink_error traceback.
        """
        import tkinter as tk

        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window._error_throttler = Mock()

        for exc in (
            RuntimeError("main thread is not in main loop"),
            tk.TclError("application has been destroyed"),
        ):
            mock_root.after.side_effect = exc
            window.show_text("A")  # must not raise

        # Routed through the throttler (not a silent debug line): a *persistent*
        # cross-thread after() failure — e.g. a non-thread-enabled Tcl build where
        # the overlay would otherwise show nothing all session — escalates to a
        # visible warning. Both attempts are reported with the event + caught exc.
        assert window._error_throttler.log.call_count == 2
        event, exc = window._error_throttler.log.call_args.args
        assert event == "show_text_dropped_loop_gone"
        assert isinstance(exc, (RuntimeError, tk.TclError))

    def test_request_stop_logs_warning_when_after_fails(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """A failed stop-schedule is visible at warning, not a silent debug line.

        Unlike per-event show_text drops, request_stop fires once per session, and
        a genuine failure (e.g. a live but non-thread-enabled Tcl loop rejecting a
        cross-thread after) means the app ignores shutdown — which must be visible
        without the user raising verbosity on a process that won't quit. It must
        also not let the exception escape the signal handler / caller.
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window.logger = Mock()
        mock_root.after.side_effect = RuntimeError("main thread is not in main loop")

        window.request_stop()  # must not raise

        window.logger.warning.assert_called_once()
        assert "request_stop_loop_gone" in window.logger.warning.call_args.args[0]

    def test_request_stop_racing_stop_is_safe(self, mock_tk: tuple[Mock, Mock]) -> None:
        """request_stop (any thread) racing stop (main thread) must not crash.

        The ``_lock`` around the ``root`` null-check in both methods exists so a
        non-main-thread ``request_stop`` cannot read ``root``, then have ``stop``
        null and tear it down before ``request_stop`` enqueues
        ``root.after(quit)``. Without the lock, ``self.root`` can flip to ``None``
        between the check and the ``after`` call, raising mid-method. Driving both
        concurrently many times must leave no escaped exception and a cleared
        root.
        """
        mock_root, _ = mock_tk
        errors: list[BaseException] = []

        for _ in range(200):
            window = DisplayWindow(DisplaySettings())

            def request_stop(win: DisplayWindow = window) -> None:
                try:
                    win.request_stop()
                except Exception as exc:  # noqa: BLE001 - recorded, asserted below
                    errors.append(exc)

            def stop(win: DisplayWindow = window) -> None:
                try:
                    win.stop()
                except Exception as exc:  # noqa: BLE001 - recorded, asserted below
                    errors.append(exc)

            requester = threading.Thread(target=request_stop)
            stopper = threading.Thread(target=stop)
            requester.start()
            stopper.start()
            requester.join()
            stopper.join()

            assert window.root is None

        assert errors == []

    def test_fade_timer_returns_early_when_root_already_none(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """A tick that fires after teardown (root already None) is a harmless no-op.

        This is the top-of-function guard, distinct from the ``finally`` re-check:
        a fade tick scheduled before ``stop`` ran can still fire afterwards, and
        must neither raise nor reschedule itself onto a dead window.
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window.root = None
        mock_root.after.reset_mock()

        window._fade_timer()  # must not raise

        mock_root.after.assert_not_called()


class TestDraggable:
    """Drag-to-move bindings for the decoration-less overlay (issue #5)."""

    def test_draggable_binds_press_and_motion_on_root_and_label(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """With draggable on, both surfaces get press + motion handlers.

        The label fills the window, so most clicks land on it, not the root;
        binding both means a drag works wherever the cursor grabs.
        """
        mock_root, mock_label = mock_tk
        DisplayWindow(DisplaySettings(draggable=True))

        for widget in (mock_root, mock_label):
            bound = {c.args[0] for c in widget.bind.call_args_list}
            assert "<Button-1>" in bound
            assert "<B1-Motion>" in bound

    def test_not_draggable_binds_nothing(self, mock_tk: tuple[Mock, Mock]) -> None:
        mock_root, mock_label = mock_tk
        DisplayWindow(DisplaySettings(draggable=False))

        mock_root.bind.assert_not_called()
        mock_label.bind.assert_not_called()

    def test_window_close_routes_through_request_stop(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """A WM close is wired to request_stop, not an in-place destroy.

        Routing WM_DELETE_WINDOW to request_stop keeps every close path on the
        graceful two-phase shutdown (schedule root.quit, let mainloop return,
        tear down in stop()) instead of letting the window manager destroy the
        Tcl app underneath a running loop.
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        mock_root.protocol.assert_called_once_with(
            "WM_DELETE_WINDOW", window.request_stop
        )

    def test_drag_motion_moves_window_to_follow_cursor(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """The window origin tracks the pointer minus the in-window grab offset.

        Pointer at (500, 400), grabbed 10px right and 5px down from the window's
        top-left, so the new origin is (490, 395).
        """
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings(draggable=True))
        mock_root.winfo_pointerx.return_value = 500
        mock_root.winfo_pointery.return_value = 400

        press = Mock()
        press.x, press.y = 10, 5
        window._on_drag_start(press)
        window._on_drag_motion(Mock())

        # The last geometry() call is the drag move (the first set the initial pos).
        mock_root.geometry.assert_called_with("+490+395")

    def test_drag_motion_after_teardown_is_noop(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        window = DisplayWindow(DisplaySettings(draggable=True))
        window.root = None

        window._on_drag_motion(Mock())  # must not raise


class TestStartMinimized:
    """Dormant-until-first-input behavior for a minimized start (issue #3)."""

    def test_start_minimized_withdraws_before_loop(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        window.start(start_minimized=True)

        mock_root.withdraw.assert_called_once()
        mock_root.mainloop.assert_called_once()
        assert window._minimized is True

    def test_start_not_minimized_does_not_withdraw(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        window.start()

        mock_root.withdraw.assert_not_called()
        assert window._minimized is False

    def test_show_text_schedules_restore_only_when_minimized(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window._minimized = True
        mock_root.after.reset_mock()

        window.show_text("A")

        scheduled = mock_root.after.call_args_list
        assert call(0, window._restore_from_minimized) in scheduled
        assert call(0, window._update_display) in scheduled

    def test_show_text_no_restore_when_not_minimized(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        mock_root.after.reset_mock()

        window.show_text("A")

        # Only the display update is scheduled; no restore on the normal path.
        mock_root.after.assert_called_once_with(0, window._update_display)

    def test_restore_deiconifies_and_clears_flag(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window._minimized = True

        window._restore_from_minimized()

        mock_root.deiconify.assert_called_once()
        assert window._minimized is False

    def test_restore_after_teardown_is_noop(self, mock_tk: tuple[Mock, Mock]) -> None:
        window = DisplayWindow(DisplaySettings())
        window._minimized = True
        window.root = None

        window._restore_from_minimized()  # must not raise

    def test_restore_logs_on_deiconify_error(self, mock_tk: tuple[Mock, Mock]) -> None:
        """A deiconify failure is throttled, not raised (mirrors the other Tk callbacks)."""
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window._error_throttler = Mock()
        window._minimized = True
        mock_root.deiconify.side_effect = RuntimeError("boom")

        window._restore_from_minimized()  # must not raise

        window._error_throttler.log.assert_called_once()
        event, exc = window._error_throttler.log.call_args.args
        assert event == "restore_minimized_error"
        assert isinstance(exc, RuntimeError)


class TestForceFrameless:
    """macOS borderless re-assertion: Tk 9 ignores overrideredirect at creation."""

    def test_delegates_to_reassert_on_macos(self, mock_tk: tuple[Mock, Mock]) -> None:
        """On macOS the platform gate passes through to the toggle."""
        window = DisplayWindow(DisplaySettings())
        with (
            patch("keycast.display.sys.platform", "darwin"),
            patch.object(window, "_reassert_overrideredirect") as reassert,
        ):
            window._force_frameless()

        reassert.assert_called_once_with()

    def test_skips_reassert_off_macos(self, mock_tk: tuple[Mock, Mock]) -> None:
        """Other platforms strip the frame on the first call, so the toggle is skipped."""
        window = DisplayWindow(DisplaySettings())
        with (
            patch("keycast.display.sys.platform", "win32"),
            patch.object(window, "_reassert_overrideredirect") as reassert,
        ):
            window._force_frameless()

        reassert.assert_not_called()

    def test_reassert_toggles_overrideredirect_off_then_on(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        """The off/on flip after a layout pass is what makes Aqua re-evaluate the frame."""
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        # _setup_window already called overrideredirect once; isolate the toggle.
        mock_root.overrideredirect.reset_mock()
        mock_root.update_idletasks.reset_mock()

        window._reassert_overrideredirect()

        mock_root.update_idletasks.assert_called_once()
        assert mock_root.overrideredirect.call_args_list == [
            call(boolean=False),
            call(boolean=True),
        ]

    def test_reassert_without_root_is_noop(self, mock_tk: tuple[Mock, Mock]) -> None:
        """After teardown nulls root the toggle is skipped, never raised."""
        window = DisplayWindow(DisplaySettings())
        window.root = None

        window._reassert_overrideredirect()  # must not raise

    def test_reassert_swallows_tclerror(self, mock_tk: tuple[Mock, Mock]) -> None:
        """A TclError (e.g. window mid-teardown) is logged and skipped, not raised."""
        import tkinter as tk

        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())
        window.logger = Mock()
        mock_root.update_idletasks.side_effect = tk.TclError("mid-teardown")

        window._reassert_overrideredirect()  # must not raise

        window.logger.debug.assert_called()


class TestWindowIcon:
    """Tests for the runtime taskbar/dock icon set by _apply_window_icon.

    These build their own window with ``_apply_window_icon`` stubbed only during
    construction, then invoke the real method under controlled patches — the
    shared ``mock_tk`` fixture stubs the method out entirely.
    """

    def _build_window(self) -> tuple[DisplayWindow, Mock]:
        """Build a DisplayWindow with tkinter mocked but the icon method live.

        Returns:
            The window and its mock root.
        """
        with (
            patch("tkinter.Tk") as tk_cls,
            patch("tkinter.Label"),
            patch.object(DisplayWindow, "_apply_window_icon"),
        ):
            root = Mock()
            tk_cls.return_value = root
            root.winfo_screenwidth.return_value = 1920
            root.winfo_screenheight.return_value = 1080
            window = DisplayWindow(DisplaySettings())
        window.root = root
        return window, root

    def test_sets_taskbar_icon_via_iconphoto(self) -> None:
        """The shipped PNG is loaded and handed to iconphoto, and kept referenced."""
        window, root = self._build_window()
        photo = Mock()
        with (
            patch("tkinter.PhotoImage", return_value=photo) as photo_cls,
            patch("keycast.display.sys.platform", "linux"),
        ):
            window._apply_window_icon()

        photo_cls.assert_called_once()
        root.iconphoto.assert_called_once_with(True, photo)
        # Held on the instance so Tk's GC doesn't blank the icon.
        assert window._icon_image is photo

    def test_missing_asset_is_noop(self) -> None:
        """A missing icon asset is skipped, never raised, and sets no icon."""
        window, root = self._build_window()
        with (
            patch("keycast.display.Path.exists", return_value=False),
            patch("tkinter.PhotoImage") as photo_cls,
        ):
            window._apply_window_icon()

        photo_cls.assert_not_called()
        root.iconphoto.assert_not_called()

    def test_tk_error_is_swallowed(self) -> None:
        """A PhotoImage/iconphoto failure is logged and skipped, not raised."""
        import tkinter as tk

        window, root = self._build_window()
        with (
            patch("tkinter.PhotoImage", side_effect=tk.TclError("bad image")),
            patch("keycast.display.sys.platform", "linux"),
        ):
            window._apply_window_icon()  # must not raise

        root.iconphoto.assert_not_called()
        assert window._icon_image is None

    def test_macos_sets_dock_icon_via_appkit(self) -> None:
        """On macOS the dock icon is set through AppKit's NSApplication."""
        window, _ = self._build_window()
        ns_image = Mock()
        fake_appkit = Mock()
        loader = fake_appkit.NSImage.alloc.return_value.initWithContentsOfFile_
        loader.return_value = ns_image
        with (
            patch("keycast.display.sys.platform", "darwin"),
            patch("tkinter.PhotoImage"),
            patch.dict("sys.modules", {"AppKit": fake_appkit}),
        ):
            window._apply_window_icon()

        app = fake_appkit.NSApplication.sharedApplication.return_value
        app.setApplicationIconImage_.assert_called_once_with(ns_image)

    def test_macos_unreadable_image_is_skipped(self) -> None:
        """If AppKit can't decode the file, no icon is set and nothing raises."""
        window, _ = self._build_window()
        fake_appkit = Mock()
        fake_appkit.NSImage.alloc.return_value.initWithContentsOfFile_.return_value = (
            None
        )
        with (
            patch("keycast.display.sys.platform", "darwin"),
            patch("tkinter.PhotoImage"),
            patch.dict("sys.modules", {"AppKit": fake_appkit}),
        ):
            window._apply_window_icon()  # must not raise

        app = fake_appkit.NSApplication.sharedApplication.return_value
        app.setApplicationIconImage_.assert_not_called()

    def test_macos_appkit_error_is_swallowed(self) -> None:
        """An AppKit failure is logged and skipped, not raised."""
        window, _ = self._build_window()
        window.logger = Mock()
        with (
            patch("keycast.display.sys.platform", "darwin"),
            patch("tkinter.PhotoImage"),
            patch(
                "keycast.display.importlib.import_module",
                side_effect=ImportError("no AppKit"),
            ),
        ):
            window._apply_window_icon()  # must not raise

        window.logger.debug.assert_called()

    def test_non_darwin_skips_appkit(self) -> None:
        """Off macOS the AppKit dock path is not touched at all."""
        window, _ = self._build_window()
        fake_appkit = Mock()
        with (
            patch("keycast.display.sys.platform", "win32"),
            patch("tkinter.PhotoImage"),
            patch.dict("sys.modules", {"AppKit": fake_appkit}),
        ):
            window._apply_window_icon()

        fake_appkit.NSApplication.sharedApplication.assert_not_called()


class TestSchedulingDoesNotHoldLock:
    """Regression: cross-thread ``after`` must not run while holding ``_lock``.

    On macOS a cross-thread ``root.after`` blocks until the main loop services
    the Tcl queue; if it were called while holding ``_lock`` (which the main
    loop's ``_fade_timer``/``_update_display`` also take), the main thread would
    block on the lock while the listener thread blocks on the main thread —
    deadlock, freezing the overlay. These tests model the main loop grabbing
    ``_lock`` from another thread *during* the ``after`` call and assert it is
    free (which would only be true if scheduling happens outside the lock).
    """

    def _assert_lock_free_during_after(
        self, window: DisplayWindow, mock_root: Mock, action: Callable[[], None]
    ) -> None:
        results: list[bool] = []

        def after_impl(_delay: int, _cb: object) -> None:
            # Another thread models the Tk main loop taking _lock. A plain Lock
            # would deadlock across threads; _lock is reentrant only on the SAME
            # thread, so a separate thread genuinely blocks if the lock is held.
            def grab() -> None:
                got = window._lock.acquire(timeout=1.0)
                results.append(got)
                if got:
                    window._lock.release()

            thread = threading.Thread(target=grab)
            thread.start()
            thread.join(timeout=2.0)

        mock_root.after.reset_mock()  # drop the fade-timer after() from __init__
        mock_root.after.side_effect = after_impl

        action()  # triggers root.after -> after_impl, which probes the lock

        assert results, "after() was never called, so the lock was not exercised"
        assert all(results), "show_* held _lock while scheduling after() (deadlock)"

    def test_show_text_schedules_after_outside_lock(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        self._assert_lock_free_during_after(
            window, mock_root, lambda: window.show_text("A")
        )

    def test_request_stop_schedules_after_outside_lock(
        self, mock_tk: tuple[Mock, Mock]
    ) -> None:
        # request_stop applies the same capture-root-then-schedule pattern and is
        # called from the signal handler / pynput threads; it must also release
        # _lock before the cross-thread after(), or Ctrl+C would deadlock at quit.
        mock_root, _ = mock_tk
        window = DisplayWindow(DisplaySettings())

        self._assert_lock_free_during_after(window, mock_root, window.request_stop)
