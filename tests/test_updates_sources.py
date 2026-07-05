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


class TestScoopSource:
    """The Scoop location heuristic: per-user vs global, path marker + env root."""

    def test_default_user_root_path_marker(self) -> None:
        posix = "c:/users/u/scoop/apps/keycast/current/keycast.exe"
        assert sources._scoop_source(posix, {}) is InstallSource.SCOOP

    def test_default_global_root_path_marker(self) -> None:
        # C:\ProgramData\scoop also contains the per-user marker, so global must
        # be matched first — a global install updates with `-g`, not plain update.
        posix = "c:/programdata/scoop/apps/keycast/current/keycast.exe"
        assert sources._scoop_source(posix, {}) is InstallSource.SCOOP_GLOBAL

    def test_custom_user_root_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A relocated root carries no "/scoop/" fragment; the env var is the only
        # signal, and the bundle must actually live under it. The env dir arrives
        # with native Windows backslashes, so PureWindowsPath reproduces a Windows
        # host on the POSIX CI runner (mirrors TestIsUnder).
        monkeypatch.setattr(sources, "Path", PureWindowsPath)
        posix = "d:/tools/keycast/current/keycast.exe"
        assert (
            sources._scoop_source(posix, {"SCOOP": r"D:\tools"}) is InstallSource.SCOOP
        )

    def test_custom_global_root_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sources, "Path", PureWindowsPath)
        posix = "d:/globalscoop/apps/keycast/current/keycast.exe"
        assert (
            sources._scoop_source(posix, {"SCOOP_GLOBAL": r"D:\globalscoop"})
            is InstallSource.SCOOP_GLOBAL
        )

    def test_global_env_root_wins_over_per_user_path_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A bundle under a custom SCOOP_GLOBAL root whose path *also* contains the
        # per-user "/scoop/apps/keycast/" fragment must still classify as global —
        # the SCOOP_GLOBAL env check runs before the per-user marker. Pins the
        # precedence against a future reorder that would wrongly drop the `-g`.
        monkeypatch.setattr(sources, "Path", PureWindowsPath)
        posix = "d:/gscoop/scoop/apps/keycast/current/keycast.exe"
        assert (
            sources._scoop_source(posix, {"SCOOP_GLOBAL": r"D:\gscoop"})
            is InstallSource.SCOOP_GLOBAL
        )

    def test_env_set_but_package_elsewhere_is_ignored(self) -> None:
        posix = "c:/program files/keycast/keycast.exe"
        assert sources._scoop_source(posix, {"SCOOP": r"C:\Users\U\scoop"}) is None

    def test_empty_env_and_non_scoop_path_rejected(self) -> None:
        posix = "c:/program files/keycast/keycast.exe"
        assert sources._scoop_source(posix, {"SCOOP": "", "SCOOP_GLOBAL": ""}) is None


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


class TestMacAppStoreReceipt:
    """The _MASReceipt filesystem probe inside the running bundle.

    ``sys.platform`` is faked to ``"darwin"`` so the receipt path is exercised on
    every CI OS (coverage uploads from Linux, where the real guard returns early).
    """

    def _bundle(self, tmp_path: Path) -> Path:
        # sys.executable is <bundle>/Contents/MacOS/keycast.
        macos = tmp_path / "keycast.app" / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        return macos / "keycast"

    def test_present_when_receipt_in_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = self._bundle(tmp_path)
        receipt = tmp_path / "keycast.app" / "Contents" / "_MASReceipt" / "receipt"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("mas")
        monkeypatch.setattr(sources.sys, "platform", "darwin")
        monkeypatch.setattr(sources.sys, "executable", str(exe))
        assert sources._mas_receipt_exists() is True

    def test_absent_when_no_receipt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A cask or drag-install .app has the same layout but no _MASReceipt.
        exe = self._bundle(tmp_path)
        monkeypatch.setattr(sources.sys, "platform", "darwin")
        monkeypatch.setattr(sources.sys, "executable", str(exe))
        assert sources._mas_receipt_exists() is False

    def test_absent_off_macos_even_with_receipt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A stray _MASReceipt on another OS must never read as a MAS install —
        # the probe is gated on the platform, like the Windows installer marker.
        exe = self._bundle(tmp_path)
        receipt = tmp_path / "keycast.app" / "Contents" / "_MASReceipt" / "receipt"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("mas")
        monkeypatch.setattr(sources.sys, "platform", "win32")
        monkeypatch.setattr(sources.sys, "executable", str(exe))
        assert sources._mas_receipt_exists() is False


class TestInstallerMarker:
    """The Windows-installer marker probe beside the executable."""

    def test_present_when_marker_beside_exe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / sources._INSTALLER_MARKER_NAME).write_text("windows-installer")
        monkeypatch.setattr(sources.sys, "platform", "win32")
        monkeypatch.setattr(sources.sys, "executable", str(tmp_path / "keycast.exe"))
        assert sources._installer_marker_exists() is True

    def test_absent_for_bare_zip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A zip extraction has no marker file beside the exe.
        monkeypatch.setattr(sources.sys, "platform", "win32")
        monkeypatch.setattr(sources.sys, "executable", str(tmp_path / "keycast.exe"))
        assert sources._installer_marker_exists() is False

    def test_absent_off_windows_even_with_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A stray .install-source beside a frozen macOS/Linux build must never
        # read as a Windows install — the probe is gated on the platform.
        (tmp_path / sources._INSTALLER_MARKER_NAME).write_text("windows-installer")
        monkeypatch.setattr(sources.sys, "platform", "darwin")
        monkeypatch.setattr(sources.sys, "executable", str(tmp_path / "keycast"))
        assert sources._installer_marker_exists() is False


class TestIsUnder:
    """The env-dir containment check, including Windows-path normalization."""

    def test_empty_dir_never_matches(self) -> None:
        # An env var being *set to empty* is not evidence of where keycast lives.
        assert sources._is_under("/home/u/.local/uv/tools/keycast", "") is False

    def test_posix_dir_contains_location(self) -> None:
        assert sources._is_under("/opt/elsewhere/keycast/x.py", "/opt/elsewhere")

    def test_sibling_prefix_does_not_match(self) -> None:
        # Boundary, not bare prefix: a sibling whose name merely starts with the
        # root must not match (D:\toolsX is not under D:\tools).
        assert sources._is_under("/opt/elsewhere2/keycast/x.py", "/opt/elsewhere") is (
            False
        )

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
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: True,
                mas_receipt_exists=lambda: False,
            )
            == InstallSource.HOMEBREW_CASK
        )

    def test_frozen_in_applications_without_receipt_is_release(self) -> None:
        loc = Path("/Applications/keycast.app/Contents/MacOS/keycast")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: False,
                mas_receipt_exists=lambda: False,
            )
            == InstallSource.GITHUB_RELEASE
        )

    def test_frozen_with_mas_receipt_is_mac_app_store(self) -> None:
        # A MAS .app lives in /Applications like a cask; the bundle's
        # _MASReceipt is what flips it to MAC_APP_STORE (ADR-011).
        loc = Path("/Applications/keycast.app/Contents/MacOS/keycast")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                mas_receipt_exists=lambda: True,
                cask_receipt_exists=lambda: False,
            )
            == InstallSource.MAC_APP_STORE
        )

    def test_mas_receipt_wins_over_cask(self) -> None:
        # Orthogonal in practice (a MAS install has no Caskroom receipt), but the
        # MAS probe is checked first — pin that order so the precedence is
        # intentional, since both key on /Applications.
        loc = Path("/Applications/keycast.app/Contents/MacOS/keycast")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                mas_receipt_exists=lambda: True,
                cask_receipt_exists=lambda: True,
            )
            == InstallSource.MAC_APP_STORE
        )

    def test_mas_receipt_not_detected_when_not_frozen(self) -> None:
        # The MAS branch lives inside `if frozen:`. A non-frozen install must
        # classify by the import-path rules even if the receipt predicate would
        # return True, never as MAC_APP_STORE.
        loc = Path("/Applications/keycast.app/Contents/Resources/keycast/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False,
                location=loc,
                env={},
                mas_receipt_exists=lambda: True,
                read_installer=lambda: "pip",
            )
            == InstallSource.PIP
        )

    def test_frozen_outside_applications_is_release(self) -> None:
        loc = Path("C:/Program Files/keycast/keycast.exe")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                mas_receipt_exists=lambda: False,
                cask_receipt_exists=lambda: True,
                installer_marker_exists=lambda: False,
            )
            == InstallSource.GITHUB_RELEASE
        )

    def test_frozen_with_installer_marker_is_windows_installer(self) -> None:
        # Same frozen bundle as a zip download; the marker beside the exe is what
        # flips it from GITHUB_RELEASE to WINDOWS_INSTALLER.
        loc = Path("C:/Program Files/keycast/keycast.exe")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: False,
                installer_marker_exists=lambda: True,
            )
            == InstallSource.WINDOWS_INSTALLER
        )

    def test_frozen_under_scoop_path_is_scoop(self) -> None:
        # Same frozen bundle as a zip download, no installer marker; the
        # ~/scoop/apps/keycast/ location is what flips it to SCOOP.
        loc = Path("C:/Users/u/scoop/apps/keycast/current/keycast.exe")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: False,
                installer_marker_exists=lambda: False,
            )
            == InstallSource.SCOOP
        )

    def test_frozen_under_global_scoop_path_is_scoop_global(self) -> None:
        # A global install (C:\ProgramData\scoop) updates with `-g`, so it is a
        # distinct source from a per-user one.
        loc = Path("C:/ProgramData/scoop/apps/keycast/current/keycast.exe")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: False,
                installer_marker_exists=lambda: False,
            )
            == InstallSource.SCOOP_GLOBAL
        )

    def test_frozen_under_custom_scoop_root_env_is_scoop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Custom SCOOP root (no "/scoop/" fragment); PureWindowsPath reproduces a
        # Windows host so the backslash env dir normalizes like it would on-target.
        monkeypatch.setattr(sources, "Path", PureWindowsPath)
        loc = PureWindowsPath("D:/tools/keycast/current/keycast.exe")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                env={"SCOOP": r"D:\tools"},
                cask_receipt_exists=lambda: False,
                mas_receipt_exists=lambda: False,
                installer_marker_exists=lambda: False,
            )
            == InstallSource.SCOOP
        )

    def test_installer_marker_wins_over_scoop(self) -> None:
        # Orthogonal in practice (a Scoop bundle has no marker), but the marker is
        # checked first — pin that order so the precedence is intentional.
        loc = Path("C:/Users/u/scoop/apps/keycast/current/keycast.exe")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: False,
                installer_marker_exists=lambda: True,
            )
            == InstallSource.WINDOWS_INSTALLER
        )

    def test_scoop_not_detected_when_not_frozen(self) -> None:
        # The Scoop branch lives inside `if frozen:`. A non-frozen install whose
        # path happens to contain /scoop/ must classify by the import-path rules,
        # never as SCOOP.
        loc = Path("/home/u/scoop/apps/keycast/lib/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False, location=loc, env={}, read_installer=lambda: "pip"
            )
            == InstallSource.PIP
        )

    def test_frozen_under_windowsapps_is_microsoft_store(self) -> None:
        # Same frozen bundle again, no marker, no Scoop path; the ACL-locked
        # WindowsApps deployment tree is what flips it to MICROSOFT_STORE
        # (ADR-009).
        loc = Path(
            "C:/Program Files/WindowsApps/keycast_0.3.0.0_x64__abc/keycast/keycast.exe"
        )
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: False,
                installer_marker_exists=lambda: False,
            )
            == InstallSource.MICROSOFT_STORE
        )

    def test_installer_marker_wins_over_microsoft_store(self) -> None:
        # Orthogonal in practice (the Store never deploys the Inno marker into
        # WindowsApps), but the marker is checked first — pin that order so the
        # precedence is intentional, like the Scoop one above.
        loc = Path(
            "C:/Program Files/WindowsApps/keycast_0.3.0.0_x64__abc/keycast/keycast.exe"
        )
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: False,
                installer_marker_exists=lambda: True,
            )
            == InstallSource.WINDOWS_INSTALLER
        )

    def test_microsoft_store_not_detected_when_not_frozen(self) -> None:
        # Like the Scoop branch, the WindowsApps probe lives inside `if frozen:`.
        # A non-frozen install whose path happens to contain /windowsapps/ must
        # classify by the import-path rules, never as MICROSOFT_STORE.
        loc = Path("/home/u/windowsapps/keycast/lib/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False, location=loc, env={}, read_installer=lambda: "pip"
            )
            == InstallSource.PIP
        )

    def test_cask_wins_over_installer_marker(self) -> None:
        # macOS cask is decided before the installer marker is even consulted.
        loc = Path("/Applications/keycast.app/Contents/MacOS/keycast")
        assert (
            sources.detect_install_source(
                frozen=True,
                location=loc,
                cask_receipt_exists=lambda: True,
                installer_marker_exists=lambda: True,
            )
            == InstallSource.HOMEBREW_CASK
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

    def test_frozen_uses_installer_marker_probe_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With no installer_marker_exists arg, the real _installer_marker_exists
        # probe runs: a marker dropped beside sys.executable flips the result to
        # WINDOWS_INSTALLER. Pins the default wiring on the positive path.
        (tmp_path / sources._INSTALLER_MARKER_NAME).write_text("windows-installer")
        monkeypatch.setattr(sources.sys, "platform", "win32")
        monkeypatch.setattr(sources.sys, "executable", str(tmp_path / "keycast.exe"))
        assert (
            sources.detect_install_source(
                frozen=True, cask_receipt_exists=lambda: False
            )
            == InstallSource.WINDOWS_INSTALLER
        )

    def test_installer_marker_not_probed_when_not_frozen(self) -> None:
        # The marker branch lives entirely inside `if frozen:`. A non-frozen
        # (pip/pipx/...) install must never be classified by the marker, even if
        # the probe would say True — pins that the probe stays behind the frozen
        # gate against a future refactor.
        loc = Path("/home/u/.local/pipx/venvs/keycast/lib/keycast/updates/sources.py")
        assert (
            sources.detect_install_source(
                frozen=False,
                location=loc,
                env={},
                read_installer=_none,
                installer_marker_exists=lambda: True,
            )
            == InstallSource.PIPX
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
        assert sources.recommended_action(InstallSource.SCOOP) == "scoop update keycast"
        assert sources.recommended_action(InstallSource.SCOOP_GLOBAL) == (
            "sudo scoop update keycast -g"
        )

    @pytest.mark.parametrize(
        "source",
        [
            InstallSource.GITHUB_RELEASE,
            InstallSource.WINDOWS_INSTALLER,
            InstallSource.UNKNOWN,
        ],
    )
    def test_fallback_sources_point_at_releases(self, source: InstallSource) -> None:
        assert sources.recommended_action(source) == sources.RELEASES_URL

    def test_labels_cover_every_source(self) -> None:
        for source in InstallSource:
            assert isinstance(sources.install_source_label(source), str)

    def test_only_fallback_sources_point_at_releases(self) -> None:
        # Exhaustiveness guard mirroring test_labels_cover_every_source: a source
        # accidentally omitted from _UPGRADE_COMMANDS silently falls through to
        # RELEASES_URL via the .get() default — exactly the "wrong channel" bug a
        # store source must never hit. Pin that only the three URL-fallback
        # sources resolve to the Releases page; every other source (commands and
        # the store statements alike) must resolve to something else.
        fallback = {
            InstallSource.GITHUB_RELEASE,
            InstallSource.WINDOWS_INSTALLER,
            InstallSource.UNKNOWN,
        }
        for source in InstallSource:
            points_at_releases = (
                sources.recommended_action(source) == sources.RELEASES_URL
            )
            assert points_at_releases == (source in fallback)

    def test_windows_installer_label_is_exact(self) -> None:
        # User-facing string (shown by `keycast info`); pin it so a typo can't
        # ship silently — the cover-every-source test only checks the type.
        assert (
            sources.install_source_label(InstallSource.WINDOWS_INSTALLER)
            == "Windows installer"
        )

    def test_scoop_label_is_exact(self) -> None:
        assert sources.install_source_label(InstallSource.SCOOP) == "Scoop"
        assert (
            sources.install_source_label(InstallSource.SCOOP_GLOBAL) == "Scoop (global)"
        )

    def test_microsoft_store_action_is_a_statement_not_a_command(self) -> None:
        # ADR-009: the Store updates its apps itself, so the recommended action
        # is that fact stated outright — never a command to run and never the
        # Releases page (which would send a Store user to the wrong channel).
        assert sources.recommended_action(InstallSource.MICROSOFT_STORE) == (
            "updates are delivered automatically by the Microsoft Store"
        )

    def test_microsoft_store_label_is_exact(self) -> None:
        assert (
            sources.install_source_label(InstallSource.MICROSOFT_STORE)
            == "Microsoft Store"
        )

    def test_mac_app_store_action_is_a_statement_not_a_command(self) -> None:
        # ADR-011: the Mac App Store updates its apps itself, so the recommended
        # action is that fact stated outright — never a command, never the
        # Releases page (which would send a MAS user to the wrong channel).
        assert sources.recommended_action(InstallSource.MAC_APP_STORE) == (
            "updates are delivered automatically by the Mac App Store"
        )

    def test_mac_app_store_label_is_exact(self) -> None:
        assert (
            sources.install_source_label(InstallSource.MAC_APP_STORE) == "Mac App Store"
        )
