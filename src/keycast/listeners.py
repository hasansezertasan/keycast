"""Input event listeners for keyboard and mouse events."""

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple, Protocol

from pynput import keyboard, mouse

# ``_ErrorThrottler`` lives in logging_setup (a dependency-light module) so the
# display layer can share it without importing pynput; re-imported here for the
# listener callbacks. Imported into this namespace so existing references to
# ``keycast.listeners._ErrorThrottler`` keep resolving.
from keycast.logging_setup import _ErrorThrottler, format_event
from keycast.secure_input import is_secure_input_active

if TYPE_CHECKING:
    from keycast.settings import KeyboardSettings, MouseSettings

# A modifier physically held longer than this (continuously, without a matching
# release) is treated as stale and dropped from the chord state. pynput can miss
# release events entirely — macOS secure-input fields, screen lock, focus
# stealing, event-tap timeouts — which would otherwise leave a modifier "held"
# forever, rendering every subsequent keystroke as a phantom chord with no
# recovery. No real modifier+key chord is held continuously for this long, so
# eviction self-heals the stuck state on the next keypress without breaking
# legitimate held-modifier sequences (e.g. Shift held across many arrow keys).
_MODIFIER_STALE_SECONDS = 30.0


class HeldModifier(NamedTuple):
    """A modifier currently held down, for chord grouping.

    ``pressed_at`` is a :func:`time.monotonic` timestamp used only for staleness
    eviction (see :data:`_MODIFIER_STALE_SECONDS`); ``label`` is the pre-resolved
    display string so a chord or lone-release can reuse it without re-formatting.
    """

    label: str
    pressed_at: float


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

    def __init__(
        self,
        show_text: TextSink,
        settings: KeyboardSettings,
        *,
        is_secure_input: Callable[[], bool] = is_secure_input_active,
    ) -> None:
        """Initialize the keyboard listener.

        Args:
            show_text: Sink invoked (on a pynput listener thread) with the
                formatted label each time a key is pressed
            settings: Keyboard settings
            is_secure_input: Predicate returning whether the OS currently reports
                secure input (a password/authentication field is focused). Called
                per press when ``settings.mask_secure_input`` is set; injected so
                tests can drive masking without a real secure field. Defaults to
                the macOS probe :func:`keycast.secure_input.is_secure_input_active`
                (a no-op returning ``False`` on other platforms).
        """
        self.show_text = show_text
        """The callback function called when a key is pressed."""
        self.settings = settings
        """The keyboard settings."""
        self._is_secure_input = is_secure_input
        """Predicate telling whether secure input is active (see __init__)."""
        self.listener: keyboard.Listener | None = None
        """The keyboard listener instance."""
        self.logger = logging.getLogger(__name__)
        """The logger instance."""
        self._error_throttler = _ErrorThrottler(self.logger)
        """Throttles repeated errors from the per-keystroke callback."""
        # Chord-grouping state (only used when settings.group_chords is set).
        # Insertion-ordered so a chord lists modifiers in the order pressed.
        # Mutated only on the single pynput listener thread, so no lock is needed.
        self._held_modifiers: dict[str, HeldModifier] = {}
        """Currently held modifiers: key name -> HeldModifier(label, pressed_at)."""
        self._chord_fired = False
        """Whether a non-modifier completed a chord during the current hold."""
        self._secure_input_active = False
        """Whether the last observed press saw secure input active.

        Tracks the active<->inactive edge so masking is logged once per
        transition, never per keystroke (see :meth:`_on_press`).
        """

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
                # Ctrl+<letter> arrives as a C0 control character (Ctrl+A is
                # "\x01", ... Ctrl+Z is "\x1a") on Windows/X11 and for Ctrl
                # combos on macOS. Map it back to its letter so a grouped chord
                # reads "Control Left + a" instead of an invisible/garbage glyph.
                # Named keys like Tab/Enter/Esc/Backspace arrive as Key objects,
                # not here, so only the 26 Ctrl+letter codes are remapped.
                if len(key.char) == 1 and 1 <= ord(key.char) <= 26:
                    return chr(ord(key.char) + 96)
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

    def _evict_stale_modifiers(self) -> None:
        """Drop modifiers held longer than ``_MODIFIER_STALE_SECONDS``.

        Guards against pynput missing a release event (see the constant's note),
        which would otherwise wedge a modifier in ``_held_modifiers`` forever and
        turn every later keystroke into a phantom chord. Called at the top of
        :meth:`_on_press` so the stuck state self-heals on the next keypress.
        """
        now = time.monotonic()
        stale = [
            name
            for name, held in self._held_modifiers.items()
            if now - held.pressed_at > _MODIFIER_STALE_SECONDS
        ]
        for name in stale:
            del self._held_modifiers[name]
            self.logger.debug(
                format_event("stale_held_modifier_evicted", modifier=name)
            )
        # Any eviction ends the current hold session: an evicted modifier belongs
        # to a wedged, stuck-open hold, so _chord_fired (set by that session) is no
        # longer meaningful — clear it even if fresher modifiers are still held, or
        # a later lone tap of one of those would be wrongly suppressed. A fresh
        # modifier that then completes a real chord re-sets the flag on that press.
        if stale:
            self._chord_fired = False

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
            # Secure-input masking: if the OS reports a password/authentication
            # field is focused, drop the keystroke entirely before it can be
            # formatted, held as a chord modifier, or reach the sink -- so a typed
            # credential never lands on the overlay. Checked ahead of chord state
            # so a modifier pressed inside a secure field is not stashed in
            # _held_modifiers (which would fabricate a phantom chord on the next
            # visible key). Best-effort: is_secure_input is False off macOS.
            if self.settings.mask_secure_input:
                secure = self._is_secure_input()
                # Edge-triggered logging: one line when masking begins and one
                # when it ends -- never per keystroke. A per-press log (even at
                # DEBUG) would re-leak into ~/.keycast/main.log the very password
                # length/cadence the mask exists to hide. Logging only the
                # transition still lets an operator confirm masking engaged. The
                # "ended" edge is picked up lazily on the first press after
                # secure input clears, so no polling thread is needed.
                if secure != self._secure_input_active:
                    self._secure_input_active = secure
                    self.logger.info(
                        format_event(
                            "secure_input_masking_started"
                            if secure
                            else "secure_input_masking_ended"
                        )
                    )
                if secure:
                    return
            if self.settings.group_chords:
                self._evict_stale_modifiers()
            key_name = self._key_name(key)
            if (
                self.settings.group_chords
                and key_name is not None
                and self._is_modifier(key_name)
            ):
                # Hold the modifier silently; its label is resolved now so a later
                # chord or a lone-release can reuse it.
                self._held_modifiers[key_name] = HeldModifier(
                    self._format_key(key), time.monotonic()
                )
                return
            # A non-modifier pressed while modifiers are held completes a chord.
            # Record that *before* the visibility filter: if the chord's key is
            # hidden (e.g. Ctrl+F1 with show_function_keys off), we must still
            # mark the hold session as consumed so releasing the modifier does
            # not fabricate a misleading lone "Control" — the modifier was used,
            # even though its chord is not displayed.
            chord_active = self.settings.group_chords and bool(self._held_modifiers)
            if chord_active:
                self._chord_fired = True
            if not self._should_show_key(key):
                return
            formatted_key = self._format_key(key)
            if chord_active:
                # Prefix the held modifiers, in the order pressed. The chord
                # always carries its modifiers, even when show_modifier_keys is
                # off (a chord without them is useless).
                labels = [held.label for held in self._held_modifiers.values()]
                formatted_key = self.settings.chord_separator.join(
                    [*labels, formatted_key]
                )
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
            label = self._held_modifiers.pop(key_name).label
            # Emit a lone modifier only if no chord consumed this hold session,
            # and not while secure input is active. A modifier pressed *before* a
            # password field gained focus is legitimately held (the press-path
            # mask never saw it), but releasing it *during* the secure window
            # must not surface even a lone modifier label -- symmetric with the
            # press-path mask. The pop above and the reset below still run, so
            # chord state stays clean across the secure window.
            emit_lone = (
                not self._chord_fired
                and self.settings.show_modifier_keys
                and not (self.settings.mask_secure_input and self._is_secure_input())
            )
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
        # Only presses are visualized (button-up is not an event keycast shows).
        if not pressed:
            return

        # Formatting and the text-sink call are separate failure domains; see the
        # matching note in ``KeyListener._on_press``. They are caught and
        # reported under different event names so a broken display sink is not
        # mislabeled as a mouse-formatting error.
        try:
            if not self.settings.show_mouse_clicks:
                return
            text = self._format_button(button)
            if self.settings.show_mouse_position:
                # pynput may deliver fractional coordinates on high-DPI (Retina)
                # displays; the type hint says int but the runtime value can be a
                # float, so round for a clean "(210, 72)" rather than
                # "(210.89453125, 72.4...)". Kept inside the try so a non-numeric
                # coordinate surfaces as a throttled mouse_format_error instead of
                # an unhandled exception that would silently kill the pynput
                # listener thread (clicks would then stop appearing, no logs).
                text += f" ({round(x)}, {round(y)})"
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
