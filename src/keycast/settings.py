"""Python module for keycast configuration and paths."""

import logging
import os
import platform
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema
from pydantic_extra_types.color import Color
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class _ReadOnlyStrMap:
    """Pydantic marker: validate a ``dict[str, str]`` then freeze it.

    Used via :data:`ReadOnlyStrMap`. ``frozen=True`` on a model only blocks
    rebinding a field, not mutation of a dict the field points at, so the value
    is wrapped in a read-only :class:`~types.MappingProxyType` once validated.
    Annotating the field as ``MappingProxyType[str, str]`` (rather than a bare
    ``Mapping``) makes the type honest about the immutable runtime value, while
    this schema keeps accepting the plain ``dict`` that JSON config and callers
    supply and still enforces ``str``-to-``str`` contents.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: object, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Build a schema that validates a ``dict[str, str]`` and wraps it.

        Args:
            source: The annotated source type (ignored; contents are fixed).
            handler: Pydantic's schema handler, used to build the inner schema.

        Returns:
            A core schema producing a read-only ``MappingProxyType`` and
            serializing it back to a plain ``dict`` for ``model_dump_json``.
        """
        dict_schema = handler.generate_schema(dict[str, str])
        return core_schema.no_info_after_validator_function(
            lambda value: MappingProxyType(dict(value)),
            dict_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(dict),
        )


ReadOnlyStrMap = Annotated[MappingProxyType[str, str], _ReadOnlyStrMap()]
"""A ``str``-to-``str`` mapping that validates from a dict and is read-only."""


def is_bare_key_name(name: str) -> bool:
    """Return whether ``name`` has the shape pynput uses for ``Key.name``.

    Single source of truth for the keyboard mapping-key grammar. ``Key.name`` is
    always lowercase and carries no ``"Key."`` prefix (e.g. ``"ctrl_l"``,
    ``"space"``, ``"f1"``). Both ``KeyboardSettings._validate_key_mappings``
    (which rejects malformed config keys) and the lookup in
    ``KeyListener._format_key`` (which looks names up by ``key.name``) rely on
    this same grammar; keeping it here stops the two sides from drifting.
    """
    return "." not in name and name == name.lower()


def is_button_string(name: str) -> bool:
    """Return whether ``name`` has the shape pynput uses for ``str(Button)``.

    Single source of truth for the mouse mapping-key grammar. pynput renders a
    button as ``Button.<name>`` (e.g. ``"Button.left"``). Both
    ``MouseSettings._validate_button_names`` and the lookup in
    ``MouseListener._format_button`` (which keys off ``str(button)``) rely on
    this grammar; keeping it here stops the two sides from drifting.
    """
    return name.startswith("Button.")


ROOT_FOLDER_NAME: str = ".keycast"
"""Name of the root folder."""

ROOT_FOLDER_PATH: Path = Path.home() / ROOT_FOLDER_NAME
"""Path to the root folder."""

LOG_FILE_PATH: Path = ROOT_FOLDER_PATH / "main.log"
"""Path to the log file."""

CONFIG_FILE_PATH: Path = ROOT_FOLDER_PATH / "config.json"
"""Path to the config file."""

UPDATE_CHECK_FILE_PATH: Path = ROOT_FOLDER_PATH / "update-check.json"
"""Path to the update-check state file.

Holds the throttle state for the update check (last-checked time and last-seen
release tag). Kept *separate* from ``config.json`` on purpose: ``Settings`` is
``frozen`` and rewritten atomically from defaults, so this mutable runtime state
must not live in the user's config. See ``keycast.updates``."""


class DisplaySettings(BaseModel):
    """Display window configuration settings."""

    model_config = ConfigDict(frozen=True)

    # Window dimensions and position
    width: int = Field(
        default=400,
        ge=100,
        le=2000,
        description="Window width in pixels",
    )
    height: int = Field(
        default=100,
        ge=50,
        le=1000,
        description="Window height in pixels",
    )
    # The configurability is intentionally asymmetric: x supports an explicit
    # "center" value (the overlay's natural horizontal placement), while y has
    # no center option because the overlay is meant to sit a fixed offset below
    # the top edge. Only x centering is implemented in DisplayWindow. The
    # literal "center" is a named value rather than a magic None so the intent
    # is self-documenting in the type and on disk. The int bounds are a *sanity*
    # check (they reject absurd values, not merely off-screen ones) and apply
    # only to the int member of the union; DisplayWindow clamps the final
    # position into the actual screen so an in-bounds-but-off-screen value still
    # renders visibly.
    x_position: Literal["center"] | Annotated[int, Field(ge=0, le=20000)] = Field(
        default="center",
        description='X position in pixels, or "center" to center horizontally; '
        "the int upper bound allows large multi-monitor desktops while rejecting "
        "absurd off-screen values",
    )
    y_position: int = Field(
        default=50,
        ge=0,
        le=20000,
        description="Y position in pixels from the top; see x_position for bounds",
    )

    # Visual appearance
    background_color: Color = Field(
        default=Color("black"),
        description="Background color",
    )
    text_color: Color = Field(
        default=Color("white"),
        description="Text color",
    )
    font_family: str = Field(
        default="Arial",
        min_length=1,
        description="Font family name (tkinter falls back to a default if the "
        "named family is unavailable on the system)",
    )
    font_size: int = Field(
        default=16,
        ge=8,
        le=72,
        description="Font size in points",
    )
    font_weight: Literal["normal", "bold"] = Field(
        default="bold",
        description="Font weight",
    )
    alpha: float = Field(
        default=0.8,
        ge=0.1,
        le=1.0,
        description="Window transparency",
    )

    # Window behavior
    always_on_top: bool = Field(
        default=True,
        description="Whether window stays on top",
    )
    draggable: bool = Field(
        default=False,
        description="Allow repositioning the overlay by dragging it with the "
        "mouse. The window has no title bar (overrideredirect), so dragging is "
        "bound directly on the overlay surface",
    )
    fade_duration_ms: int = Field(
        default=2000,
        ge=500,
        le=10000,
        description="How long events stay visible in milliseconds",
    )
    max_events: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of events to display",
    )


def _super_key_labels() -> tuple[str, str]:
    """Return the (left, right) labels for the Super/Command/Windows key.

    pynput reports this key as ``cmd``/``cmd_l``/``cmd_r`` on every platform,
    but its conventional name differs by OS: "Command" on macOS, "Windows" on
    Windows, and "Super" elsewhere. Labeling it per-platform keeps the on-screen
    text matching what users see printed on their own keyboards.

    Returns:
        A ``(left_label, right_label)`` pair for the host platform.
    """
    system = platform.system()
    if system == "Darwin":
        return "Command Left", "Command Right"
    if system == "Windows":
        return "Windows Left", "Windows Right"
    return "Super Left", "Super Right"


def _default_key_mappings() -> dict[str, str]:
    """Build the default key-name to label mappings for the host platform.

    Both the bare and "_l" variants map to the same label because pynput names
    the left modifier inconsistently across platforms. On macOS and Linux the
    left key and its bare alias share the same underlying value, so
    ``Key.ctrl_l`` is an enum alias of ``Key.ctrl`` and reports name "ctrl";
    only on Windows does the left key report a distinct "ctrl_l". Covering both
    names keeps labels stable everywhere. The Super/Command/Windows key labels
    are chosen per-platform (see :func:`_super_key_labels`).

    Returns:
        The default key-name to display-label mapping.
    """
    super_left, super_right = _super_key_labels()
    return {
        # Control
        "ctrl": "Control Left",
        "ctrl_l": "Control Left",
        "ctrl_r": "Control Right",
        # Alt / Option. The right-hand AltGr key only reports the distinct name
        # "alt_gr" on some platforms (Windows / X11); elsewhere (e.g. macOS) it
        # aliases "alt_r", so the "alt_gr" entry is inert there but harmless.
        "alt": "Alt Left",
        "alt_l": "Alt Left",
        "alt_r": "Alt Right",
        "alt_gr": "Alt Right",
        # Shift
        "shift": "Shift Left",
        "shift_l": "Shift Left",
        "shift_r": "Shift Right",
        # Command / Super / Windows
        "cmd": super_left,
        "cmd_l": super_left,
        "cmd_r": super_right,
        # Other
        "space": "Space Bar",
        "enter": "Enter",
    }


class KeyboardSettings(BaseModel):
    """Keyboard listener configuration settings."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Whether to enable the keyboard listener",
    )
    show_modifier_keys: bool = Field(
        default=True,
        description="Whether to show modifier keys (Ctrl, Alt, etc.)",
    )
    show_function_keys: bool = Field(
        default=True,
        description="Whether to show function keys (F1, F2, etc.)",
    )
    show_special_keys: bool = Field(
        default=True,
        description="Whether to show special keys (Enter, Space, etc.)",
    )
    group_chords: bool = Field(
        default=False,
        description="Combine a key pressed while modifiers are held into a single "
        'chord label (e.g. "Control Left + S") instead of separate events. A held '
        "modifier released on its own is still shown alone (subject to "
        "show_modifier_keys). Off by default; the presenter preset enables it.",
    )
    chord_separator: str = Field(
        default=" + ",
        min_length=1,
        description="String joining the parts of a grouped chord (see group_chords).",
    )
    # ``ReadOnlyStrMap`` validates the dict, freezes it in a read-only
    # ``MappingProxyType`` (``frozen=True`` only blocks rebinding the field, not
    # mutation of the dict it points at), and serializes it back to a plain dict.
    # ``validate_default`` makes the wrap apply to the default too.
    key_mappings: ReadOnlyStrMap = Field(
        default_factory=_default_key_mappings,
        validate_default=True,
        description="Custom key name mappings. Keys are pynput key names with "
        'the "Key." prefix removed (e.g. "ctrl_l", "space"); values are the '
        "labels shown on screen",
    )

    @field_validator("key_mappings")
    @classmethod
    def _validate_key_mappings(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        """Reject key names that cannot match a real pynput key.

        ``KeyListener._format_key`` looks names up by ``key.name`` (pynput's
        attribute for special keys), which is always lowercase and carries no
        ``"Key."`` prefix (e.g. "ctrl_l", "space", "f1"). A key written with the
        prefix ("Key.ctrl") or capitalized ("Ctrl") can never match, so the
        mapping would silently do nothing; rejecting it at config load turns that
        silent no-op into a visible error. Mirrors ``_validate_button_names``.

        Runs after ``ReadOnlyStrMap`` has already frozen the value, so it only
        validates and returns it unchanged.

        Args:
            value: The validated, read-only key-name mapping.

        Returns:
            The same mapping, unchanged.

        Raises:
            ValueError: If any key carries a ``.`` or is not all-lowercase.
        """
        bad = sorted(key for key in value if not is_bare_key_name(key))
        if bad:
            msg = (
                "key_mappings keys must be bare pynput key names: lowercase with "
                'no "Key." prefix (e.g. "ctrl_l", "space", "f1"); invalid keys: '
                f"{bad}"
            )
            raise ValueError(msg)
        return value


class MouseSettings(BaseModel):
    """Mouse listener configuration settings."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Whether to enable the mouse listener",
    )
    show_mouse_clicks: bool = Field(
        default=True,
        description="Whether to show mouse clicks",
    )
    show_mouse_position: bool = Field(
        default=False,
        description="Whether to show mouse position coordinates",
    )
    # See ``KeyboardSettings.key_mappings``: ``ReadOnlyStrMap`` validates,
    # freezes, and serializes the mapping; ``validate_default`` freezes the
    # empty default too.
    button_names: ReadOnlyStrMap = Field(
        default_factory=dict,
        validate_default=True,
        description="Custom button name mappings. Keys are full pynput button "
        'strings (e.g. "Button.left"); values are the labels shown on screen',
    )

    @field_validator("button_names")
    @classmethod
    def _validate_button_names(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        """Reject button keys that cannot match a real pynput button.

        ``MouseListener._format_button`` looks keys up by ``str(button)``, which
        pynput renders as ``Button.<name>``. A key without that prefix can never
        match, so the mapping would silently do nothing; rejecting it at config
        load turns that silent no-op into a visible error.

        Runs after ``ReadOnlyStrMap`` has already frozen the value, so it only
        validates and returns it unchanged.

        Args:
            value: The validated, read-only button-name mapping.

        Returns:
            The same mapping, unchanged.

        Raises:
            ValueError: If any key does not start with ``"Button."``.
        """
        bad = sorted(key for key in value if not is_button_string(key))
        if bad:
            msg = (
                "button_names keys must be full pynput button strings starting "
                f'with "Button." (e.g. "Button.left"); invalid keys: {bad}'
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_position_requires_clicks(self) -> "MouseSettings":
        """Reject ``show_mouse_position`` without ``show_mouse_clicks``.

        ``MouseListener._on_click`` appends the position only inside the
        ``pressed and show_mouse_clicks`` branch, so ``show_mouse_position=True``
        with ``show_mouse_clicks=False`` never renders anything. Like the
        mapping-key validators above, this turns that silently inert combination
        into a visible config error instead of a no-op.

        Returns:
            The validated settings, unchanged.

        Raises:
            ValueError: If ``show_mouse_position`` is set without
                ``show_mouse_clicks``.
        """
        if self.show_mouse_position and not self.show_mouse_clicks:
            msg = (
                "show_mouse_position has no effect unless show_mouse_clicks is "
                "also true (position is shown alongside clicks); enable "
                "show_mouse_clicks or disable show_mouse_position."
            )
            raise ValueError(msg)
        return self


class LoggingSettings(BaseModel):
    """Logging configuration settings."""

    model_config = ConfigDict(frozen=True)

    # pyrefly: ignore[bad-assignment]  # Field(default=...) can't be narrowed to the Literal; mypy/pyright/ty accept it.
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format",
    )
    file_path: Path | None = Field(
        default=LOG_FILE_PATH,
        description="Log file path (None for console only)",
    )
    max_file_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum log file size in MB",
    )
    backup_count: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Number of backup log files to keep",
    )

    @field_validator("format")
    @classmethod
    def _validate_format(cls, value: str) -> str:
        """Reject format strings that logging cannot use.

        Constructing a ``logging.Formatter`` validates the format against the
        ``%`` style, so a malformed format fails fast at config load instead of
        at the first log emission.

        Args:
            value: The candidate log format string.

        Returns:
            The validated format string.

        Raises:
            ValueError: If the format string is not a valid logging format.
        """
        try:
            logging.Formatter(value)
        except (ValueError, TypeError) as exc:
            msg = f"Invalid logging format string: {exc}"
            raise ValueError(msg) from exc
        return value


_PRESET_OVERRIDES: dict[str, dict[str, object]] = {
    # Screencast / demo: large, legible, lingers a little longer, clicks shown.
    "presenter": {
        "display": {
            "font_size": 28,
            "fade_duration_ms": 3000,
            "max_events": 3,
            "alpha": 0.9,
        },
        "mouse": {"show_mouse_clicks": True},
        "keyboard": {"group_chords": True},
    },
    # Unobtrusive corner overlay: small, faint, one event, gone quickly.
    "minimal": {
        "display": {
            "font_size": 12,
            "fade_duration_ms": 1000,
            "max_events": 1,
            "alpha": 0.6,
        },
    },
    # Troubleshooting: verbose logging plus everything visible, kept on screen.
    "debug": {
        "debug": True,
        "display": {"max_events": 10, "fade_duration_ms": 5000},
        "mouse": {"show_mouse_clicks": True, "show_mouse_position": True},
    },
}
"""Built-in preset name -> override bundle, layered over the loaded config.

Each override is a partial settings tree: a top-level scalar flag (e.g. ``debug``)
or a section name (``display`` / ``mouse`` / ``keyboard``) mapped to the fields it
replaces. :meth:`Settings.resolve_preset` applies these on top of the file /
defaults, so a preset only touches the fields it names; everything else keeps its
configured value. Every value must stay within its field's declared bounds:
``resolve_preset`` re-validates the merged result, so an out-of-range preset would
raise at load. ``"custom"`` is intentionally absent — it means "no overrides".
"""


class Settings(BaseSettings):
    """Main settings class for the keycast application."""

    model_config = SettingsConfigDict(
        json_file=CONFIG_FILE_PATH,
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )

    # Component settings
    display: DisplaySettings = Field(
        default_factory=DisplaySettings,
        description="Display window settings",
    )
    keyboard: KeyboardSettings = Field(
        default_factory=KeyboardSettings,
        description="Keyboard listener settings",
    )
    mouse: MouseSettings = Field(
        default_factory=MouseSettings,
        description="Mouse listener settings",
    )
    logging: LoggingSettings = Field(
        default_factory=LoggingSettings,
        description="Logging settings",
    )

    # App-wide flags
    debug: bool = Field(
        default=False,
        description="Enable debug mode: surface verbose diagnostics regardless of "
        "the configured logging level. See effective_logging for how this combines "
        "with logging.level.",
    )
    start_minimized: bool = Field(
        default=False,
        description="Start with the overlay hidden; it appears automatically the "
        "first time a key or click is captured. Requires auto_start (input must "
        "be captured for the overlay to ever appear).",
    )
    auto_start: bool = Field(
        default=True,
        description="Start the input listeners on launch. When false, no listeners "
        "start regardless of keyboard.enabled / mouse.enabled — a master switch "
        "that captures nothing until re-enabled in config.",
    )
    check_for_updates: bool = Field(
        default=True,
        description="Check the GitHub Releases API for a newer version at most "
        "once a day and show a non-blocking notice. Set false to disable all "
        "automatic update checks (offline / privacy). Throttle state is kept in "
        "~/.keycast/update-check.json, not in this config. See keycast.updates.",
    )
    # pyrefly: ignore[bad-assignment]  # Field(default=...) can't be narrowed to the Literal; mypy/pyright/ty accept it.
    preset: Literal["custom", "presenter", "minimal", "debug"] = Field(
        default="custom",
        description="Named settings bundle layered over the config on load. "
        '"custom" (default) uses the file verbatim; "presenter", "minimal" and '
        '"debug" override a handful of display/mouse fields (and, for "debug", '
        "verbose logging) for common scenarios. A preset wins over the file only "
        "for the fields it names; see resolve_preset and _PRESET_OVERRIDES.",
    )

    # Note: per-listener enable flags live on `keyboard.enabled` / `mouse.enabled`;
    # auto_start is the app-level master switch layered above them.

    @model_validator(mode="after")
    def _validate_minimized_requires_autostart(self) -> "Settings":
        """Reject ``start_minimized`` without ``auto_start``.

        A minimized start hides the overlay until the first captured event re-shows
        it (see ``DisplayWindow._restore_from_minimized``). With ``auto_start``
        off, no listeners run, so no event is ever captured and the overlay would
        stay hidden for the whole session with no way back. Like
        ``MouseSettings._validate_position_requires_clicks``, this turns that
        silently inert combination into a visible config error instead of a window
        that never appears.

        Returns:
            The validated settings, unchanged.

        Raises:
            ValueError: If ``start_minimized`` is set without ``auto_start``.
        """
        if self.start_minimized and not self.auto_start:
            msg = (
                "start_minimized requires auto_start: the overlay starts hidden and "
                "only reappears on the first captured event, but auto_start=false "
                "starts no listeners, so it would never reappear. Enable auto_start "
                "or disable start_minimized."
            )
            raise ValueError(msg)
        return self

    def effective_logging(self) -> LoggingSettings:
        """Return the logging settings to actually apply, accounting for ``debug``.

        ``debug`` is an app-wide switch for verbose diagnostics; ``logging.level``
        is the user's explicit level. This method is the single place that decides
        how the two combine into the one ``LoggingSettings`` that
        :func:`keycast.logging_setup.setup_logging` receives, so the policy lives
        in exactly one testable spot rather than being smeared across the wiring.

        ``LoggingSettings`` is ``frozen``, so a new instance must be derived with
        ``self.logging.model_copy(update={...})`` rather than mutating it.

        Returns:
            The logging settings to apply.
        """
        # Policy: when debug is on, force DEBUG (the most verbose level) so the
        # configured level cannot quiet diagnostics; when off, leave logging
        # exactly as configured (so debug never changes normal operation).
        if not self.debug:
            return self.logging
        return self.logging.model_copy(update={"level": "DEBUG"})

    def resolve_preset(self) -> "Settings":
        """Return the settings to apply, with the selected ``preset`` layered on.

        ``preset`` names a built-in override bundle (see :data:`_PRESET_OVERRIDES`)
        that is merged on top of the loaded config. ``"custom"`` (the default)
        applies nothing, so the settings are returned unchanged. Called by
        ``Keycast.__init__`` right after :meth:`create_settings_file`, so every
        component sees the resolved settings while the on-disk config keeps the
        user's raw values plus the ``preset`` name.

        Each overridden **section** is re-validated the same way loading the
        config does: its current values are dumped with ``model_dump(mode="json")``,
        the preset's fields are merged on top, and the section model's
        ``model_validate`` rebuilds it — re-running that section's field bounds and
        cross-field validators (e.g. ``MouseSettings``' position-requires-clicks
        rule), so a preset can never produce invalid section settings.
        ``model_copy`` then swaps the rebuilt sections (and any top-level scalar
        flags) into a new ``Settings``. Note the sub-models are plain
        ``BaseModel``, where ``model_validate`` honours the passed data; the
        top-level ``Settings`` is a ``BaseSettings`` whose ``model_validate``
        re-runs the configured sources instead, so it deliberately is *not* used
        to re-assemble here.

        A preset wins over the file for the fields it names, and only those; every
        other field keeps its configured value.

        Returns:
            A new ``Settings`` with the preset applied, or ``self`` when the
            preset is ``"custom"`` (or otherwise names no overrides).
        """
        overrides = _PRESET_OVERRIDES.get(self.preset)
        if not overrides:
            return self

        updates: dict[str, object] = {}
        for key, value in overrides.items():
            current = getattr(self, key, None)
            if isinstance(value, dict) and isinstance(current, BaseModel):
                # Re-validate the section with the preset's fields merged over its
                # current values. mode="json" yields JSON-safe primitives (Color
                # -> str, read-only mappings -> dict) that model_validate accepts.
                merged = {**current.model_dump(mode="json"), **value}
                updates[key] = type(current).model_validate(merged)
            else:
                # A top-level scalar flag (e.g. debug=True).
                updates[key] = value
        return self.model_copy(update=updates)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        env_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize the settings sources used to load the settings.

        Intentionally narrows configuration to a single authoritative source:
        the JSON config file. The init, environment, dotenv and file-secret
        sources are deliberately dropped, so constructor kwargs and environment
        variables do not influence loaded settings (tests that need overrides
        must patch the JSON source).

        Args:
            settings_cls: The settings class
            init_settings: The initial settings
            env_settings: The environment settings
            dotenv_settings: The dotenv settings
            file_secret_settings: The file secret settings

        Returns:
            The settings sources
        """
        return (JsonConfigSettingsSource(settings_cls),)

    @classmethod
    def create_settings_file(cls) -> "Settings":
        """Load settings, recovering from a corrupt file and persisting defaults.

        On first run (no config file) the defaults are written to disk. If the
        existing file is corrupt, it is backed up and defaults are used so the
        application can still start.

        Returns:
            The settings object

        Raises:
            TypeError: If the JSON file path is unset or is not a Path object
        """
        json_file = cls.model_config.get("json_file")
        if not json_file:
            msg = "JSON file path is unset"
            raise TypeError(msg)
        if not isinstance(json_file, Path):
            msg = "JSON file path is not a Path object"
            raise TypeError(msg)

        try:
            settings = cls()
            persistable = True
        except (ValidationError, ValueError) as exc:
            # Corrupt or malformed config file: back it up and fall back to
            # defaults so the application can still start. ValueError covers
            # json.JSONDecodeError raised while parsing the file.
            settings, persistable = cls._recover_from_invalid_config(json_file, exc)

        # Only persist settings that came through validation. An emergency
        # fallback may be a ``model_construct`` result that skipped validation
        # entirely; writing that to disk would make it the authoritative config
        # and could loop the app through recovery on the next launch.
        if persistable and not json_file.exists():
            cls._write_settings(json_file, settings)

        return settings

    @staticmethod
    def _warn_user(message: str) -> None:
        """Print a one-line warning to stderr.

        Config loading and the first-run write both happen *before* logging is
        configured (see ``application.Keycast.__init__``), so a ``logger`` call
        here would go nowhere the user can see. Writing to stderr guarantees the
        message is observable when something goes wrong with their config.

        Args:
            message: The user-facing message to print.
        """
        print(message, file=sys.stderr)

    @classmethod
    def _recover_from_invalid_config(
        cls, json_file: Path, exc: Exception
    ) -> "tuple[Settings, bool]":
        """Back up an invalid config file and return settings from defaults.

        The backup never overwrites a previous one (a timestamp suffix keeps the
        first, recoverable copy intact), and a failure to back up degrades to
        in-memory defaults rather than crashing startup.

        Args:
            json_file: Path to the (invalid) config file.
            exc: The error raised while loading it.

        Returns:
            A ``(settings, persistable)`` pair. ``persistable`` is ``True`` only
            when the settings came back through validation (a clean re-load) and
            are therefore safe to write to disk; it is ``False`` for the
            emergency ``_safe_defaults`` fallbacks, which must not be persisted.
        """
        logger = logging.getLogger(__name__)

        if json_file.exists():
            backup = json_file.with_name(f"{json_file.name}.{int(time.time())}.bak")
            try:
                json_file.replace(backup)
            except OSError:
                logger.exception(
                    "Invalid config at %s (%s) could not be backed up; "
                    "starting from in-memory defaults without persisting",
                    json_file,
                    exc,
                )
                # Recovery runs before logging is configured, so also surface
                # this to the user directly; otherwise the failure is silent.
                cls._warn_user(
                    f"keycast: config at {json_file} is invalid ({exc}) and could "
                    "not be backed up; using built-in defaults for this session."
                )
                return cls._safe_defaults(), False
            logger.warning(
                "Invalid config at %s (%s); backed up to %s and using defaults",
                json_file,
                exc,
                backup,
            )
            cls._warn_user(
                f"keycast: config at {json_file} was invalid ({exc}); it was backed "
                f"up to {backup} and built-in defaults are now in use."
            )

        # The bad file has been moved aside (or never existed), so loading again
        # should yield clean defaults. Guard against defaults themselves failing.
        try:
            return cls(), True
        except (ValidationError, ValueError) as retry_exc:
            logger.exception(
                "Default settings failed to load; using in-memory defaults"
            )
            # Like the other recovery branches, surface this to stderr: it
            # happens before logging is configured, so the logger call above
            # goes nowhere the user can see.
            cls._warn_user(
                f"keycast: could not load settings even after recovery "
                f"({retry_exc}); using built-in defaults for this session."
            )
            return cls._safe_defaults(), False

    @classmethod
    def _safe_defaults(cls) -> "Settings":
        """Return a defaults-only ``Settings``, validated where possible.

        Prefers ``model_validate({})`` so the recovery result still passes field
        validation (bounds, the log-format check, etc.) and cannot itself violate
        the invariants the type promises. ``model_validate`` does not consult the
        configured sources, so it bypasses the corrupt file that triggered
        recovery (a load-bearing assumption about pydantic-settings — if it ever
        changed, recovery would re-read the corrupt file and loop; the recovery
        tests in ``tests/test_settings.py`` pin it). Only if validating the bare
        defaults somehow fails does it fall back to ``model_construct``, which
        skips validation entirely, as an absolute last resort to keep the
        application starting.

        Returns:
            A settings object built from defaults.
        """
        try:
            return cls.model_validate({})
        except (ValidationError, ValueError) as exc:
            logger = logging.getLogger(__name__)
            logger.exception(
                "Default settings failed validation; using unvalidated defaults"
            )
            # This is the most degraded state the app can reach (an unvalidated
            # config), and it runs before logging is configured, so the log line
            # above is invisible. Surface it to the user like the other recovery
            # branches; otherwise the worst failure mode is the only silent one.
            cls._warn_user(
                f"keycast: built-in default settings failed validation ({exc}); "
                "starting with unvalidated defaults for this session."
            )
            return cls.model_construct()

    @classmethod
    def _write_settings(cls, json_file: Path, settings: "Settings") -> None:
        """Atomically write settings to ``json_file``.

        Writes to a temporary file in the same directory and replaces the target
        in a single ``os.replace`` so a crash mid-write cannot leave a truncated
        (and therefore corrupt) config behind.

        Args:
            json_file: Destination path.
            settings: The settings to serialize.
        """
        logger = logging.getLogger(__name__)
        try:
            json_file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=json_file.parent, suffix=".tmp")
            # Clean up the temp file on *any* failure, not just OSError: a
            # serialization error from model_dump_json would otherwise leave an
            # orphaned ``*.tmp`` in ~/.keycast on every failed launch.
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                    tmp_file.write(settings.model_dump_json())
                os.replace(tmp_name, json_file)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except Exception as exc:
            # Persisting the config is best-effort: a failure here must not stop
            # the application from starting. This deliberately catches more than
            # OSError (e.g. a serialization failure) so that no write problem
            # crashes startup; the app simply runs with in-memory defaults.
            logger.exception(
                "Could not write config file %s; continuing without persisting",
                json_file,
            )
            # First-run persistence happens before logging is configured, so
            # surface the failure to the user too (e.g. read-only home, full
            # disk) instead of failing silently every launch.
            cls._warn_user(
                f"keycast: could not save config to {json_file} ({exc}); "
                "continuing with defaults but settings will not persist."
            )
