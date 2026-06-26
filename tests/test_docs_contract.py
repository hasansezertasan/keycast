"""Guards that the public API described in ``docs/`` and ``README.md`` stays true.

These tests exist because the documentation drifted badly once already: classes
were renamed (``KeyDisplayWindow`` -> ``DisplayWindow``), constructor parameters
changed (``on_key_press`` -> ``show_text``), and orchestration moved out of
``main`` into :class:`keycast.application.Keycast` -- none of which the docs
tracked, leaving copy-paste examples that raised ``TypeError``.

They assert only the surface the docs make promises about (importable symbols,
constructor parameter names, and that documented settings fields stay present and
in sync with the docs). They are intentionally annotation-free at the inspection
layer: ``co_varnames`` is read directly so PEP 649 deferred annotations (and
``TYPE_CHECKING``-only imports) cannot break introspection.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from keycast.application import Keycast
from keycast.display import DisplayWindow
from keycast.listeners import KeyListener, MouseListener
from keycast.settings import (
    CONFIG_FILE_PATH,
    LOG_FILE_PATH,
    DisplaySettings,
    KeyboardSettings,
    LoggingSettings,
    MouseSettings,
    Settings,
    _default_key_mappings,
)


def _positional_params(func: Callable[..., Any]) -> list[str]:
    """Return a callable's positional parameter names, excluding ``self``."""
    code = func.__code__
    return list(code.co_varnames[: code.co_argcount])[1:]


class TestDocumentedConstructors:
    """Constructor signatures the docs hand to users in copy-paste examples."""

    def test_key_listener_takes_show_text_and_settings(self) -> None:
        assert _positional_params(KeyListener.__init__) == ["show_text", "settings"]

    def test_mouse_listener_takes_show_text_and_settings(self) -> None:
        assert _positional_params(MouseListener.__init__) == ["show_text", "settings"]

    def test_display_window_takes_settings_only(self) -> None:
        assert _positional_params(DisplayWindow.__init__) == ["settings"]


class TestDocumentedPublicApi:
    """Symbols and methods the docs reference by name."""

    def test_display_window_sink_and_lifecycle_methods(self) -> None:
        for name in ("show_text", "start", "request_stop", "stop"):
            assert callable(getattr(DisplayWindow, name)), name

    def test_keycast_lifecycle_methods(self) -> None:
        for name in ("start", "stop", "run", "signal_handler"):
            assert callable(getattr(Keycast, name)), name

    def test_settings_factory_classmethod(self) -> None:
        assert callable(getattr(Settings, "create_settings_file"))

    def test_plain_callable_satisfies_text_sink(self) -> None:
        # The docs promise any ``Callable[[str], None]`` is a valid sink; the
        # listener stores it and exposes it as a callable ``show_text``.
        captured: list[str] = []
        listener = KeyListener(show_text=captured.append, settings=KeyboardSettings())
        assert callable(listener.show_text)
        listener.show_text("A")
        assert captured == ["A"]


class TestAppLevelFlagsAreDocumented:
    """The implemented top-level scalar flags must stay present and documented.

    ``debug`` (#2), ``start_minimized`` (#3) and ``auto_start`` (#4) were once
    stubbed-then-removed to avoid documenting absent behavior; now that they are
    wired up, this pins them so a future removal forces a docs update too. The
    declared defaults are checked (rather than ``Settings()``, which would read
    the real ``~/.keycast/config.json`` via the JSON source).
    """

    def test_app_level_flags_present_with_defaults(self) -> None:
        expected_defaults = {
            "debug": False,
            "start_minimized": False,
            "auto_start": True,
            "check_for_updates": True,
        }
        for field, default in expected_defaults.items():
            assert field in Settings.model_fields, field
            assert Settings.model_fields[field].default is default, field

    def test_display_draggable_present_and_off_by_default(self) -> None:
        assert "draggable" in DisplaySettings.model_fields
        assert DisplaySettings.model_fields["draggable"].default is False

    def test_settings_sections_are_exactly_documented(self) -> None:
        # The four sections every doc lists, plus the four top-level scalar flags
        # -- nothing more, nothing less. The scalars are flags, not sections.
        documented_sections = {"display", "keyboard", "mouse", "logging"}
        scalar_flags = {"debug", "start_minimized", "auto_start", "check_for_updates"}
        assert set(Settings.model_fields) == documented_sections | scalar_flags


class TestDocumentedDefaultLabels:
    """Default key labels the docs quote verbatim must match what ships.

    The docs once claimed modifiers render as ``"Ctrl"``/``"Cmd"`` and characters
    "as uppercase"; the code actually ships ``"Control Left"`` etc. and returns
    characters verbatim. These assertions pin the platform-stable labels the API
    reference and README spell out, so prose can't silently diverge again.
    """

    def test_platform_stable_default_labels(self) -> None:
        mappings = _default_key_mappings()
        expected = {
            "ctrl": "Control Left",
            "ctrl_l": "Control Left",
            "ctrl_r": "Control Right",
            "alt": "Alt Left",
            "shift": "Shift Left",
            "space": "Space Bar",
            "enter": "Enter",
        }
        for name, label in expected.items():
            assert mappings[name] == label, name

    def test_modifiers_are_not_abbreviated(self) -> None:
        # Guards against regressing to the old "Ctrl"/"Alt"/"Shift" doc claim.
        mappings = _default_key_mappings()
        for name in ("ctrl", "alt", "shift"):
            assert mappings[name] not in ("Ctrl", "Alt", "Shift"), name


class TestDocumentedLoggingBehavior:
    """Logging defaults and paths the API reference / README state literally.

    The docs once claimed ``file_path`` defaults to ``None`` (console only); the
    code actually ships ``~/.keycast/main.log`` (file logging on by default).
    These pin the corrected claims.
    """

    def test_file_path_defaults_to_log_file_not_none(self) -> None:
        assert LoggingSettings().file_path == LOG_FILE_PATH
        assert LoggingSettings().file_path is not None

    def test_log_file_location(self) -> None:
        assert LOG_FILE_PATH.name == "main.log"
        assert LOG_FILE_PATH.parent.name == ".keycast"

    def test_rotation_defaults(self) -> None:
        settings = LoggingSettings()
        assert settings.level == "INFO"
        assert settings.max_file_size_mb == 10
        assert settings.backup_count == 5

    def test_config_backup_name_stem(self) -> None:
        # The docs promise corrupt configs back up to ``config.json.<epoch>.bak``;
        # that literal depends on the config file being named ``config.json``.
        assert CONFIG_FILE_PATH.name == "config.json"


class TestDocumentedSettingsClasses:
    """The settings classes the API reference enumerates all import."""

    def test_all_settings_classes_importable(self) -> None:
        for cls in (
            Settings,
            DisplaySettings,
            KeyboardSettings,
            MouseSettings,
            LoggingSettings,
        ):
            assert isinstance(cls, type)


_PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def _coord_pair(text: str, pattern: str) -> tuple[int, int]:
    """Extract a two-int ``(x, y)`` tuple matched by ``pattern`` (two groups)."""
    m = re.search(pattern, text)
    assert m is not None, f"pattern not found: {pattern}"
    return int(m.group(1)), int(m.group(2))


class TestDmgBackgroundCoordinateContract:
    """The .dmg background and dmgbuild layout share one coordinate system.

    ``make_dmg_background.py`` hard-codes ``APP_CENTER``/``APPS_CENTER`` and the
    window size, then draws the drag arrow into the gap between those centres;
    ``dmg_settings.py`` independently lists ``icon_locations`` and
    ``window_rect``. Nothing at runtime links the two -- move an icon in the
    settings file and the committed background's arrow misaligns silently. Both
    files carry comments asserting they MUST match; these tests are the
    enforcement. They parse the source textually because neither module is
    importable here (``dmg_settings.py`` needs dmgbuild's injected ``defines``;
    ``make_dmg_background.py`` needs Pillow, not a project dependency).
    """

    def _settings_src(self) -> str:
        return (_PACKAGING / "dmg_settings.py").read_text(encoding="utf-8")

    def _background_src(self) -> str:
        return (_PACKAGING / "make_dmg_background.py").read_text(encoding="utf-8")

    def test_icon_centres_match(self) -> None:
        settings, background = self._settings_src(), self._background_src()
        # dmg_settings.py: appname -> (x, y); Applications -> (x, y)
        app_loc = _coord_pair(settings, r"appname:\s*\((\d+),\s*(\d+)\)")
        apps_loc = _coord_pair(settings, r'"Applications":\s*\((\d+),\s*(\d+)\)')
        # make_dmg_background.py: APP_CENTER / APPS_CENTER
        app_centre = _coord_pair(background, r"APP_CENTER\s*=\s*\((\d+),\s*(\d+)\)")
        apps_centre = _coord_pair(
            background, r"APPS_CENTER\s*=\s*\((\d+),\s*(\d+)\)"
        )
        assert app_loc == app_centre
        assert apps_loc == apps_centre

    def test_window_size_matches(self) -> None:
        # window_rect = ((x, y), (w, h)) in settings vs WIN_W, WIN_H in generator.
        win = _coord_pair(
            self._settings_src(),
            r"window_rect\s*=\s*\(\(\d+,\s*\d+\),\s*\((\d+),\s*(\d+)\)\)",
        )
        gen = _coord_pair(
            self._background_src(), r"WIN_W,\s*WIN_H\s*=\s*(\d+),\s*(\d+)"
        )
        assert win == gen

    def test_arrow_stays_in_the_icon_gap(self) -> None:
        # The arrow's hard-coded x-span must sit between the two icon edges, or
        # it overlaps the icons Finder paints on top. icon_size is the full
        # width; centres are the icon midpoints.
        settings, background = self._settings_src(), self._background_src()
        icon_size = int(re.search(r"icon_size\s*=\s*(\d+)", settings).group(1))  # type: ignore[union-attr]
        app_x = _coord_pair(settings, r"appname:\s*\((\d+),\s*(\d+)\)")[0]
        apps_x = _coord_pair(settings, r'"Applications":\s*\((\d+),\s*(\d+)\)')[0]
        x0, x1 = _coord_pair(background, r"x0,\s*x1\s*=\s*round\((\d+).*?round\((\d+)")
        assert app_x + icon_size // 2 <= x0, "arrow starts under the app icon"
        assert x1 <= apps_x - icon_size // 2, "arrow ends under /Applications"
