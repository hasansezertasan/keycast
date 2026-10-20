"""Tests for the main entry point."""

import sys
import tkinter as tk
from unittest.mock import patch

import pytest

from keycast.main import main


def test_main_runs_application() -> None:
    """main() constructs Keycast and runs it."""
    with patch("keycast.main.Keycast") as keycast_cls:
        main()

<<<<<<< before updating
        keycast_cls.assert_called_once_with()
        keycast_cls.return_value.run.assert_called_once_with()
=======
    Every standalone-executable build (launcher / freezer / compiler)
    targets ``keycast.__main__:main``, so this pins the
    contract that the symbol exists and is callable for whichever component is
    enabled, and that the active branch's component import actually resolves.
    The module is imported (not executed as ``__main__``), so a runnable
    component's blocking ``main()`` (server loop, mainloop, ...) is never invoked.
    """
    main_module = importlib.import_module("keycast.__main__")
>>>>>>> after updating


def test_main_exits_nonzero_on_construction_failure() -> None:
    """A failure building Keycast (e.g. headless tkinter) degrades to exit 1.

<<<<<<< before updating
    Construction runs before run()'s own error handling, so main() must catch it
    rather than let an uncaught traceback escape.
=======
@pytest.mark.parametrize("dependency", ["typer", "pydantic", "pydantic_settings"])
def test_console_root_reports_missing_launcher_dependency(
    dependency: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing root dependency is reported actionably, not as a bare traceback.

    Every module parametrized here is imported at the console root's module
    scope -- ``typer`` by the root itself, ``pydantic``/``pydantic_settings``
    transitively through ``core.logging_setup`` -> ``core.config`` -- so each one
    fails before the component-dependency guard inside ``cli/app.py`` exists.

    Given:
        - An environment out of sync with the installed package, so one of the
          root's own dependencies cannot be imported -- what adding the shared
          launcher (or enabling settings) leaves behind until ``uv sync``.
    When:
        - ``__main__`` loads the console root, as bare ``keycast`` does.
    Then:
        - It exits 1 with a message naming the module and ``uv sync``, and no
          traceback.
>>>>>>> after updating
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


def test_main_missing_tkinter_logs_actionable_hint(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Python built without _tkinter (ImportError) gets the same headless hint.

    ``import tkinter`` raising -- not just ``tk.TclError`` at construction -- must
    still degrade to exit 1 with an actionable message rather than an uncaught
    traceback. Poisoning sys.modules makes the lazy ``import tkinter`` in main()
    raise ImportError.
    """
    monkeypatch.setitem(sys.modules, "tkinter", None)

    with (
        caplog.at_level("ERROR", logger="keycast"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 1
    assert "reason=no_display" in caplog.text
    assert "_tkinter" in caplog.text
