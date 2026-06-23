"""Tests for the main entry point."""

import tkinter as tk
from unittest.mock import patch

import pytest

from keycast.main import main


def test_main_runs_application() -> None:
    """main() constructs Keycast and runs it."""
    with patch("keycast.main.Keycast") as keycast_cls:
        main()

        keycast_cls.assert_called_once_with()
        keycast_cls.return_value.run.assert_called_once_with()


def test_main_exits_nonzero_on_construction_failure() -> None:
    """A failure building Keycast (e.g. headless tkinter) degrades to exit 1.

    Construction runs before run()'s own error handling, so main() must catch it
    rather than let an uncaught traceback escape.
    """
    with (
        patch("keycast.main.Keycast", side_effect=RuntimeError("boom")),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 1


def test_main_headless_failure_logs_actionable_hint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A tkinter TclError (no display server) degrades with an actionable hint."""
    with (
        patch(
            "keycast.main.Keycast",
            side_effect=tk.TclError("no display name and no $DISPLAY"),
        ),
        caplog.at_level("ERROR", logger="keycast"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 1
    assert "reason=no_display" in caplog.text
    assert "hint=" in caplog.text
