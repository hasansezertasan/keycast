"""Test cases for the main application commands using Typer's CLI runner."""

import platform
from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from keycast import __version__
from keycast.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def stub_update_check() -> Iterator[Mock]:
    """Neutralize the update check for every CLI test.

    A real subcommand invocation would read config and spawn a GitHub-bound
    daemon thread; stubbing the entrypoint keeps the CLI tests deterministic and
    offline. Tests that assert the wiring request this fixture for the mock.

    Yields:
        The mock standing in for ``keycast.updates.notify_pending_update``.
    """
    with patch("keycast.updates.notify_pending_update") as mock:
        yield mock


def test_no_args_launches_app(stub_update_check: Mock) -> None:
    """Invoking `keycast` with no subcommand launches the overlay.

    The overlay path notifies about updates through the window (Keycast.start),
    not the CLI callback, so the callback's update check stays untouched here.
    """
    with patch("keycast.main.main") as mock_run:
        result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once_with()
    stub_update_check.assert_not_called()


def test_version_does_not_launch_app() -> None:
    """A subcommand must not trigger the no-arg launch path."""
    with patch("keycast.main.main") as mock_run:
        result = runner.invoke(app, ["version"])

    assert result.exit_code == 0, result.output
    mock_run.assert_not_called()


def test_version_prints_the_package_version() -> None:
    """`version` echoes the installed package version verbatim."""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == __version__


def test_info_reports_version_python_and_platform() -> None:
    """`info` prints the documented Version/Python/Platform lines with real values.

    Asserts the labelled output contract in ``cli.info`` so a regression that
    drops or relabels a line is caught, not just a nonzero exit.
    """
    result = runner.invoke(app, ["info"])

    assert result.exit_code == 0, result.output
    assert f"Application Version: {__version__}" in result.output
    assert f"Python Version: {platform.python_version()}" in result.output
    assert f"Platform: {platform.system()}" in result.output


def test_info_reports_install_source() -> None:
    """`info` adds the documented Install source line."""
    result = runner.invoke(app, ["info"])

    assert result.exit_code == 0, result.output
    assert "Install source:" in result.output


def test_subcommand_runs_update_check(stub_update_check: Mock) -> None:
    """Any subcommand triggers the (cached) update check via the root callback."""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0, result.output
    stub_update_check.assert_called_once()


def test_update_notice_rides_stderr_not_stdout() -> None:
    """The notice must not pollute the parseable stdout of `version`."""

    def emit_notice(*, notify: object, **_kwargs: object) -> None:
        notify("keycast 9.9.9 available — pip install -U keycast")  # type: ignore[operator]

    with patch("keycast.updates.notify_pending_update", side_effect=emit_notice):
        result = runner.invoke(app, ["version"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == __version__
    assert "9.9.9 available" in result.stderr
