"""Tests for the logging_setup module."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest

from keycast.logging_setup import format_event, setup_logging
from keycast.settings import LoggingSettings


class TestFormatEvent:
    """Test cases for the format_event structured-log helper."""

    def test_no_fields_returns_bare_event(self) -> None:
        """With no fields the event name is returned unchanged."""
        assert format_event("keyboard_listener_started") == "keyboard_listener_started"

    def test_whitespace_free_values_stay_bare(self) -> None:
        """Tokens without whitespace are rendered as plain key=value pairs."""
        assert (
            format_event("listener_event", kind="keyboard", count=3)
            == "listener_event kind=keyboard count=3"
        )

    def test_whitespace_values_are_repr_quoted(self) -> None:
        """A value containing whitespace is repr-quoted to stay one token.

        This keeps each field a single whitespace-delimited token so the log
        stays greppable (e.g. ``grep key=`` would otherwise split on the space).
        """
        assert format_event("key_press", key="Control Left") == (
            "key_press key='Control Left'"
        )

    def test_tab_and_newline_values_are_repr_quoted(self) -> None:
        """Any whitespace (not just a space) triggers quoting.

        A tab or newline would otherwise break the single-token contract just as
        a space does — ``repr`` renders them as ``\\t``/``\\n`` inside quotes so
        the field stays one greppable token.
        """
        assert format_event("evt", value="a\tb") == "evt value='a\\tb'"
        assert format_event("evt", value="a\nb") == "evt value='a\\nb'"

    def test_non_string_value_with_whitespace_is_repr_quoted(self) -> None:
        """The whitespace check uses ``str(value)`` but renders with ``repr``.

        Fields receive arbitrary objects (e.g. pynput key/button reprs), so a
        non-string whose ``str`` contains whitespace must still be quoted as a
        single token.
        """
        assert format_event("evt", pos=(1, 2)) == "evt pos=(1, 2)"

    def test_empty_value_is_repr_quoted(self) -> None:
        """An empty value is quoted so it does not render as a bare ``key=``.

        Keystroke/click context can be empty; a bare ``key=`` looks like a
        missing value, so ``repr`` renders it as ``key=''`` to stay an
        unambiguous single token.
        """
        assert format_event("evt", key="") == "evt key=''"

    def test_value_containing_equals_is_repr_quoted(self) -> None:
        """A value containing ``=`` is quoted so the token stays unambiguous.

        Without quoting, ``key=a=b`` is ambiguous about where the value starts;
        ``repr`` keeps the whole value one greppable token.
        """
        assert format_event("evt", key="a=b") == "evt key='a=b'"

    def test_field_order_is_preserved(self) -> None:
        """Fields render in insertion order across three or more fields.

        The docstring promises ``key=value`` pairs render "in order"; this pins
        that a dict-reordering regression would break.
        """
        assert format_event("evt", a=1, b=2, c=3) == "evt a=1 b=2 c=3"


class TestSetupLogging:
    """Test cases for setup_logging."""

    def test_console_only_level_info(self) -> None:
        """level=INFO is translated to the numeric logging level."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging(LoggingSettings(level="INFO", file_path=None))
            assert mock_basic_config.call_args[1]["level"] == logging.INFO

    def test_console_only_level_debug(self) -> None:
        """level=DEBUG is translated to the numeric logging level."""
        with patch("logging.basicConfig") as mock_basic_config:
            setup_logging(LoggingSettings(level="DEBUG", file_path=None))
            assert mock_basic_config.call_args[1]["level"] == logging.DEBUG

    def test_file_handler_is_added(self, tmp_path: Path) -> None:
        """A RotatingFileHandler is created from the settings and attached."""
        log_file = tmp_path / "logs" / "main.log"
        settings = LoggingSettings(
            file_path=log_file, max_file_size_mb=7, backup_count=3
        )
        root = logging.getLogger()
        before = set(root.handlers)

        with patch("logging.basicConfig"):
            setup_logging(settings)

        added = [h for h in root.handlers if h not in before]
        try:
            assert log_file.parent.exists()
            file_handlers = [h for h in added if isinstance(h, RotatingFileHandler)]
            assert len(file_handlers) == 1
            assert file_handlers[0].maxBytes == 7 * 1024 * 1024
            assert file_handlers[0].backupCount == 3
        finally:
            for handler in added:
                root.removeHandler(handler)
                handler.close()

    def test_file_handler_failure_degrades_to_console(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unwritable log directory must not crash setup; no handler is added."""
        settings = LoggingSettings(file_path=tmp_path / "main.log")

        def boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("read-only filesystem")

        monkeypatch.setattr(Path, "mkdir", boom)
        root = logging.getLogger()
        before = set(root.handlers)

        with patch("logging.basicConfig"):
            setup_logging(settings)  # must not raise

        added = [h for h in root.handlers if h not in before]
        assert not any(isinstance(h, RotatingFileHandler) for h in added)

    def test_file_handler_non_oserror_failure_degrades_to_console(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-OSError during handler setup must also not crash startup.

        The catch is intentionally broad (Exception, not just OSError) so the
        documented "a log-file problem must not crash the app" contract holds
        even for a non-OSError (e.g. a ValueError from a degenerate path). The
        app degrades to console-only.
        """
        settings = LoggingSettings(file_path=tmp_path / "main.log")

        def boom(*_args: object, **_kwargs: object) -> None:
            raise ValueError("not an OSError")

        monkeypatch.setattr(Path, "mkdir", boom)
        root = logging.getLogger()
        before = set(root.handlers)

        with patch("logging.basicConfig"):
            setup_logging(settings)  # must not raise

        added = [h for h in root.handlers if h not in before]
        assert not any(isinstance(h, RotatingFileHandler) for h in added)

    def test_setup_logging_relies_on_prevalidated_format(self, tmp_path: Path) -> None:
        """setup_logging trusts the field validator; it does not re-validate format.

        The file-handler branch builds a ``logging.Formatter`` from
        ``settings.format`` with no try/except of its own, because
        ``LoggingSettings._validate_format`` already guarantees the format is
        constructible at config load. This pins that cross-module contract: a
        format that bypassed validation (here via ``model_construct``) escapes
        ``setup_logging``. If the field validator is ever removed, a bad format in
        a real config would crash the same way — re-add the validation if touched.
        """
        added: list[logging.Handler] = []
        root = logging.getLogger()
        before = set(root.handlers)
        unvalidated = LoggingSettings.model_construct(
            level="INFO",
            format="%(nonexistent)q",
            file_path=tmp_path / "main.log",
            max_file_size_mb=10,
            backup_count=5,
        )

        try:
            with patch("logging.basicConfig"), pytest.raises(ValueError):
                setup_logging(unvalidated)
        finally:
            added = [h for h in root.handlers if h not in before]
            for handler in added:
                root.removeHandler(handler)
                handler.close()

    def test_console_only_adds_no_file_handler(self) -> None:
        """With file_path=None no RotatingFileHandler is attached at all."""
        root = logging.getLogger()
        before = set(root.handlers)

        with patch("logging.basicConfig"):
            setup_logging(LoggingSettings(file_path=None))

        added = [h for h in root.handlers if h not in before]
        assert not any(isinstance(h, RotatingFileHandler) for h in added)

    def test_repeated_setup_does_not_duplicate_file_handler(
        self, tmp_path: Path
    ) -> None:
        """A second setup_logging removes the prior file handler (no FD leak).

        Without the dedup in setup_logging, repeated calls would stack a new
        RotatingFileHandler each time, leaking descriptors and duplicating every
        log line. Exactly one must remain, and the displaced one must be closed.
        """
        log_file = tmp_path / "main.log"
        settings = LoggingSettings(file_path=log_file)
        root = logging.getLogger()
        before = set(root.handlers)

        added: list[logging.Handler] = []
        try:
            with patch("logging.basicConfig"):
                setup_logging(settings)
                first = [
                    h
                    for h in root.handlers
                    if h not in before and isinstance(h, RotatingFileHandler)
                ]
                assert len(first) == 1

                setup_logging(settings)

            file_handlers = [
                h
                for h in root.handlers
                if h not in before and isinstance(h, RotatingFileHandler)
            ]
            added = file_handlers
            assert len(file_handlers) == 1
            # The handler from the first call was replaced, not kept.
            assert file_handlers[0] is not first[0]
            # The displaced handler was closed; FileHandler.close() nulls the
            # stream, so a None stream proves the descriptor was released.
            assert first[0].stream is None
        finally:
            for handler in added:
                root.removeHandler(handler)
                handler.close()
