"""Tests for update-check orchestration (``keycast.updates`` package root).

Network and threading are injected, never real: ``fetch`` and ``spawn`` are
passed explicitly (or internals patched), so nothing here reaches GitHub or
spawns a background thread unless the test opts in deterministically.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from keycast import updates
from keycast.updates.sources import InstallSource
from keycast.updates.state import UpdateState


class TestFormatNotice:
    """The user-facing notice string."""

    def test_format_notice(self) -> None:
        notice = updates.format_notice("v0.5.0", InstallSource.HOMEBREW_CASK)
        assert notice == "keycast 0.5.0 available — brew upgrade --cask keycast"


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
