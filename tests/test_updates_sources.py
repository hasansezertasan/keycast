"""Tests for install-source detection (``keycast.updates.sources``).

Detection is exercised with injected ``env`` / ``read_installer`` /
``cask_receipt_exists`` so the ambient machine (which may have ``UV_TOOL_DIR``
set or an ``INSTALLER`` record of its own) cannot leak into the assertions.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from unittest.mock import MagicMock

import pytest

from keycast.updates import sources
from keycast.updates.sources import InstallSource


def _none() -> None:
    return None


class TestLooksHomebrew:
    """The Homebrew path heuristic that splits cask from manual Release."""

    @pytest.mark.parametrize(
        "posix",
        [
            "/opt/homebrew/cellar/keycast/0.1.0/lib",
            "/usr/local/cellar/keycast/0.1.0",
            "/opt/homebrew/caskroom/keycast/0.1.0/keycast.app",
            "/home/linuxbrew/.linuxbrew/lib",
        ],
    )
    def test_homebrew_paths_detected(self, posix: str) -> None:
        assert sources._looks_homebrew(posix) is True

    def test_non_homebrew_path_rejected(self) -> None:
        assert sources._looks_homebrew("/usr/lib/python3.14/site-packages") is False


class TestHomebrewCaskReceipt:
    """The Caskroom-receipt filesystem probe that confirms a cask install."""

    def test_found_under_standard_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "Caskroom" / "keycast").mkdir(parents=True)
        monkeypatch.setattr(sources, "_HOMEBREW_CASK_PREFIXES", (str(tmp_path),))
        monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)
        assert sources._homebrew_cask_receipt_exists() is True

    def test_found_under_custom_prefix_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "Caskroom" / "keycast").mkdir(parents=True)
        monkeypatch.setattr(sources, "_HOMEBREW_CASK_PREFIXES", ("/nonexistent-xyz",))
        monkeypatch.setenv("HOMEBREW_PREFIX", str(tmp_path))
        assert sources._homebrew_cask_receipt_exists() is True

    def test_absent_when_no_receipt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sources, "_HOMEBREW_CASK_PREFIXES", (str(tmp_path),))
        monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)
        assert sources._homebrew_cask_receipt_exists() is False


class TestIsUnder:
    """The env-dir containment check, including Windows-path normalization."""

    def test_empty_dir_never_matches(self) -> None:
        # An env var being *set to empty* is not evidence of where keycast lives.
        assert sources._is_under("/home/u/.local/uv/tools/keycast", "") is False

    def test_posix_dir_contains_location(self) -> None:
        assert sources._is_under("/opt/elsewhere/keycast/x.py", "/opt/elsewhere")

    def test_normalizes_windows_backslashes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The env dir arrives with native Windows backslashes; the function must
        # normalize it to lower-cased POSIX before comparing. Patching Path to
        # PureWindowsPath reproduces a Windows host on a POSIX CI runner, so this
        # pins the documented normalization independent of the test machine.
        monkeypatch.setattr(sources, "Path", PureWindowsPath)
        location_posix = "c:/users/u/.local/uv/tools/keycast/lib/sources.py"
        assert sources._is_under(location_posix, r"C:\Users\U\.local\uv\tools") is True


class TestReadInstaller:
    """The stdlib INSTALLER record reader."""

    def test_returns_lowercased_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dist = MagicMock()
        dist.read_text.return_value = "uv\n"
        monkeypatch.setattr(sources.importlib.metadata, "distribution", lambda _n: dist)
        assert sources._read_installer() == "uv"

    def test_missing_record_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dist = MagicMock()
        dist.read_text.return_value = None
        monkeypatch.setattr(sources.importlib.metadata, "distribution", lambda _n: dist)
        assert sources._read_installer() is None

    def test_unreadable_metadata_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(_name: str) -> object:
            raise sources.importlib.metadata.PackageNotFoundError("keycast")

        monkeypatch.setattr(sources.importlib.metadata, "distribution", boom)
        assert sources._read_installer() is None


class TestDetectInstallSource:
    """The first-match-wins detection tree (ADR-002 / ADR-005)."""

    def test_frozen_under_caskroom_is_cask(self) -> None:
        loc = Path(
            "/opt/homebrew/Caskroom/keycast/0.5.0/keycast.app/Contents/MacOS/keycast"
        )
        assert (
            sources.detect_install_source(
                frozen=True, location=loc, cask_receipt_exists=lambda: False
            )
            == InstallSource.HOMEBREW_CASK
        )

    def test_frozen_in_applications_with_receipt_is_cask(self) -> None:
        loc = Path("/Applications/keycast.app/Contents/MacOS/keycast")
        assert (
            sources.detect_install_source(
                frozen=True, location=loc, cask_receipt_exists=lambda: True
            )
            == InstallSource.HOMEBREW_CASK
        )

    def test_frozen_in_applications_without_receipt_is_release(self) -> None:
        loc = Path("/Applications/keycast.app/Contents/MacOS/keycast")
        assert (
            sources.detect_install_source(
                frozen=True, location=loc, cask_receipt_exists=lambda: False
            )
            == InstallSource.GITHUB_RELEASE
        )

    def test_frozen_outside_applications_is_release(self) -> None:
        loc = Path("C:/Program Files/keycast/keycast.exe")
        assert (
            sources.detect_install_source(
                frozen=True, location=loc, cask_receipt_exists=lambda: True
            )
            == InstallSource.GITHUB_RELEASE
        )

    def test_frozen_uses_sys_executable_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sources.sys,
            "executable",
            "/Users/u/Downloads/keycast.app/Contents/MacOS/keycast",
        )
        assert (
            sources.detect_install_source(
                frozen=True, cask_receipt_exists=lambda: False
            )
            == InstallSource.GITHUB_RELEASE
        )

    def test_pipx_by_path(self) -> None:
        loc = Path("/home/u/.local/pipx/venvs/keycast/lib/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False, location=loc, env={}, read_installer=_none
            )
            == InstallSource.PIPX
        )

    def test_pipx_by_env_home(self) -> None:
        loc = Path("/custom/pipxhome/keycast/lib/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False,
                location=loc,
                env={"PIPX_HOME": "/custom/pipxhome"},
                read_installer=_none,
            )
            == InstallSource.PIPX
        )

    def test_uv_tool_by_installer_record(self) -> None:
        # The authoritative signal: INSTALLER="uv", regardless of path.
        loc = Path("/opt/whatever/site-packages/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False, location=loc, env={}, read_installer=lambda: "uv"
            )
            == InstallSource.UV_TOOL
        )

    def test_uv_tool_by_path_fallback(self) -> None:
        loc = Path(
            "/home/u/.local/share/uv/tools/keycast/lib/keycast/updates/sources.py"
        )
        assert (
            sources.detect_install_source(
                frozen=False, location=loc, env={}, read_installer=_none
            )
            == InstallSource.UV_TOOL
        )

    def test_uv_tool_by_env_dir(self) -> None:
        loc = Path("/opt/elsewhere/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False,
                location=loc,
                env={"UV_TOOL_DIR": "/opt/elsewhere"},
                read_installer=_none,
            )
            == InstallSource.UV_TOOL
        )

    def test_homebrew_formula(self) -> None:
        # INSTALLER reads "pip" for a brew formula (installed via pip), so the
        # Cellar path marker is what classifies it.
        loc = Path("/opt/homebrew/Cellar/keycast/0.1.0/lib/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False, location=loc, env={}, read_installer=lambda: "pip"
            )
            == InstallSource.HOMEBREW_FORMULA
        )

    def test_env_var_set_but_package_elsewhere_is_ignored(self) -> None:
        # A set UV_TOOL_DIR/PIPX_HOME must not hijack classification unless the
        # package actually lives under it (regression: Windows CI).
        loc = Path("/opt/homebrew/Cellar/keycast/0.1.0/lib/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False,
                location=loc,
                env={"UV_TOOL_DIR": "/home/u/.local/share/uv/tools", "PIPX_HOME": "/x"},
                read_installer=_none,
            )
            == InstallSource.HOMEBREW_FORMULA
        )

    def test_plain_pip(self) -> None:
        loc = Path("/usr/lib/python3.14/site-packages/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False, location=loc, env={}, read_installer=lambda: "pip"
            )
            == InstallSource.PIP
        )

    def test_defaults_resolve_without_args(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Exercises the default frozen/location/env/read_installer resolution
        # against the real package; the runner is not frozen, so it never errors.
        monkeypatch.delattr(sources.sys, "frozen", raising=False)
        assert isinstance(sources.detect_install_source(), InstallSource)


class TestRecommendedActionAndLabels:
    """Per-source command strings and human labels."""

    def test_command_sources_map_to_commands(self) -> None:
        assert sources.recommended_action(InstallSource.PIPX) == "pipx upgrade keycast"
        assert sources.recommended_action(InstallSource.HOMEBREW_CASK) == (
            "brew upgrade --cask keycast"
        )

    @pytest.mark.parametrize(
        "source", [InstallSource.GITHUB_RELEASE, InstallSource.UNKNOWN]
    )
    def test_fallback_sources_point_at_releases(self, source: InstallSource) -> None:
        assert sources.recommended_action(source) == sources.RELEASES_URL

    def test_labels_cover_every_source(self) -> None:
        for source in InstallSource:
            assert isinstance(sources.install_source_label(source), str)
