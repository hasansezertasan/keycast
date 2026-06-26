"""Tests for the throttle state file (``keycast.updates.state``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from keycast.updates import state
from keycast.updates.state import UpdateState


class TestStateFile:
    """Reading/writing the throttle state, including corruption recovery."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "update-check.json"
        state.write_state(UpdateState(last_checked=123.0, last_seen_tag="v0.2.0"), path)
        assert state.read_state(path) == UpdateState(123.0, "v0.2.0")

    def test_missing_file_is_empty_state(self, tmp_path: Path) -> None:
        assert state.read_state(tmp_path / "nope.json") == UpdateState()

    def test_invalid_json_is_empty_state(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        path.write_text("{not json", encoding="utf-8")
        assert state.read_state(path) == UpdateState()

    def test_non_dict_json_is_empty_state(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        path.write_text("123", encoding="utf-8")
        assert state.read_state(path) == UpdateState()

    def test_wrong_typed_fields_become_none(self, tmp_path: Path) -> None:
        path = tmp_path / "u.json"
        path.write_text(
            '{"last_checked": "soon", "last_seen_tag": 5}', encoding="utf-8"
        )
        assert state.read_state(path) == UpdateState(None, None)

    def test_write_failure_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A serialization failure must clean up the temp file and not raise: the
        # inner BaseException handler unlinks, the outer handler logs at DEBUG.
        def boom(*_args: object, **_kwargs: object) -> None:
            raise ValueError("nope")

        monkeypatch.setattr(state.json, "dump", boom)
        state.write_state(UpdateState(1.0, "v1"), tmp_path / "u.json")
        assert list(tmp_path.glob("*.tmp")) == []


class TestDueForCheck:
    """The throttle decision."""

    def test_never_checked_is_due(self) -> None:
        assert state.due_for_check(UpdateState(), now=1000.0) is True

    def test_elapsed_is_due(self) -> None:
        old = UpdateState(last_checked=0.0)
        assert state.due_for_check(old, now=state.CHECK_INTERVAL_SECONDS) is True

    def test_within_window_is_not_due(self) -> None:
        recent = UpdateState(last_checked=1000.0)
        assert state.due_for_check(recent, now=1001.0, interval=10_000) is False
