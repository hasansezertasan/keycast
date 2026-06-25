"""Tests for the install-source-aware update check (``keycast.updates``).

Network and threading are always injected, never real: ``fetch`` and ``spawn``
are passed explicitly (or ``urlopen``/``Settings`` patched), so these tests make
no outbound request and spawn no background work unless they opt in deterministically.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from keycast import updates
from keycast.updates import InstallSource, UpdateState


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
        assert updates._looks_homebrew(posix) is True

    def test_non_homebrew_path_rejected(self) -> None:
        assert updates._looks_homebrew("/usr/lib/python3.14/site-packages") is False


class TestDetectInstallSource:
    """The first-match-wins detection tree (ADR-002)."""

    def test_frozen_under_homebrew_is_cask(self) -> None:
        loc = Path(
            "/opt/homebrew/Caskroom/keycast/0.5.0/keycast.app/Contents/MacOS/keycast"
        )
        assert updates.detect_install_source(frozen=True, location=loc) == (
            InstallSource.HOMEBREW_CASK
        )

    def test_frozen_elsewhere_is_github_release(self) -> None:
        loc = Path("/Applications/keycast.app/Contents/MacOS/keycast")
        assert updates.detect_install_source(frozen=True, location=loc) == (
            InstallSource.GITHUB_RELEASE
        )

    def test_frozen_uses_sys_executable_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            updates.sys,
            "executable",
            "/Applications/keycast.app/Contents/MacOS/keycast",
        )
        assert (
            updates.detect_install_source(frozen=True) == InstallSource.GITHUB_RELEASE
        )

    def test_pipx_by_path(self) -> None:
        loc = Path(
            "/home/u/.local/pipx/venvs/keycast/lib/python3.14/keycast/updates.py"
        )
        assert (
            updates.detect_install_source(frozen=False, location=loc, env={})
            == InstallSource.PIPX
        )

    def test_pipx_by_env_home(self) -> None:
        loc = Path("/custom/pipxhome/keycast/lib/keycast/updates.py")
        source = updates.detect_install_source(
            frozen=False, location=loc, env={"PIPX_HOME": "/custom/pipxhome"}
        )
        assert source == InstallSource.PIPX

    def test_uv_tool_by_path(self) -> None:
        loc = Path("/home/u/.local/share/uv/tools/keycast/lib/keycast/updates.py")
        assert (
            updates.detect_install_source(frozen=False, location=loc, env={})
            == InstallSource.UV_TOOL
        )

    def test_uv_tool_by_tools_fragment(self) -> None:
        loc = Path("/somewhere/uv/tools/keycast/keycast/updates.py")
        # The "/uv/tools/" fragment alone matches, independent of any env var.
        assert (
            updates.detect_install_source(frozen=False, location=loc, env={})
            == InstallSource.UV_TOOL
        )

    def test_uv_tool_by_env_dir_only(self) -> None:
        loc = Path("/opt/elsewhere/keycast/updates.py")
        source = updates.detect_install_source(
            frozen=False, location=loc, env={"UV_TOOL_DIR": "/opt/elsewhere"}
        )
        assert source == InstallSource.UV_TOOL

    def test_homebrew_formula(self) -> None:
        # Cellar marker on a non-frozen install → formula, not cask.
        loc = Path("/opt/homebrew/Cellar/keycast/0.1.0/lib/keycast/updates.py")
        assert updates.detect_install_source(frozen=False, location=loc, env={}) == (
            InstallSource.HOMEBREW_FORMULA
        )

    def test_env_var_set_but_package_elsewhere_is_ignored(self) -> None:
        # A set UV_TOOL_DIR/PIPX_HOME must NOT hijack classification unless the
        # package actually lives under it: a brew/pip user who also has uv
        # configured should still get the right advice (regression: Windows CI).
        loc = Path("/opt/homebrew/Cellar/keycast/0.1.0/lib/keycast/updates.py")
        source = updates.detect_install_source(
            frozen=False,
            location=loc,
            env={"UV_TOOL_DIR": "/home/u/.local/share/uv/tools", "PIPX_HOME": "/x"},
        )
        assert source == InstallSource.HOMEBREW_FORMULA

    def test_plain_pip(self) -> None:
        loc = Path("/usr/lib/python3.14/site-packages/keycast/updates.py")
        assert updates.detect_install_source(frozen=False, location=loc, env={}) == (
            InstallSource.PIP
        )

    def test_defaults_resolve_without_args(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Exercises the default frozen/location/env resolution against the real
        # package location; the test runner is not frozen, so this never errors.
        monkeypatch.delattr(updates.sys, "frozen", raising=False)
        assert isinstance(updates.detect_install_source(), InstallSource)


class TestRecommendedActionAndLabels:
    """Per-source command strings and human labels."""

    def test_command_sources_map_to_commands(self) -> None:
        assert updates.recommended_action(InstallSource.PIPX) == "pipx upgrade keycast"
        assert updates.recommended_action(InstallSource.HOMEBREW_CASK) == (
            "brew upgrade --cask keycast"
        )

    @pytest.mark.parametrize(
        "source", [InstallSource.GITHUB_RELEASE, InstallSource.UNKNOWN]
    )
    def test_fallback_sources_point_at_releases(self, source: InstallSource) -> None:
        assert updates.recommended_action(source) == updates.RELEASES_URL

    def test_labels_cover_every_source(self) -> None:
        for source in InstallSource:
            assert isinstance(updates.install_source_label(source), str)


class TestVersionComparison:
    """PEP 440 comparison and notice formatting."""

    @pytest.mark.parametrize(
        ("raw", "expected"), [("v0.3.0", "0.3.0"), ("V1.0", "1.0"), ("2.0", "2.0")]
    )
    def test_strip_v(self, raw: str, expected: str) -> None:
        assert updates._strip_v(raw) == expected

    def test_newer_is_true(self) -> None:
        assert updates.is_newer("v0.5.0", "0.4.9") is True

    def test_same_or_older_is_false(self) -> None:
        assert updates.is_newer("0.4.0", "0.4.0") is False
        assert updates.is_newer("0.3.0", "0.4.0") is False

    def test_dev_version_orders_below_release(self) -> None:
        # hatch-vcs dev build in a source checkout vs a clean release tag.
        assert updates.is_newer("v0.3.1", "0.3.1.dev4+g1234abc") is True

    def test_unparsable_is_not_newer(self) -> None:
        assert updates.is_newer("not-a-version", "0.1.0") is False

    def test_format_notice(self) -> None:
        notice = updates.format_notice("v0.5.0", InstallSource.HOMEBREW_CASK)
        assert notice == "keycast 0.5.0 available — brew upgrade --cask keycast"


class TestStateFile:
    """Reading/writing the throttle state, including corruption recovery."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "update-check.json"
        updates.write_state(
            UpdateState(last_checked=123.0, last_seen_tag="v0.2.0"), path
        )
        assert updates.read_state(path) == UpdateState(123.0, "v0.2.0")

    def test_missing_file_is_empty_state(self, tmp_path: Path) -> None:
        assert updates.read_state(tmp_path / "nope.json") == UpdateState()

    def test_invalid_json_is_empty_state(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        path.write_text("{not json", encoding="utf-8")
        assert updates.read_state(path) == UpdateState()

    def test_non_dict_json_is_empty_state(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        path.write_text("123", encoding="utf-8")
        assert updates.read_state(path) == UpdateState()

    def test_wrong_typed_fields_become_none(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        path.write_text(
            '{"last_checked": "soon", "last_seen_tag": 5}', encoding="utf-8"
        )
        assert updates.read_state(path) == UpdateState(None, None)

    def test_write_failure_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A serialization failure must clean up the temp file and not raise: the
        # inner BaseException handler unlinks, the outer handler logs at DEBUG.
        def boom(*_args: object, **_kwargs: object) -> None:
            raise ValueError("nope")

        monkeypatch.setattr(updates.json, "dump", boom)
        updates.write_state(UpdateState(1.0, "v1"), tmp_path / "u.json")
        # No temp files left behind by the failed write.
        assert list(tmp_path.glob("*.tmp")) == []


class TestDueForCheck:
    """The throttle decision."""

    def test_never_checked_is_due(self) -> None:
        assert updates.due_for_check(UpdateState(), now=1000.0) is True

    def test_elapsed_is_due(self) -> None:
        state = UpdateState(last_checked=0.0)
        assert updates.due_for_check(state, now=updates.CHECK_INTERVAL_SECONDS) is True

    def test_within_window_is_not_due(self) -> None:
        state = UpdateState(last_checked=1000.0)
        assert updates.due_for_check(state, now=1001.0, interval=10_000) is False


class TestFetchLatestReleaseTag:
    """The GitHub fetch, with ``urlopen`` patched (never real network)."""

    def _patch_urlopen(self, monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
        cm = MagicMock()
        cm.__enter__.return_value = object()
        monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *_a, **_k: cm)
        monkeypatch.setattr(updates.json, "load", lambda _resp: payload)

    def test_returns_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, {"tag_name": "v1.2.3"})
        assert updates._fetch_latest_release_tag() == "v1.2.3"

    def test_missing_tag_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, {"name": "no tag here"})
        assert updates._fetch_latest_release_tag() is None

    def test_non_dict_payload_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, ["unexpected"])
        assert updates._fetch_latest_release_tag() is None

    def test_network_error_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: object, **_k: object) -> None:
            raise OSError("offline")

        monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
        assert updates._fetch_latest_release_tag() is None


class TestRefreshState:
    """Persisting throttle state after a fetch attempt."""

    def test_successful_fetch_records_tag_and_time(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        updates.refresh_state(now=2000.0, path=path, fetch=lambda: "v0.9.0")
        assert updates.read_state(path) == UpdateState(2000.0, "v0.9.0")

    def test_failed_fetch_keeps_previous_tag(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        updates.write_state(UpdateState(1.0, "v0.5.0"), path)
        updates.refresh_state(now=10.0, path=path, fetch=lambda: None)
        # last_checked advances (so we don't re-probe), tag is preserved.
        assert updates.read_state(path) == UpdateState(10.0, "v0.5.0")


class TestSpawnDaemon:
    """The background runner."""

    def test_runs_target_on_a_thread(self) -> None:
        ran: list[int] = []
        thread = updates._spawn_daemon(lambda: ran.append(1))
        thread.join(timeout=2)
        assert ran == [1]
        assert thread.daemon is True


class TestUpdateEnabled:
    """Reading the opt-out flag from config without side effects."""

    def test_reads_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = MagicMock()
        fake.return_value.check_for_updates = False
        monkeypatch.setattr("keycast.settings.Settings", fake)
        assert updates._update_enabled() is False

    def test_defaults_true_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = MagicMock(side_effect=RuntimeError("corrupt"))
        monkeypatch.setattr("keycast.settings.Settings", fake)
        assert updates._update_enabled() is True


class TestNotifyPendingUpdate:
    """The orchestrator: cache-notify on the hot path, refresh in background."""

    def test_disabled_is_noop(self) -> None:
        notes: list[str] = []
        spawned: list[object] = []
        updates.notify_pending_update(
            notify=notes.append, enabled=False, spawn=spawned.append
        )
        assert notes == [] and spawned == []

    def test_enabled_none_reads_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(updates, "_update_enabled", lambda: False)
        notes: list[str] = []
        updates.notify_pending_update(notify=notes.append, spawn=lambda _f: None)
        assert notes == []

    def test_notifies_from_cache_when_newer(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        updates.write_state(
            UpdateState(last_checked=1000.0, last_seen_tag="v9.9.9"), path
        )
        notes: list[str] = []
        spawned: list[object] = []
        updates.notify_pending_update(
            notify=notes.append,
            current="0.1.0",
            enabled=True,
            state_path=path,
            now=1000.0,
            interval=10_000,  # within window: no refresh
            spawn=spawned.append,
        )
        assert any("9.9.9 available" in note for note in notes)
        assert spawned == []

    def test_no_notice_when_not_newer(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        updates.write_state(
            UpdateState(last_checked=1000.0, last_seen_tag="v0.0.1"), path
        )
        notes: list[str] = []
        updates.notify_pending_update(
            notify=notes.append,
            current="9.9.9",
            enabled=True,
            state_path=path,
            now=1000.0,
            interval=10_000,
            spawn=lambda _f: None,
        )
        assert notes == []

    def test_spawns_refresh_when_due(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"  # missing → due
        ran: list[str] = []

        def run_now(fn: object) -> None:
            fn()  # type: ignore[operator]  # run synchronously instead of threading
            ran.append("ran")

        updates.notify_pending_update(
            notify=lambda _m: None,
            current="0.1.0",
            enabled=True,
            state_path=path,
            now=2000.0,
            fetch=lambda: "v0.2.0",
            spawn=run_now,
        )
        assert ran == ["ran"]
        assert updates.read_state(path) == UpdateState(2000.0, "v0.2.0")

    def test_now_defaults_to_clock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "u.json"  # missing → due
        monkeypatch.setattr(updates.time, "time", lambda: 5000.0)
        spawned: list[object] = []
        updates.notify_pending_update(
            notify=lambda _m: None,
            current="0.1.0",
            enabled=True,
            state_path=path,
            fetch=lambda: None,
            spawn=spawned.append,
        )
        assert len(spawned) == 1
