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


class ClickSink(Protocol):
    """A sink that receives the raw ``(x, y)`` position of a mouse click.

    The second, optional listener channel alongside :class:`TextSink`, used to
    drive the click ripple with coordinates a formatted string cannot carry. The
    same threading contract applies: it is invoked on a **pynput listener
    thread**, so a GUI implementation must marshal onto its own UI thread (see
    :meth:`keycast.display.DisplayWindow.show_click`).
    """

    def __call__(self, x: int, y: int) -> None:
        """Handle a click at ``(x, y)``.

        Args:
            x: The click x-coordinate in screen pixels.
            y: The click y-coordinate in screen pixels.
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
        # Chord-grouping state (only used when settings.group_chords is set).
        # Insertion-ordered so a chord lists modifiers in the order pressed.
        # Mutated only on the single pynput listener thread, so no lock is needed.
        self._held_modifiers: dict[str, str] = {}
        """Currently held modifiers: key name -> display label."""
        self._chord_fired = False
        """Whether a non-modifier completed a chord during the current hold."""

    @staticmethod
    def _is_modifier(key_name: str | None) -> bool:
        """Return whether a pynput key name is a modifier keycast tracks for chords.

        Mirrors the modifier prefixes ``_should_show_key`` keys off; the Super key
        is reported as "cmd" on every platform (never "win"), so there is no "win"
        prefix here.

        Args:
            key_name: The pynput key name, or None for character/unknown keys.

        Returns:
            True if the name is a ctrl/alt/shift/cmd modifier.
        """
        return key_name is not None and key_name.startswith(
            ("ctrl", "alt", "shift", "cmd")
        )

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
            key_name = self._key_name(key)
            if (
                self.settings.group_chords
                and key_name is not None
                and self._is_modifier(key_name)
            ):
                # Hold the modifier silently; its label is resolved now so a later
                # chord or a lone-release can reuse it.
                self._held_modifiers[key_name] = self._format_key(key)
                return
            if not self._should_show_key(key):
                return
            formatted_key = self._format_key(key)
            if self.settings.group_chords and self._held_modifiers:
                # Non-modifier completing a chord: prefix the held modifiers, in
                # the order pressed. The chord always carries its modifiers, even
                # when show_modifier_keys is off (a chord without them is useless).
                parts = [*self._held_modifiers.values(), formatted_key]
                formatted_key = self.settings.chord_separator.join(parts)
                self._chord_fired = True
        except Exception as exc:
            self._error_throttler.log("key_format_error", exc, key=key)
            return

        try:
            self.show_text(formatted_key)
        except Exception as exc:
            self._error_throttler.log("key_sink_error", exc, key=key)

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        """Handle key release events, used only for chord grouping.

        Tracks which modifiers are currently held so :meth:`_on_press` can build
        chords. A modifier released without having completed a chord during its
        hold is emitted alone here (subject to ``show_modifier_keys``), so a lone
        modifier tap still shows. A no-op unless ``group_chords`` is set.

        Args:
            key: The released key (pynput may deliver None).
        """
        if not self.settings.group_chords:
            return

        # Formatting/state and the sink call are separate failure domains, mirrored
        # from _on_press so a broken sink is not mislabeled as a format error.
        try:
            if key is None:
                return
            key_name = self._key_name(key)
            if key_name is None or not self._is_modifier(key_name):
                return
            if key_name not in self._held_modifiers:
                return
            label = self._held_modifiers.pop(key_name)
            # Emit a lone modifier only if no chord consumed this hold session.
            emit_lone = not self._chord_fired and self.settings.show_modifier_keys
            if not self._held_modifiers:
                # Hold session ended; reset for the next one.
                self._chord_fired = False
            if not emit_lone:
                return
        except Exception as exc:
            self._error_throttler.log("key_format_error", exc, key=key)
            return

        try:
            self.show_text(label)
        except Exception as exc:
            self._error_throttler.log("key_sink_error", exc, key=key)

    def start(self) -> None:
        """Start the keyboard listener."""
        if not self.settings.enabled:
            self.logger.info("keyboard_listener_disabled")
            return

        try:
            # on_release is registered unconditionally; it early-returns unless
            # group_chords is set, so it is inert in the default configuration.
            self.listener = keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release
            )
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

    def __init__(
        self,
        show_text: TextSink,
        settings: MouseSettings,
        *,
        on_click_position: ClickSink | None = None,
    ) -> None:
        """Initialize the mouse listener.

        Args:
            show_text: Sink invoked (on a pynput listener thread) with the
                formatted label each time the mouse is clicked
            settings: Mouse settings
            on_click_position: Optional second sink invoked with the raw ``(x, y)``
                of each click, used to drive the click ripple. Keyword-only so the
                documented positional signature stays ``(show_text, settings)``.
                The composition root wires this only when
                ``settings.show_click_ripple`` is set.
        """
        self.show_text = show_text
        """The callback function called when mouse is clicked."""
        self.on_click_position = on_click_position
        """Optional sink for the raw click position (drives the click ripple)."""
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
        # Only presses are visualized (button-up is not an event keycast shows).
        if not pressed:
            return

        # pynput may deliver fractional coordinates on high-DPI displays (Retina);
        # the type hint says int, but the runtime value can be a float. Round once
        # here, at the capture boundary, so both channels get clean integers: the
        # ripple's Tk geometry string rejects non-integers, and the position text
        # would otherwise render "(210.89453125, 72.4...)".
        x, y = round(x), round(y)

        # The ripple is an independent channel: it fires on any click when
        # enabled, regardless of show_mouse_clicks (which gates only the text
        # label). Its own failure domain so a broken ripple sink is not mislabeled
        # as a text-sink or format error.
        if self.settings.show_click_ripple and self.on_click_position is not None:
            try:
                self.on_click_position(x, y)
            except Exception as exc:
                self._error_throttler.log("mouse_ripple_error", exc, button=button)

        # Formatting and the text-sink call are separate failure domains; see the
        # matching note in ``KeyListener._on_press``. They are caught and
        # reported under different event names so a broken display sink is not
        # mislabeled as a mouse-formatting error.
        try:
            if not self.settings.show_mouse_clicks:
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
