"""Test cases for the main application commands using Typer's CLI runner."""

import platform
from unittest.mock import patch

from typer.testing import CliRunner

from keycast import __version__
from keycast.cli import app

runner = CliRunner()


def test_no_args_launches_app() -> None:
    """Invoking `keycast` with no subcommand launches the overlay."""
    with patch("keycast.main.main") as mock_run:
        result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once_with()


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
    assert result.output.strip() == __version__


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
