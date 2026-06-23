"""Tests for the settings module (load, recovery, creation, invariants)."""

import json
import os
import platform
from pathlib import Path

import pytest
from pydantic import ValidationError

from keycast.settings import (
    DisplaySettings,
    KeyboardSettings,
    LoggingSettings,
    MouseSettings,
    Settings,
    _default_key_mappings,
    is_bare_key_name,
    is_button_string,
)


class TestImportContract:
    """Guards that the module imports and constructs on the running interpreter.

    A smoke test that fails fast if ``settings.py`` ever stops importing or
    constructing (e.g. a syntax error or a broken default), so that class of
    breakage can't slip through.
    """

    def test_settings_constructs_with_validation(self) -> None:
        settings = Settings()
        assert settings.display.width == DisplaySettings().width

    def test_model_construct_populates_nested_defaults(self) -> None:
        """The last-resort recovery path relies on nested models being present."""
        settings = Settings.model_construct()
        assert isinstance(settings.display, DisplaySettings)
        assert isinstance(settings.keyboard, KeyboardSettings)
        assert isinstance(settings.mouse, MouseSettings)
        assert isinstance(settings.logging, LoggingSettings)


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Settings at a throwaway config file inside tmp_path.

    Patches the ``json_file`` in ``Settings.model_config`` so both
    ``JsonConfigSettingsSource`` and ``create_settings_file`` use it.

    Returns:
        The path the settings will be loaded from / written to.
    """
    path = tmp_path / "config.json"
    monkeypatch.setitem(Settings.model_config, "json_file", path)
    return path


class TestPlatformKeyLabels:
    """Default Super/Command/Windows labels adapt to the host platform."""

    @pytest.mark.parametrize(
        ("system", "left", "right"),
        [
            ("Darwin", "Command Left", "Command Right"),
            ("Windows", "Windows Left", "Windows Right"),
            ("Linux", "Super Left", "Super Right"),
        ],
    )
    def test_super_key_labels_per_platform(
        self,
        monkeypatch: pytest.MonkeyPatch,
        system: str,
        left: str,
        right: str,
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: system)

        mappings = _default_key_mappings()

        assert mappings["cmd"] == left
        assert mappings["cmd_l"] == left
        assert mappings["cmd_r"] == right
        # Non-platform-specific labels are unaffected.
        assert mappings["ctrl_l"] == "Control Left"

    def test_alt_gr_maps_to_alt_right(self) -> None:
        """The documented ``alt_gr`` → "Alt Right" mapping is present.

        ``alt_gr`` is the right-Alt name pynput reports on Windows/X11 (inert on
        macOS, where it aliases ``alt_r``). It is documented in
        ``_default_key_mappings`` but otherwise only covered as a dict line, so
        pin the label ``_format_key`` would resolve it to.
        """
        assert _default_key_mappings()["alt_gr"] == "Alt Right"


class TestFieldInvariants:
    """Pydantic Field constraints reject out-of-range values."""

    def test_display_width_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DisplaySettings(width=50)  # below ge=100

    def test_display_alpha_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DisplaySettings(alpha=2.0)  # above le=1.0

    def test_logging_level_literal_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoggingSettings(level="TRACE")  # type: ignore[arg-type]

    def test_max_file_size_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoggingSettings(max_file_size_mb=0)  # below ge=1

    def test_empty_font_family_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DisplaySettings(font_family="")  # below min_length=1

    def test_position_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DisplaySettings(x_position=50000)  # above le=20000

    def test_x_position_center_literal_accepted(self) -> None:
        assert DisplaySettings(x_position="center").x_position == "center"

    def test_x_position_unknown_string_rejected(self) -> None:
        # Only the named "center" value is allowed; any other string is invalid.
        with pytest.raises(ValidationError):
            DisplaySettings(x_position="left")

    def test_y_position_has_no_center_option(self) -> None:
        # The x/y asymmetry is intentional: only x supports "center" (the only
        # centering DisplayWindow implements). y is int-only, so "center" must be
        # rejected. Pins the documented asymmetry against accidental symmetry.
        with pytest.raises(ValidationError):
            DisplaySettings(y_position="center")

    def test_invalid_log_format_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoggingSettings(format="%(nonexistent)q")  # invalid logging format

    def test_valid_log_format_accepted(self) -> None:
        settings = LoggingSettings(format="%(levelname)s: %(message)s")
        assert settings.format == "%(levelname)s: %(message)s"

    def test_settings_models_are_frozen(self) -> None:
        """Frozen models reject post-construction mutation."""
        for model in (
            DisplaySettings(),
            KeyboardSettings(),
            MouseSettings(),
            LoggingSettings(),
        ):
            with pytest.raises(ValidationError):
                model.enabled = False  # type: ignore[attr-defined]

    def test_mapping_fields_are_read_only(self) -> None:
        """The mapping fields are exposed as read-only views, not mutable dicts.

        ``frozen=True`` blocks rebinding the field; wrapping the value in a
        ``MappingProxyType`` additionally blocks mutating its *contents*, so a
        caller cannot silently corrupt shared settings state.
        """
        keyboard = KeyboardSettings()
        mouse = MouseSettings(button_names={"Button.left": "LMB"})

        with pytest.raises(TypeError):
            keyboard.key_mappings["space"] = "Mutated"  # type: ignore[index]
        with pytest.raises(TypeError):
            mouse.button_names["Button.left"] = "Mutated"  # type: ignore[index]

    def test_mapping_fields_round_trip_through_json(self) -> None:
        """The read-only mappings serialize to JSON and reload unchanged."""
        original = KeyboardSettings(key_mappings={"ctrl_l": "Control", "space": "Sp"})
        reloaded = KeyboardSettings.model_validate_json(original.model_dump_json())

        assert reloaded.key_mappings == {"ctrl_l": "Control", "space": "Sp"}


class TestCreateSettingsFile:
    """Behavior of Settings.create_settings_file."""

    def test_first_run_writes_defaults(self, config_path: Path) -> None:
        """With no file present, defaults are written atomically to disk."""
        assert not config_path.exists()

        settings = Settings.create_settings_file()

        assert config_path.exists()
        # The written file is valid JSON that round-trips back to defaults.
        on_disk = json.loads(config_path.read_text())
        assert on_disk["display"]["width"] == settings.display.width
        # The atomic write (tempfile + os.replace) leaves no stray temp file
        # behind on the success path, just as the failure path cleans up.
        assert list(config_path.parent.glob("*.tmp")) == []

    def test_valid_file_is_loaded(self, config_path: Path) -> None:
        """An existing valid config overrides the defaults."""
        config_path.write_text(json.dumps({"display": {"width": 777}}))

        settings = Settings.create_settings_file()

        assert settings.display.width == 777

    def test_corrupt_file_is_backed_up_and_defaults_used(
        self, config_path: Path
    ) -> None:
        """Malformed JSON is moved aside and defaults take over."""
        config_path.write_text("{ this is not valid json ")

        settings = Settings.create_settings_file()

        # Defaults are returned, the app can still start.
        assert settings.display.width == DisplaySettings().width
        # The corrupt file was moved to a timestamped .bak (original gone).
        backups = list(config_path.parent.glob("config.json.*.bak"))
        assert len(backups) == 1
        assert "not valid json" in backups[0].read_text()

    def test_backup_does_not_clobber_previous_backup(self, config_path: Path) -> None:
        """A pre-existing .bak is preserved (no data loss across bad starts)."""
        existing = config_path.parent / "config.json.111.bak"
        existing.write_text("precious original")
        config_path.write_text("{ broken ")

        Settings.create_settings_file()

        assert existing.read_text() == "precious original"

    def test_backup_failure_falls_back_to_defaults(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the file can't be backed up, start from defaults rather than crash."""
        config_path.write_text("{ broken ")

        def boom(self: Path, target: Path) -> None:
            raise OSError("read-only filesystem")

        monkeypatch.setattr(Path, "replace", boom)

        settings = Settings.create_settings_file()

        assert settings.display.width == DisplaySettings().width

    def test_corrupt_file_warns_user_on_stderr(
        self, config_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Recovery happens before logging is set up, so warn on stderr too."""
        config_path.write_text("{ broken ")

        Settings.create_settings_file()

        err = capsys.readouterr().err
        assert "keycast:" in err
        assert str(config_path) in err

    def test_write_failure_warns_user_and_does_not_crash(
        self,
        config_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A failed first-run write surfaces to the user and leaves no temp file."""

        def boom(src: str, dst: str) -> None:
            raise OSError("read-only filesystem")

        monkeypatch.setattr(os, "replace", boom)

        # Must not raise even though persistence fails.
        settings = Settings.create_settings_file()

        assert settings.display.width == DisplaySettings().width
        assert not config_path.exists()
        # The atomic-write temp file is cleaned up on failure.
        assert list(config_path.parent.glob("*.tmp")) == []
        assert "could not save config" in capsys.readouterr().err

    def test_default_colors_survive_write_and_reload(self, config_path: Path) -> None:
        """Color fields round-trip through the first-run write + reload.

        create_settings_file serializes the defaults (including Color fields) on
        first run, then a later run parses them back. This guards against a Color
        that serializes to a form which does not re-parse to the same value.
        """
        first = Settings.create_settings_file()
        second = Settings.create_settings_file()

        assert second.display.background_color == first.display.background_color
        assert second.display.text_color == first.display.text_color

    def test_custom_colors_round_trip_through_config(self, config_path: Path) -> None:
        """User-specified colors in the config load back to the same value."""
        config_path.write_text(
            json.dumps({"display": {"background_color": "red", "text_color": "lime"}})
        )

        loaded = Settings.create_settings_file()

        assert (
            loaded.display.background_color
            == DisplaySettings(background_color="red").background_color
        )
        assert (
            loaded.display.text_color == DisplaySettings(text_color="lime").text_color
        )

    def test_recovery_uses_validated_defaults_when_load_always_fails(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even if every full load fails, startup recovers via validated defaults.

        Forces ``Settings()`` to always raise so the post-backup retry in
        _recover_from_invalid_config also fails, driving the _safe_defaults path.
        model_validate (used by _safe_defaults) does not go through __init__, so
        it still produces a usable, validated settings object.
        """

        def always_fail(self: Settings, *args: object, **kwargs: object) -> None:
            raise ValueError("load always fails")

        monkeypatch.setattr(Settings, "__init__", always_fail)

        settings = Settings.create_settings_file()

        assert settings.display.width == DisplaySettings().width

    def test_unvalidated_fallback_is_not_persisted(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An emergency fallback (possibly unvalidated) is never written to disk.

        When the post-backup reload also fails, recovery returns a
        ``_safe_defaults`` object that may have skipped validation. Persisting it
        would make an unvalidated config authoritative and could loop the app
        through recovery next launch, so ``create_settings_file`` must not write
        it: the corrupt file is moved to a backup and *not* replaced.
        """
        config_path.write_text("{ broken ")

        # Force both the initial load and the post-backup retry to fail so
        # recovery reaches _safe_defaults; model_validate bypasses __init__ and
        # still yields a usable object.
        def always_fail(self: Settings, *args: object, **kwargs: object) -> None:
            raise ValueError("load always fails")

        monkeypatch.setattr(Settings, "__init__", always_fail)

        settings = Settings.create_settings_file()

        assert settings.display.width == DisplaySettings().width
        # Backed up, but no fresh config written in its place.
        assert not config_path.exists()
        backups = list(config_path.parent.glob("config.json.*.bak"))
        assert len(backups) == 1

    def test_unset_json_file_raises_type_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(Settings.model_config, "json_file", None)
        with pytest.raises(TypeError):
            Settings.create_settings_file()

    def test_non_path_json_file_raises_type_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(Settings.model_config, "json_file", "config.json")
        with pytest.raises(TypeError):
            Settings.create_settings_file()


class TestSafeDefaults:
    """Behavior of the Settings._safe_defaults recovery helper."""

    def test_returns_validated_defaults(self) -> None:
        """The normal path returns a fully-populated, validated settings object."""
        settings = Settings._safe_defaults()

        assert settings.display.width == DisplaySettings().width
        assert isinstance(settings.keyboard, KeyboardSettings)

    def test_falls_back_to_model_construct_when_validation_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If validating bare defaults fails, fall back to model_construct."""

        def boom(*args: object, **kwargs: object) -> None:
            raise ValueError("validation unavailable")

        monkeypatch.setattr(Settings, "model_validate", boom)

        settings = Settings._safe_defaults()

        # model_construct still yields the nested default models.
        assert isinstance(settings.display, DisplaySettings)
        assert isinstance(settings.logging, LoggingSettings)

    def test_model_construct_fallback_warns_user_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The unvalidated last resort surfaces to the user, not just the log.

        This is the most degraded state the app can reach and runs before logging
        is configured, so — like the other recovery branches — it must warn on
        stderr; otherwise the worst failure mode would be the only silent one.
        """

        def boom(*args: object, **kwargs: object) -> None:
            raise ValueError("validation unavailable")

        monkeypatch.setattr(Settings, "model_validate", boom)

        Settings._safe_defaults()

        err = capsys.readouterr().err
        assert "keycast:" in err
        assert "unvalidated defaults" in err


class TestButtonNamesValidation:
    """The button_names mapping is validated at config load."""

    def test_valid_button_key_accepted(self) -> None:
        settings = MouseSettings(button_names={"Button.left": "Primary Click"})
        assert settings.button_names["Button.left"] == "Primary Click"

    def test_key_without_button_prefix_rejected(self) -> None:
        """A key that can never match str(button) is rejected, not silently inert."""
        with pytest.raises(ValidationError):
            MouseSettings(button_names={"left": "Primary Click"})

    def test_invalid_button_names_in_config_trigger_recovery(
        self, config_path: Path
    ) -> None:
        """A config with bad button keys is treated as corrupt and recovered."""
        config_path.write_text(
            json.dumps({"mouse": {"button_names": {"left": "Primary"}}})
        )

        settings = Settings.create_settings_file()

        # Recovery falls back to defaults (empty mapping) instead of crashing.
        assert settings.mouse.button_names == {}
        backups = list(config_path.parent.glob("config.json.*.bak"))
        assert len(backups) == 1


class TestKeyMappingsValidation:
    """The key_mappings mapping is validated at config load."""

    def test_valid_bare_key_accepted(self) -> None:
        settings = KeyboardSettings(key_mappings={"ctrl_l": "Control", "space": "Sp"})
        assert settings.key_mappings["ctrl_l"] == "Control"

    def test_key_with_prefix_rejected(self) -> None:
        """A "Key."-prefixed name can never match key.name, so it is rejected."""
        with pytest.raises(ValidationError):
            KeyboardSettings(key_mappings={"Key.ctrl": "Control"})

    def test_capitalized_key_rejected(self) -> None:
        """pynput names are lowercase; a capitalized key would silently no-op."""
        with pytest.raises(ValidationError):
            KeyboardSettings(key_mappings={"Ctrl": "Control"})

    def test_invalid_key_mappings_in_config_trigger_recovery(
        self, config_path: Path
    ) -> None:
        """A config with bad key_mappings keys is recovered, not crashed."""
        config_path.write_text(
            json.dumps({"keyboard": {"key_mappings": {"Ctrl": "Control"}}})
        )

        settings = Settings.create_settings_file()

        # Recovery falls back to the default mappings instead of crashing.
        assert settings.keyboard.key_mappings == _default_key_mappings()
        backups = list(config_path.parent.glob("config.json.*.bak"))
        assert len(backups) == 1


class TestMappingKeyGrammar:
    """The shared predicates that define the mapping-key grammars.

    These are the single source of truth that both the config validators and the
    listener lookups derive from, so the validated key shape and the runtime
    lookup key shape cannot drift apart.
    """

    def test_is_bare_key_name_accepts_pynput_key_name_shape(self) -> None:
        """Lowercase, prefix-free names (the shape of Key.name) are accepted."""
        assert is_bare_key_name("ctrl_l")
        assert is_bare_key_name("space")
        assert is_bare_key_name("f1")

    def test_is_bare_key_name_rejects_prefixed_or_capitalized(self) -> None:
        """A "Key." prefix or any uppercase cannot match key.name."""
        assert not is_bare_key_name("Key.ctrl")
        assert not is_bare_key_name("Ctrl")

    def test_is_button_string_accepts_pynput_button_shape(self) -> None:
        """The Button.<name> shape (the shape of str(Button)) is accepted."""
        assert is_button_string("Button.left")
        assert is_button_string("Button.x2")

    def test_is_button_string_rejects_unprefixed(self) -> None:
        """A key without the Button. prefix cannot match str(button)."""
        assert not is_button_string("left")

    def test_validator_and_predicate_agree(self) -> None:
        """The validators accept exactly what the predicates accept.

        Pins that the validators are wired to the shared predicates: a key the
        predicate accepts validates, and one it rejects raises.
        """
        KeyboardSettings(key_mappings={"ctrl_l": "Control"})  # predicate-true: ok
        MouseSettings(button_names={"Button.left": "Primary"})  # predicate-true: ok
        with pytest.raises(ValidationError):
            KeyboardSettings(key_mappings={"Key.ctrl": "Control"})  # predicate-false
        with pytest.raises(ValidationError):
            MouseSettings(button_names={"left": "Primary"})  # predicate-false


class TestMousePositionRequiresClicks:
    """show_mouse_position only renders alongside show_mouse_clicks."""

    def test_position_with_clicks_accepted(self) -> None:
        settings = MouseSettings(show_mouse_clicks=True, show_mouse_position=True)
        assert settings.show_mouse_position is True

    def test_position_without_clicks_rejected(self) -> None:
        """position-without-clicks is inert, so it is a config error, not a no-op."""
        with pytest.raises(ValidationError):
            MouseSettings(show_mouse_clicks=False, show_mouse_position=True)

    def test_neither_flag_is_valid(self) -> None:
        """Disabling both is a legitimate (clicks-off) configuration."""
        settings = MouseSettings(show_mouse_clicks=False, show_mouse_position=False)
        assert settings.show_mouse_position is False

    def test_inert_combination_in_config_triggers_recovery(
        self, config_path: Path
    ) -> None:
        """A config with the inert combination is treated as corrupt and recovered."""
        config_path.write_text(
            json.dumps(
                {"mouse": {"show_mouse_clicks": False, "show_mouse_position": True}}
            )
        )

        settings = Settings.create_settings_file()

        # Recovery falls back to defaults instead of crashing.
        assert settings.mouse.show_mouse_position is False
        backups = list(config_path.parent.glob("config.json.*.bak"))
        assert len(backups) == 1


class TestStartMinimizedRequiresAutoStart:
    """``start_minimized`` is inert without ``auto_start``; the model rejects it.

    With no listeners running (``auto_start`` off) nothing is ever captured, so a
    minimized overlay would never reappear. The validator turns that silently
    inert combination into a visible error, like the mouse position/clicks rule.
    """

    def test_minimized_without_autostart_is_rejected(self) -> None:
        # Settings is a BaseSettings, so model_validate(dict) ignores supplied
        # values (it reads the JSON source). Build unvalidated with model_construct
        # and invoke the after-validator directly to exercise the rule.
        settings = Settings.model_construct(start_minimized=True, auto_start=False)
        with pytest.raises(ValueError, match="start_minimized requires auto_start"):
            settings._validate_minimized_requires_autostart()

    def test_minimized_with_autostart_is_accepted(self) -> None:
        settings = Settings.model_construct(start_minimized=True, auto_start=True)
        assert settings._validate_minimized_requires_autostart() is settings

    def test_inert_combo_in_config_is_recovered(self, config_path: Path) -> None:
        # End-to-end: an on-disk config with the inert combo fails validation, so
        # create_settings_file treats it as corrupt, backs it up, and uses
        # defaults (mirrors the mouse show_mouse_position recovery test).
        config_path.write_text(
            json.dumps({"start_minimized": True, "auto_start": False})
        )

        settings = Settings.create_settings_file()

        assert settings.start_minimized is False
        assert settings.auto_start is True
        backups = list(config_path.parent.glob("config.json.*.bak"))
        assert len(backups) == 1


class TestEffectiveLogging:
    """How ``Settings.debug`` resolves into the applied ``LoggingSettings``.

    These tests pin the *recommended* policy: ``debug`` is an override that
    forces verbose (DEBUG) logging when on, and is a no-op when off. They drive
    the implementation of ``Settings.effective_logging`` (issue #2). If you pick
    a different policy when writing that method, update these assertions to match
    the policy you chose.

    ``model_construct`` sets ``debug``/``logging`` directly: ``Settings`` reads
    config from the JSON source only (see ``settings_customise_sources``), so
    ``model_validate(dict)`` would ignore these values and load defaults instead.
    """

    def test_debug_off_leaves_logging_unchanged(self) -> None:
        logging_settings = LoggingSettings(level="WARNING")
        settings = Settings.model_construct(debug=False, logging=logging_settings)
        assert settings.effective_logging() == logging_settings

    def test_debug_on_forces_debug_level(self) -> None:
        settings = Settings.model_construct(
            debug=True, logging=LoggingSettings(level="WARNING")
        )
        assert settings.effective_logging().level == "DEBUG"

    def test_debug_on_preserves_other_logging_fields(self) -> None:
        # Only the level should change; format, file_path, rotation are untouched.
        logging_settings = LoggingSettings(level="ERROR", backup_count=7)
        settings = Settings.model_construct(debug=True, logging=logging_settings)
        effective = settings.effective_logging()
        assert effective.level == "DEBUG"
        assert effective.backup_count == 7
        assert effective.format == logging_settings.format
