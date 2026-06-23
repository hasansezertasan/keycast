"""Input event listeners for keyboard and mouse events."""

import logging
from typing import TYPE_CHECKING, Protocol

from pynput import keyboard, mouse

# ``_ErrorThrottler`` lives in logging_setup (a dependency-light module) so the
# display layer can share it without importing pynput; re-imported here for the
# listener callbacks. Imported into this namespace so existing references to
# ``keycast.listeners._ErrorThrottler`` keep resolving.
from keycast.logging_setup import _ErrorThrottler, format_event

if TYPE_CHECKING:
    from keycast.settings import KeyboardSettings, MouseSettings


class TextSink(Protocol):
    """A sink that displays a single line of text.

    Listeners invoke this on a **pynput listener thread**, not the
    application's main thread. Any implementation that touches a GUI toolkit
    (e.g. tkinter, which is not thread-safe) must marshal the work onto its own
    UI thread; see :meth:`keycast.display.DisplayWindow.show_text`.
    """

    def __call__(self, text: str) -> None:
        """Display ``text``.

        Args:
            text: The text to display.
        """
        ...


class KeyListener:
    """Keyboard event listener using pynput."""

    def __init__(self, show_text: TextSink, settings: KeyboardSettings) -> None:
        """Initialize the keyboard listener.

        Args:
            show_text: Sink invoked (on a pynput listener thread) with the
                formatted label each time a key is pressed
            settings: Keyboard settings
        """
        self.show_text = show_text
        """The callback function called when a key is pressed."""
        self.settings = settings
        """The keyboard settings."""
        self.listener: keyboard.Listener | None = None
        """The keyboard listener instance."""
        self.logger = logging.getLogger(__name__)
        """The logger instance."""
        self._error_throttler = _ErrorThrottler(self.logger)
        """Throttles repeated errors from the per-keystroke callback."""

    def _key_name(self, key: keyboard.Key | keyboard.KeyCode) -> str | None:
        """Return the stable pynput name for a special key, or None for others.

        ``keyboard.Key`` members expose a reliable ``name`` attribute (e.g.
        "space", "ctrl_r", "f1"), which is more robust than parsing ``str(key)``.
        Note that left modifiers are not stable across platforms: on macOS and
        Linux ``Key.ctrl_l`` aliases ``Key.ctrl`` and reports name "ctrl" (see
        :func:`keycast.settings._default_key_mappings`). Character keys
        (``KeyCode``) have no such name and return None.

        Args:
            key: The key object from pynput

        Returns:
            The special key's name, or None for character/unknown keys
        """
        if isinstance(key, keyboard.Key):
            return key.name
        return None

    def _format_key(self, key: keyboard.Key | keyboard.KeyCode) -> str:
        """Format a key for display.

        Args:
            key: The key object from pynput

        Returns:
            Formatted key string
        """
        # Handle regular character keys
        if isinstance(key, keyboard.KeyCode):
            if key.char:
                return key.char
            # Dead/virtual key code with no character: fall back to its repr.
            return str(key)

        key_name = self._key_name(key)
        if key_name is None:
            return str(key)

        # Look up custom mappings first. ``key.name`` has the bare-key-name shape
        # (see ``settings.is_bare_key_name``) that ``_validate_key_mappings``
        # enforces on config keys, so a configured mapping for this key matches.
        if key_name in self.settings.key_mappings:
            return self.settings.key_mappings[key_name]

        return key_name.capitalize()

    def _should_show_key(self, key: keyboard.Key | keyboard.KeyCode) -> bool:
        """Determine if a key should be displayed based on settings.

        Args:
            key: The key object from pynput

        Returns:
            True if the key should be displayed
        """
        key_name = self._key_name(key)
        if key_name is None:
            # Character (or unknown) keys are always shown.
            return True

        # Check if it's a modifier key. pynput reports the Windows/Super key as
        # "cmd" (not "win") on every platform, so there is no "win" prefix to
        # match here.
        if key_name.startswith(("ctrl", "alt", "shift", "cmd")):
            return self.settings.show_modifier_keys

        # Check if it's a function key (f1, f2, etc.)
        if key_name.startswith("f") and len(key_name) > 1 and key_name[1:].isdigit():
            return self.settings.show_function_keys

        # Check if it's a special key
        special_keys = {
            "space",
            "enter",
            "tab",
            "backspace",
            "delete",
            "esc",
            "up",
            "down",
            "left",
            "right",
        }
        if key_name in special_keys:
            return self.settings.show_special_keys

        # Any other named special key is shown by default.
        return True

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        """Handle key press events.

        Args:
            key: The pressed key
        """
        # Formatting and the sink call are separate failure domains: a bug in
        # key formatting ("could not format this key") is distinct from a broken
        # display sink ("the overlay is broken"). Keeping them in one try would
        # mislabel a display-layer fault as an input error, so they are caught
        # and reported under different event names.
        try:
            if key is None:
                self.logger.warning(
                    format_event("key_event_skipped", reason="key_is_none")
                )
                return
            if not self._should_show_key(key):
                return
            formatted_key = self._format_key(key)
        except Exception as exc:
            self._error_throttler.log("key_format_error", exc, key=key)
            return

        try:
            self.show_text(formatted_key)
        except Exception as exc:
            self._error_throttler.log("key_sink_error", exc, key=key)

    def start(self) -> None:
        """Start the keyboard listener."""
        if not self.settings.enabled:
            self.logger.info("keyboard_listener_disabled")
            return

        try:
            self.listener = keyboard.Listener(on_press=self._on_press)
            self.listener.start()
            self.logger.info("keyboard_listener_started")
        except Exception:
            # Drop any half-constructed listener so a later stop() does not try
            # to stop something that never started running.
            self.listener = None
            self.logger.exception("keyboard_listener_start_failed")
            raise

    def stop(self) -> None:
        """Stop the keyboard listener."""
        if not self.settings.enabled:
            self.logger.info("keyboard_listener_disabled")
            return

        if self.listener:
            self.listener.stop()
            self.listener = None
            self.logger.info("keyboard_listener_stopped")


class MouseListener:
    """Mouse event listener using pynput."""

    def __init__(self, show_text: TextSink, settings: MouseSettings) -> None:
        """Initialize the mouse listener.

        Args:
            show_text: Sink invoked (on a pynput listener thread) with the
                formatted label each time the mouse is clicked
            settings: Mouse settings
        """
        self.show_text = show_text
        """The callback function called when mouse is clicked."""
        self.settings = settings
        """The mouse settings."""
        self.listener: mouse.Listener | None = None
        """The mouse listener instance."""
        self.logger = logging.getLogger(__name__)
        """The logger instance."""
        self._error_throttler = _ErrorThrottler(self.logger)
        """Throttles repeated errors from the per-click callback."""

    def _format_button(self, button: mouse.Button) -> str:
        """Format a mouse button for display.

        Args:
            button: The mouse button object from pynput

        Returns:
            Formatted button string
        """
        # pynput stringifies buttons as ``Button.<name>`` (e.g. "Button.left") —
        # the same shape ``settings.is_button_string`` enforces on config keys,
        # so a configured ``button_names`` mapping for this button matches.
        button_name = str(button)

        # Check custom mappings first
        if button_name in self.settings.button_names:
            return self.settings.button_names[button_name]

        # Apply default formatting
        if button_name == "Button.left":
            return "Left Click"
        if button_name == "Button.right":
            return "Right Click"
        if button_name == "Button.middle":
            return "Middle Click"
        return button_name.replace("Button.", "").capitalize() + " Click"

    def _on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:  # noqa: FBT001
        """Handle mouse click events.

        Args:
            x: X coordinate of the click
            y: Y coordinate of the click
            button: The clicked button
            pressed: Whether the button was pressed (True) or released (False)

        """
        # Formatting and the sink call are separate failure domains; see the
        # matching note in ``KeyListener._on_press``. They are caught and
        # reported under different event names so a broken display sink is not
        # mislabeled as a mouse-formatting error.
        try:
            if not (pressed and self.settings.show_mouse_clicks):
                return
            text = self._format_button(button)
            if self.settings.show_mouse_position:
                text += f" ({x}, {y})"
        except Exception as exc:
            self._error_throttler.log("mouse_format_error", exc, button=button)
            return

        try:
            self.show_text(text)
        except Exception as exc:
            self._error_throttler.log("mouse_sink_error", exc, button=button)

    def start(self) -> None:
        """Start the mouse listener."""
        if not self.settings.enabled:
            self.logger.info("mouse_listener_disabled")
            return

        try:
            self.listener = mouse.Listener(on_click=self._on_click)
            self.listener.start()
            self.logger.info("mouse_listener_started")
        except Exception:
            # Drop any half-constructed listener so a later stop() does not try
            # to stop something that never started running.
            self.listener = None
            self.logger.exception("mouse_listener_start_failed")
            raise

    def stop(self) -> None:
        """Stop the mouse listener."""
        if not self.settings.enabled:
            self.logger.info("mouse_listener_disabled")
            return

        if self.listener:
            self.listener.stop()
            self.listener = None
            self.logger.info("mouse_listener_stopped")
