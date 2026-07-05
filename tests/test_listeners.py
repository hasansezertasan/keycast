"""Tests for the listeners module."""

import platform
from unittest.mock import Mock, patch

import pytest
from pynput import keyboard, mouse

from keycast.listeners import (
    _MODIFIER_STALE_SECONDS,
    KeyListener,
    MouseListener,
    _ErrorThrottler,
)
from keycast.settings import KeyboardSettings, MouseSettings


class TestPynputKeyNamingContract:
    """Pin the pynput key-name facts the label logic depends on.

    Comments in ``listeners.py`` and ``settings.py`` assert specific pynput
    naming behavior (e.g. ``Key.ctrl_l`` aliases ``Key.ctrl`` on macOS/Linux,
    the Super key is always named ``cmd``). Nothing else guards these
    external-dependency claims, so a pynput upgrade could silently break label
    resolution while every doc-contract test still passes. These assertions fail
    loudly if the upstream names the code keys off ever change.
    """

    def test_stable_special_key_names(self) -> None:
        # These names are identical on every platform and feed _default_key_mappings.
        assert keyboard.Key.space.name == "space"
        assert keyboard.Key.enter.name == "enter"
        assert keyboard.Key.ctrl_r.name == "ctrl_r"

    def test_super_key_is_named_cmd_on_all_platforms(self) -> None:
        # settings.py / listeners.py rely on the Super/Windows key reporting
        # "cmd" (never "win") everywhere.
        assert keyboard.Key.cmd.name == "cmd"
        assert keyboard.Key.cmd_r.name == "cmd_r"

    def test_left_ctrl_aliasing_matches_platform(self) -> None:
        # On macOS/Linux Key.ctrl_l aliases Key.ctrl and reports "ctrl"; only
        # Windows reports a distinct "ctrl_l". _default_key_mappings covers both
        # names, but this pins the platform-specific fact the comments claim.
        if platform.system() == "Windows":
            assert keyboard.Key.ctrl_l.name == "ctrl_l"
        else:
            assert keyboard.Key.ctrl_l.name == "ctrl"


class TestKeyListener:
    """Test cases for KeyListener class."""

    def test_init_default_parameters(self) -> None:
        """Test initialization with default parameters."""
        mock_callback = Mock()
        settings = KeyboardSettings()
        listener = KeyListener(mock_callback, settings)

        assert listener.show_text == mock_callback
        assert listener.settings.show_modifier_keys is True
        assert listener.settings.show_function_keys is True
        assert listener.settings.show_special_keys is True
        # KeyboardSettings ships sensible default mappings (not empty).
        assert listener.settings.key_mappings["space"] == "Space Bar"
        assert "ctrl" in listener.settings.key_mappings
        assert listener.listener is None

    def test_init_custom_parameters(self) -> None:
        """Test initialization with custom parameters."""
        mock_callback = Mock()
        custom_mappings = {"ctrl_l": "Ctrl", "space": "Space"}

        settings = KeyboardSettings(
            show_modifier_keys=False,
            show_function_keys=False,
            show_special_keys=False,
            key_mappings=custom_mappings,
        )
        listener = KeyListener(mock_callback, settings)

        assert listener.show_text == mock_callback
        assert listener.settings.show_modifier_keys is False
        assert listener.settings.show_function_keys is False
        assert listener.settings.show_special_keys is False
        assert listener.settings.key_mappings == custom_mappings

    def test_format_key_character(self) -> None:
        """Test formatting character keys."""
        mock_callback = Mock()
        settings = KeyboardSettings()
        listener = KeyListener(mock_callback, settings)

        # A real character key (the code path requires an actual KeyCode).
        result = listener._format_key(keyboard.KeyCode.from_char("a"))
        assert result == "a"

    def test_format_key_special_keys(self) -> None:
        """Test the capitalize fallback for special keys (no custom mapping)."""
        mock_callback = Mock()
        # Use empty mappings to exercise the default capitalize() fallback.
        settings = KeyboardSettings(key_mappings={})
        listener = KeyListener(mock_callback, settings)

        # Use real pynput Key members so the test reflects actual input objects.
        # The exact ``.name`` for some keys is platform-dependent (e.g. on macOS
        # ``Key.ctrl_l`` aliases ``Key.ctrl``), so assert against the capitalized
        # name rather than a hard-coded string.
        keys = [
            keyboard.Key.space,
            keyboard.Key.enter,
            keyboard.Key.tab,
            keyboard.Key.backspace,
            keyboard.Key.delete,
            keyboard.Key.esc,
            keyboard.Key.ctrl_l,
            keyboard.Key.alt_l,
            keyboard.Key.shift_l,
            keyboard.Key.f1,
            keyboard.Key.f12,
            keyboard.Key.up,
            keyboard.Key.down,
            keyboard.Key.left,
            keyboard.Key.right,
        ]

        for key in keys:
            assert listener._format_key(key) == key.name.capitalize()

    def test_format_key_custom_mappings(self) -> None:
        """Test formatting with custom key mappings."""
        mock_callback = Mock()
        # Build the mapping from the actual key names so it is platform-agnostic.
        custom_mappings = {
            keyboard.Key.ctrl_l.name: "Control",
            keyboard.Key.space.name: "Spacebar",
        }
        settings = KeyboardSettings(key_mappings=custom_mappings)
        listener = KeyListener(mock_callback, settings)

        assert listener._format_key(keyboard.Key.ctrl_l) == "Control"
        assert listener._format_key(keyboard.Key.space) == "Spacebar"

    def test_format_key_default_modifier_mappings(self) -> None:
        """The default mappings label left/right modifiers across platforms.

        Both the bare/"_l" and "_r" variants are covered, so the labels resolve
        regardless of how pynput names the left modifier on the host platform.
        """
        listener = KeyListener(Mock(), KeyboardSettings())

        assert listener._format_key(keyboard.Key.ctrl_l) == "Control Left"
        assert listener._format_key(keyboard.Key.ctrl_r) == "Control Right"
        assert listener._format_key(keyboard.Key.shift_l) == "Shift Left"
        assert listener._format_key(keyboard.Key.shift_r) == "Shift Right"

    def test_format_key_unknown_object_falls_back_to_str(self) -> None:
        """An object that is neither KeyCode nor Key falls back to its repr.

        ``_key_name`` returns None for anything that is not a ``keyboard.Key``,
        so ``_format_key`` cannot classify it and uses ``str(key)``.
        """
        listener = KeyListener(Mock(), KeyboardSettings())

        sentinel = Mock()
        sentinel.__str__ = Mock(return_value="<weird>")  # type: ignore[method-assign]
        assert listener._format_key(sentinel) == "<weird>"

    def test_format_key_keycode_without_char(self) -> None:
        """A dead/virtual KeyCode with no char falls back to its repr."""
        listener = KeyListener(Mock(), KeyboardSettings())

        # vk-only KeyCode (e.g. a media/dead key) has char is None.
        key = keyboard.KeyCode(vk=999)  # type: ignore[arg-type]
        assert key.char is None
        assert listener._format_key(key) == str(key)

    def test_on_press_none_logs_and_skips_callback(self) -> None:
        """pynput can deliver key=None; it is logged and not forwarded."""
        callback = Mock()
        listener = KeyListener(callback, KeyboardSettings())
        listener.logger = Mock()

        listener._on_press(None)

        callback.assert_not_called()
        listener.logger.warning.assert_called_once()

    def test_on_press_swallows_and_logs_sink_error(self) -> None:
        """A failing show_text is caught (listener thread survives) and logged.

        The sink call is a separate failure domain from formatting, so it is
        reported under ``key_sink_error``.
        """
        callback = Mock(side_effect=RuntimeError("boom"))
        listener = KeyListener(callback, KeyboardSettings())
        listener._error_throttler = Mock()

        listener._on_press(keyboard.KeyCode.from_char("a"))  # must not raise

        assert listener._error_throttler.log.call_count == 1
        assert listener._error_throttler.log.call_args[0][0] == "key_sink_error"

    def test_on_press_format_error_is_reported_separately_from_sink(self) -> None:
        """A formatting failure is reported as key_format_error, not a sink error."""
        callback = Mock()
        listener = KeyListener(callback, KeyboardSettings())
        listener._error_throttler = Mock()

        with patch.object(listener, "_format_key", side_effect=RuntimeError("boom")):
            listener._on_press(keyboard.KeyCode.from_char("a"))  # must not raise

        # Formatting failed before the sink was reached, so the sink never ran.
        callback.assert_not_called()
        assert listener._error_throttler.log.call_args[0][0] == "key_format_error"

    def test_on_press_forwards_formatted_character(self) -> None:
        """A shown character key is formatted and forwarded to the sink."""
        callback = Mock()
        listener = KeyListener(callback, KeyboardSettings())

        listener._on_press(keyboard.KeyCode.from_char("a"))

        callback.assert_called_once_with("a")

    def test_on_press_forwards_formatted_modifier_label(self) -> None:
        """A shown modifier is forwarded as its label, not the raw key object."""
        callback = Mock()
        listener = KeyListener(callback, KeyboardSettings())

        listener._on_press(keyboard.Key.ctrl_l)

        callback.assert_called_once_with("Control Left")

    def test_should_show_key_modifier_keys(self) -> None:
        """Test showing modifier keys based on settings."""
        mock_callback = Mock()

        # Test with modifier keys enabled
        settings = KeyboardSettings(show_modifier_keys=True)
        listener = KeyListener(mock_callback, settings)
        assert listener._should_show_key(keyboard.Key.ctrl_l) is True

        # Test with modifier keys disabled
        settings = KeyboardSettings(show_modifier_keys=False)
        listener = KeyListener(mock_callback, settings)
        assert listener._should_show_key(keyboard.Key.ctrl_l) is False

    def test_should_show_key_function_keys(self) -> None:
        """Test showing function keys based on settings."""
        mock_callback = Mock()

        # Test with function keys enabled
        settings = KeyboardSettings(show_function_keys=True)
        listener = KeyListener(mock_callback, settings)
        assert listener._should_show_key(keyboard.Key.f1) is True

        # Test with function keys disabled
        settings = KeyboardSettings(show_function_keys=False)
        listener = KeyListener(mock_callback, settings)
        assert listener._should_show_key(keyboard.Key.f1) is False

    def test_should_show_key_special_keys(self) -> None:
        """Test showing special keys based on settings."""
        mock_callback = Mock()

        # Test with special keys enabled
        settings = KeyboardSettings(show_special_keys=True)
        listener = KeyListener(mock_callback, settings)
        assert listener._should_show_key(keyboard.Key.space) is True

        # Test with special keys disabled
        settings = KeyboardSettings(show_special_keys=False)
        listener = KeyListener(mock_callback, settings)
        assert listener._should_show_key(keyboard.Key.space) is False

    def test_should_show_key_character_keys(self) -> None:
        """Test showing character keys (should always be shown)."""
        mock_callback = Mock()
        settings = KeyboardSettings()
        listener = KeyListener(mock_callback, settings)

        assert listener._should_show_key(keyboard.KeyCode.from_char("a")) is True

    def test_should_show_key_named_key_outside_known_sets(self) -> None:
        """Named keys not in any known set are always shown (default branch).

        Keys like Home/End/PageUp report a stable ``.name`` but are not
        modifiers, function keys, or members of the hardcoded special set, so
        they fall through to ``return True`` and are shown regardless of
        ``show_special_keys``. This pins that passthrough behavior.
        """
        settings = KeyboardSettings(show_special_keys=False)
        listener = KeyListener(Mock(), settings)

        assert listener._should_show_key(keyboard.Key.home) is True
        assert listener._should_show_key(keyboard.Key.end) is True
        assert listener._should_show_key(keyboard.Key.page_up) is True

    def test_should_show_key_f_prefixed_non_function_name_falls_through(self) -> None:
        """A name starting with 'f' but lacking an all-digit suffix is not f-key.

        The function-key guard is ``startswith("f") and key_name[1:].isdigit()``
        (f1..f20). A name like "fn" starts with 'f' but its suffix is not all
        digits, so it must NOT be gated on ``show_function_keys`` — it falls
        through to the default "shown" branch. Pinned via a patched name since no
        standard pynput key reports "fn".
        """
        settings = KeyboardSettings(show_function_keys=False, show_special_keys=False)
        listener = KeyListener(Mock(), settings)

        with patch.object(listener, "_key_name", return_value="fn"):
            # If "fn" were wrongly treated as a function key it would be hidden
            # (show_function_keys=False); the default passthrough shows it.
            assert listener._should_show_key(keyboard.Key.f1) is True

    def test_on_press_skips_filtered_key(self) -> None:
        """A key hidden by settings is not forwarded to the callback.

        Wires the filtering decision to display: with modifiers disabled,
        pressing a modifier must leave ``show_text`` uncalled.
        """
        callback = Mock()
        settings = KeyboardSettings(show_modifier_keys=False)
        listener = KeyListener(callback, settings)

        listener._on_press(keyboard.Key.ctrl_l)

        callback.assert_not_called()

    def test_start_and_stop(self) -> None:
        """Test starting and stopping the listener."""
        mock_callback = Mock()
        settings = KeyboardSettings()
        listener = KeyListener(mock_callback, settings)

        with patch("pynput.keyboard.Listener") as mock_listener_class:
            mock_listener = Mock()
            mock_listener_class.return_value = mock_listener

            listener.start()
            # on_release is registered too (inert unless group_chords is set), so
            # the listener can track held modifiers for chord grouping.
            mock_listener_class.assert_called_once_with(
                on_press=listener._on_press, on_release=listener._on_release
            )
            mock_listener.start.assert_called_once()

            listener.stop()
            mock_listener.stop.assert_called_once()
            assert listener.listener is None

    def test_disabled_listener_does_not_start(self) -> None:
        """When disabled, start() creates no pynput listener."""
        listener = KeyListener(Mock(), KeyboardSettings(enabled=False))

        with patch("pynput.keyboard.Listener") as mock_listener_class:
            listener.start()

        mock_listener_class.assert_not_called()
        assert listener.listener is None

    def test_disabled_listener_stop_is_noop(self) -> None:
        """When disabled, stop() returns early without touching any listener."""
        listener = KeyListener(Mock(), KeyboardSettings(enabled=False))
        listener.listener = Mock()  # should be left untouched

        listener.stop()

        listener.listener.stop.assert_not_called()

    def test_stop_without_started_listener_is_noop(self) -> None:
        """stop() on an enabled-but-never-started listener does nothing."""
        listener = KeyListener(Mock(), KeyboardSettings())
        assert listener.listener is None

        listener.stop()  # must not raise

    def test_start_failure_logs_and_reraises(self) -> None:
        """A failure constructing the pynput listener is logged and propagated."""
        listener = KeyListener(Mock(), KeyboardSettings())
        listener.logger = Mock()

        with (
            patch("pynput.keyboard.Listener", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            listener.start()

        listener.logger.exception.assert_called_once()


class TestMouseListener:
    """Test cases for MouseListener class."""

    def test_init_default_parameters(self) -> None:
        """Test initialization with default parameters."""
        mock_callback = Mock()
        settings = MouseSettings()
        listener = MouseListener(mock_callback, settings)

        assert listener.show_text == mock_callback
        assert listener.settings.show_mouse_clicks is True
        assert listener.settings.show_mouse_position is False
        assert listener.settings.button_names == {}
        assert listener.listener is None

    def test_init_custom_parameters(self) -> None:
        """Test initialization with custom parameters."""
        mock_callback = Mock()
        custom_names = {"Button.left": "Left Button", "Button.right": "Right Button"}

        # show_mouse_position requires show_mouse_clicks (a model validator
        # rejects position-without-clicks), so both are enabled here.
        settings = MouseSettings(
            enabled=False,
            show_mouse_clicks=True,
            show_mouse_position=True,
            button_names=custom_names,
        )
        listener = MouseListener(mock_callback, settings)

        assert listener.show_text == mock_callback
        assert listener.settings.enabled is False
        assert listener.settings.show_mouse_clicks is True
        assert listener.settings.show_mouse_position is True
        assert listener.settings.button_names == custom_names

    def test_format_button_default(self) -> None:
        """Default formatting uses real pynput buttons (real str() contract).

        Using real ``mouse.Button`` members validates the actual
        ``str(button) == "Button.<name>"`` contract that ``_format_button``
        relies on, rather than a hand-mocked ``__str__`` that could drift from
        pynput's real representation. ``Button.unknown`` exercises the generic
        capitalize fallback for any button without an explicit case.
        """
        listener = MouseListener(Mock(), MouseSettings())

        assert listener._format_button(mouse.Button.left) == "Left Click"
        assert listener._format_button(mouse.Button.right) == "Right Click"
        assert listener._format_button(mouse.Button.middle) == "Middle Click"
        # Generic fallback: "Button.unknown" -> "Unknown Click".
        assert listener._format_button(mouse.Button.unknown) == "Unknown Click"

    def test_format_button_custom_names(self) -> None:
        """Custom names are keyed by the real ``str(button)`` value."""
        custom_names = {
            str(mouse.Button.left): "Primary Click",
            str(mouse.Button.right): "Secondary Click",
        }
        settings = MouseSettings(button_names=custom_names)
        listener = MouseListener(Mock(), settings)

        assert listener._format_button(mouse.Button.left) == "Primary Click"

    def test_on_click_pressed(self) -> None:
        """Test handling mouse click when pressed."""
        mock_callback = Mock()
        settings = MouseSettings(show_mouse_clicks=True)
        listener = MouseListener(mock_callback, settings)

        listener._on_click(100, 200, mouse.Button.left, True)
        mock_callback.assert_called_once_with("Left Click")

    def test_on_click_released(self) -> None:
        """Test handling mouse click when released (should not call callback)."""
        mock_callback = Mock()
        settings = MouseSettings(show_mouse_clicks=True)
        listener = MouseListener(mock_callback, settings)

        listener._on_click(100, 200, mouse.Button.left, False)
        mock_callback.assert_not_called()

    def test_on_click_with_position(self) -> None:
        """Test handling mouse click with position enabled."""
        mock_callback = Mock()
        settings = MouseSettings(
            show_mouse_clicks=True,
            show_mouse_position=True,
        )
        listener = MouseListener(mock_callback, settings)

        listener._on_click(150, 250, mouse.Button.right, True)
        mock_callback.assert_called_once_with("Right Click (150, 250)")

    def test_on_click_clicks_disabled(self) -> None:
        """Test handling mouse click when clicks are disabled."""
        mock_callback = Mock()
        settings = MouseSettings(show_mouse_clicks=False)
        listener = MouseListener(mock_callback, settings)

        listener._on_click(100, 200, mouse.Button.left, True)
        mock_callback.assert_not_called()

    def test_on_click_swallows_and_logs_sink_error(self) -> None:
        """A failing show_text is caught (listener thread survives) and logged.

        Reported under ``mouse_sink_error`` to distinguish a broken display sink
        from a button-formatting failure.
        """
        callback = Mock(side_effect=RuntimeError("boom"))
        listener = MouseListener(callback, MouseSettings(show_mouse_clicks=True))
        listener._error_throttler = Mock()

        listener._on_click(100, 200, mouse.Button.left, True)  # must not raise

        assert listener._error_throttler.log.call_count == 1
        assert listener._error_throttler.log.call_args[0][0] == "mouse_sink_error"

    def test_on_click_format_error_is_reported_separately_from_sink(self) -> None:
        """A button-formatting failure is reported as mouse_format_error."""
        callback = Mock()
        listener = MouseListener(callback, MouseSettings(show_mouse_clicks=True))
        listener._error_throttler = Mock()

        with patch.object(listener, "_format_button", side_effect=RuntimeError("boom")):
            listener._on_click(100, 200, mouse.Button.left, True)  # must not raise

        callback.assert_not_called()
        assert listener._error_throttler.log.call_args[0][0] == "mouse_format_error"

    def test_start_and_stop(self) -> None:
        """Test starting and stopping the listener."""
        mock_callback = Mock()
        settings = MouseSettings()
        listener = MouseListener(mock_callback, settings)

        with patch("pynput.mouse.Listener") as mock_listener_class:
            mock_listener = Mock()
            mock_listener_class.return_value = mock_listener

            listener.start()
            mock_listener_class.assert_called_once_with(on_click=listener._on_click)
            mock_listener.start.assert_called_once()

            listener.stop()
            mock_listener.stop.assert_called_once()
            assert listener.listener is None

    def test_disabled_listener_does_not_start(self) -> None:
        """When disabled, start() creates no pynput listener."""
        listener = MouseListener(Mock(), MouseSettings(enabled=False))

        with patch("pynput.mouse.Listener") as mock_listener_class:
            listener.start()

        mock_listener_class.assert_not_called()
        assert listener.listener is None

    def test_disabled_listener_stop_is_noop(self) -> None:
        """When disabled, stop() returns early without touching any listener."""
        listener = MouseListener(Mock(), MouseSettings(enabled=False))
        listener.listener = Mock()  # should be left untouched

        listener.stop()

        listener.listener.stop.assert_not_called()

    def test_stop_without_started_listener_is_noop(self) -> None:
        """stop() on an enabled-but-never-started listener does nothing."""
        listener = MouseListener(Mock(), MouseSettings())
        assert listener.listener is None

        listener.stop()  # must not raise

    def test_start_failure_logs_and_reraises(self) -> None:
        """A failure constructing the pynput listener is logged and propagated."""
        listener = MouseListener(Mock(), MouseSettings())
        listener.logger = Mock()

        with (
            patch("pynput.mouse.Listener", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            listener.start()

        listener.logger.exception.assert_called_once()


class TestErrorThrottler:
    """Test cases for the _ErrorThrottler helper."""

    def _log(self, throttler: _ErrorThrottler, message: str, exc: Exception) -> None:
        """Call throttler.log from within an active except block."""
        try:
            raise exc
        except type(exc) as raised:
            throttler.log(message, raised)

    def test_first_occurrence_logs_traceback(self) -> None:
        """The first time an error is seen it is logged with a traceback.

        The traceback is sourced from the *passed* exception via ``exc_info=exc``
        (logged at ERROR), not from ``logger.exception()`` which would read the
        ambient exception state — see ``test_passed_exception_traceback_used``.
        """
        logger = Mock()
        throttler = _ErrorThrottler(logger)

        self._log(throttler, "context", RuntimeError("boom"))

        logger.error.assert_called_once()
        (message,), kwargs = logger.error.call_args
        assert message == "context"
        assert isinstance(kwargs["exc_info"], RuntimeError)
        logger.exception.assert_not_called()
        logger.warning.assert_not_called()

    def test_passed_exception_traceback_used_outside_except_block(self) -> None:
        """The first-occurrence traceback comes from ``exc``, not ambient state.

        ``logger.exception()`` reads ``sys.exc_info()``, so a caller that passes a
        *stored* exception from outside an ``except`` block would silently log no
        traceback. Using ``exc_info=exc`` makes the passed exception's own
        traceback the source, so it survives being logged outside the handler.
        """
        logger = Mock()
        throttler = _ErrorThrottler(logger)

        # Capture an exception with a traceback, then leave the except block.
        try:
            raise RuntimeError("stored")
        except RuntimeError as raised:
            stored = raised
        assert stored.__traceback__ is not None

        throttler.log("context", stored)  # called with no ambient exception

        logger.error.assert_called_once()
        assert logger.error.call_args.kwargs["exc_info"] is stored

    def test_repeats_are_suppressed_until_summary(self) -> None:
        """Identical repeats are suppressed, then summarized at the interval."""
        logger = Mock()
        throttler = _ErrorThrottler(logger, summary_interval=5)

        for _ in range(5):
            self._log(throttler, "context", RuntimeError("boom"))

        # First call logged the traceback; the 5th emits the periodic summary.
        logger.error.assert_called_once()
        logger.warning.assert_called_once()
        # The summary embeds the repeat count as a structured field.
        assert "repeated=5" in logger.warning.call_args[0][0]

    def test_summary_recurs_each_interval_with_error_key(self) -> None:
        """The summary fires at every interval boundary and carries the key.

        Driving 11 repeats with interval 5 must summarize at the 5th and 10th
        repeat only (not at 6-9 or 11), each line including the stable grouping
        key so a recurring failure stays identifiable.
        """
        logger = Mock()
        throttler = _ErrorThrottler(logger, summary_interval=5)

        for _ in range(11):
            self._log(throttler, "context", RuntimeError("boom"))

        # First occurrence logs a full traceback exactly once.
        logger.error.assert_called_once()
        # Summaries fire only at the 5th and 10th repeats.
        assert logger.warning.call_count == 2
        first_summary = logger.warning.call_args_list[0][0][0]
        second_summary = logger.warning.call_args_list[1][0][0]
        assert "repeated=5" in first_summary
        assert "repeated=10" in second_summary
        # The stable grouping key is emitted as a structured field.
        assert "error_key=RuntimeError@" in first_summary

    def test_distinct_errors_logged_separately(self) -> None:
        """Different errors are tracked independently, each logged once."""
        logger = Mock()
        throttler = _ErrorThrottler(logger)

        self._log(throttler, "context", RuntimeError("a"))
        self._log(throttler, "context", ValueError("b"))

        assert logger.error.call_count == 2

    def test_varying_messages_same_site_are_grouped(self) -> None:
        """Same error type+site is throttled even when the message varies.

        Keying on ``str(exc)`` would treat each message as a new error and
        re-flood the log with full tracebacks; keying on type+location does not.
        """
        logger = Mock()
        throttler = _ErrorThrottler(logger)

        for i in range(10):
            self._log(throttler, "context", RuntimeError(f"coords {i}"))

        # All ten share one origin, so only the first logs a traceback.
        logger.error.assert_called_once()

    def test_error_key_without_traceback_is_unknown(self) -> None:
        """An exception that was never raised has no traceback, so location is unknown."""
        exc = RuntimeError("never raised")
        assert exc.__traceback__ is None

        key = _ErrorThrottler._error_key(exc)

        assert key == "RuntimeError@<unknown>"

    def test_error_key_walks_to_innermost_frame(self) -> None:
        """The grouping key reflects the innermost frame, not the catch site.

        Raising through a nested call gives the traceback multiple frames; the
        key must report where the error originated (the inner function).
        """

        def inner() -> None:
            raise RuntimeError("deep")

        def outer() -> None:
            inner()

        try:
            outer()
        except RuntimeError as exc:
            key = _ErrorThrottler._error_key(exc)

        # The innermost frame is inside ``inner``; its line differs from the
        # ``outer()`` call site, confirming the tb_next loop walked all the way in.
        assert key.startswith("RuntimeError@")
        assert f"{__file__}:" in key
        inner_line = inner.__code__.co_firstlineno + 1
        assert key.endswith(f":{inner_line}")

    def test_distinct_error_count_is_capped_by_evicting_oldest(self) -> None:
        """Tracking is bounded by evicting the least-recently-seen error.

        A long session cannot grow ``_counts`` without limit, and unlike a
        clear-all strategy only the single oldest distinct error is dropped.
        """
        logger = Mock()
        throttler = _ErrorThrottler(logger, max_distinct=2)

        self._log(throttler, "context", RuntimeError("a"))
        self._log(throttler, "context", ValueError("b"))
        # The third distinct error exceeds the cap and evicts the oldest (the
        # RuntimeError); the two most-recent errors remain.
        self._log(throttler, "context", KeyError("c"))

        assert len(throttler._counts) == 2
        kinds = {key.split("@", 1)[0] for key in throttler._counts}
        assert kinds == {"ValueError", "KeyError"}

    def test_recurring_error_survives_a_burst_of_one_off_errors(self) -> None:
        """A recurring error keeps its running count despite eviction churn.

        This is the point of LRU eviction over clear-all: a steady recurring
        failure is refreshed on every occurrence, so a flood of distinct one-off
        errors evicts the noise, not the recurring error's accumulated count.
        """
        logger = Mock()
        throttler = _ErrorThrottler(logger, summary_interval=5, max_distinct=2)

        def recur() -> None:
            raise RuntimeError("recurring")

        # Fire the recurring error four times (below the summary interval),
        # interleaving a fresh, genuinely distinct error each round (a uniquely
        # named exception type, so its grouping key differs) to churn the cache
        # past its cap of 2 and force eviction of the noise.
        for i in range(4):
            try:
                recur()
            except RuntimeError as exc:
                throttler.log("context", exc)
            noise_type = type(f"Noise{i}", (RuntimeError,), {})
            try:
                raise noise_type("noise")
            except noise_type as exc:
                throttler.log("context", exc)

        # Every noise error has been evicted, but the recurring error survived
        # and is still tracked with its full count of 4...
        recurring_key = next(k for k in throttler._counts if "RuntimeError" in k)
        assert throttler._counts[recurring_key] == 4
        # ...so its 5th occurrence emits the summary (count was never reset).
        try:
            recur()
        except RuntimeError as exc:
            throttler.log("context", exc)
        assert "repeated=5" in logger.warning.call_args[0][0]


class TestChordGrouping:
    """KeyListener.group_chords: combining held modifiers with a key.

    Uses real pynput ``Key``/``KeyCode`` objects (they resolve headless) and a
    list sink. ``Key.ctrl_l``/``shift_l`` map to the platform-stable labels
    ``"Control Left"``/``"Shift Left"`` via ``_default_key_mappings``.
    """

    def _listener(self, captured: list[str], **overrides: object) -> KeyListener:
        settings = KeyboardSettings(group_chords=True, **overrides)  # type: ignore[arg-type]
        return KeyListener(captured.append, settings)

    def test_modifier_press_is_held_silently(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)

        # Held, not emitted, until a key completes the chord or it is released.
        assert captured == []

    def test_chord_combines_modifier_and_key(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("s"))

        assert captured == ["Control Left + s"]

    def test_chord_lists_modifiers_in_press_order(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.Key.shift_l)
        listener._on_press(keyboard.KeyCode.from_char("a"))

        assert captured == ["Control Left + Shift Left + a"]

    def test_custom_chord_separator(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured, chord_separator="+")

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("s"))

        assert captured == ["Control Left+s"]

    def test_lone_modifier_is_emitted_on_release(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_release(keyboard.Key.ctrl_l)

        assert captured == ["Control Left"]

    def test_modifier_used_in_chord_is_not_re_emitted_on_release(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("s"))
        listener._on_release(keyboard.KeyCode.from_char("s"))
        listener._on_release(keyboard.Key.ctrl_l)

        # Only the chord shows; the modifier is not repeated on release.
        assert captured == ["Control Left + s"]

    def test_next_hold_after_chord_can_emit_lone_modifier(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        # First hold completes a chord...
        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("s"))
        listener._on_release(keyboard.Key.ctrl_l)
        # ...and the "fired" state resets, so a later lone tap still shows.
        listener._on_press(keyboard.Key.shift_l)
        listener._on_release(keyboard.Key.shift_l)

        assert captured == ["Control Left + s", "Shift Left"]

    def test_lone_modifier_respects_show_modifier_keys(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured, show_modifier_keys=False)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_release(keyboard.Key.ctrl_l)

        assert captured == []

    def test_chord_shows_modifiers_even_when_lone_modifiers_hidden(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured, show_modifier_keys=False)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("s"))

        # A chord always carries its modifiers; show_modifier_keys only gates
        # lone modifier taps.
        assert captured == ["Control Left + s"]

    def test_character_without_modifiers_is_emitted_normally(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.KeyCode.from_char("a"))

        assert captured == ["a"]

    def test_on_release_is_noop_when_grouping_disabled(self) -> None:
        captured: list[str] = []
        listener = KeyListener(captured.append, KeyboardSettings())  # group off

        # Default behavior: press emits immediately, release does nothing.
        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_release(keyboard.Key.ctrl_l)

        assert captured == ["Control Left"]

    def test_on_release_none_is_safe(self) -> None:
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_release(None)  # must not raise

        assert captured == []

    def test_repeated_chords_under_one_hold(self) -> None:
        # The core presenter sequence: Ctrl held across Ctrl+C then Ctrl+V. Both
        # chords must show, and Ctrl must not leak out as a lone modifier.
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("c"))
        listener._on_release(keyboard.KeyCode.from_char("c"))
        listener._on_press(keyboard.KeyCode.from_char("v"))
        listener._on_release(keyboard.KeyCode.from_char("v"))
        listener._on_release(keyboard.Key.ctrl_l)

        assert captured == ["Control Left + c", "Control Left + v"]

    def test_ctrl_letter_control_char_maps_to_letter(self) -> None:
        # The OS delivers Ctrl+S as the C0 control character "\x13"; it must
        # render as the letter, not an invisible glyph.
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("\x13"))  # Ctrl+S

        assert captured == ["Control Left + s"]

    def test_hidden_chord_key_suppresses_chord_and_lone_modifier(self) -> None:
        # Ctrl+F1 with function keys hidden: the chord is not shown, and the
        # modifier is NOT fabricated as a lone "Control" on release — it was
        # consumed by the (hidden) chord.
        captured: list[str] = []
        listener = self._listener(captured, show_function_keys=False)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.Key.f1)
        listener._on_release(keyboard.Key.f1)
        listener._on_release(keyboard.Key.ctrl_l)

        assert captured == []

    @staticmethod
    def _backdate(listener: KeyListener, name: str) -> None:
        """Push a held modifier's press time past the staleness window."""
        held = listener._held_modifiers[name]
        listener._held_modifiers[name] = held._replace(
            pressed_at=held.pressed_at - (_MODIFIER_STALE_SECONDS + 1)
        )

    def test_stale_held_modifier_is_evicted_on_next_press(self) -> None:
        # A missed release (secure-input field, screen lock, ...) would otherwise
        # wedge the modifier "held" forever. Backdate its press time past the
        # staleness window; the next keypress evicts it and is a plain key, not a
        # phantom chord.
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        # Key name is platform-dependent (ctrl_l aliases ctrl on macOS), so read
        # it back rather than assuming which name pynput used.
        (name,) = listener._held_modifiers
        self._backdate(listener, name)

        listener._on_press(keyboard.KeyCode.from_char("a"))

        assert captured == ["a"]
        assert listener._held_modifiers == {}

    def test_partial_stale_eviction_clears_chord_fired(self) -> None:
        # A stuck modifier (missed release) after a completed chord must not
        # poison a later, unrelated hold. Ctrl wedges after Ctrl+S; a fresh Shift
        # is then held. When Ctrl is evicted (Shift survives), _chord_fired must
        # reset so Shift's lone tap is still emitted on release — not swallowed.
        captured: list[str] = []
        listener = self._listener(captured)

        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.KeyCode.from_char("s"))  # fires a chord
        (ctrl_name,) = listener._held_modifiers
        self._backdate(listener, ctrl_name)  # Ctrl's release was missed

        listener._on_press(keyboard.Key.shift_l)  # fresh hold; evicts stale Ctrl
        listener._on_release(keyboard.Key.shift_l)

        assert captured == ["Control Left + s", "Shift Left"]

    def test_ungrouped_ctrl_letter_control_char_maps_to_letter(self) -> None:
        # The control-char remap lives in _format_key, so it applies even with
        # grouping off: a raw "\x13" still renders as "s", not an invisible glyph.
        captured: list[str] = []
        listener = KeyListener(captured.append, KeyboardSettings())  # group off

        listener._on_press(keyboard.KeyCode.from_char("\x13"))  # Ctrl+S

        assert captured == ["s"]


class TestMouseFractionalCoordinates:
    """pynput can deliver float coordinates on high-DPI (Retina) displays.

    The type hint says int, but the runtime value is a float; the position text
    (show_mouse_position) must render clean integers, not "(210.89453125, 72.4...)".
    """

    def test_fractional_coordinates_rounded_in_position_text(self) -> None:
        captured: list[str] = []
        settings = MouseSettings(show_mouse_clicks=True, show_mouse_position=True)
        listener = MouseListener(captured.append, settings)

        listener._on_click(210.89453125, 72.421875, mouse.Button.left, pressed=True)  # type: ignore[arg-type]

        assert captured == ["Left Click (211, 72)"]

    def test_non_numeric_coordinate_does_not_crash_the_listener(self) -> None:
        # A backend handing back a non-numeric coord must surface as a throttled
        # mouse_format_error, not an unhandled exception escaping the pynput
        # callback (which would silently stop the listener thread). The rounding
        # lives inside the try for exactly this reason.
        captured: list[str] = []
        settings = MouseSettings(show_mouse_clicks=True, show_mouse_position=True)
        listener = MouseListener(captured.append, settings)

        listener._on_click(None, None, mouse.Button.left, pressed=True)  # type: ignore[arg-type]

        assert captured == []  # no event emitted, and no exception raised
