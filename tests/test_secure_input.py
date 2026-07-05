"""Tests for the macOS secure-input probe (best-effort, fail-open)."""

import pytest

from keycast import secure_input


@pytest.fixture(autouse=True)
def _reset_probe_cache() -> None:
    """Clear the module-level probe cache so each test resolves it fresh."""
    secure_input._probe = None
    secure_input._load_failed = False


class TestIsSecureInputActive:
    """The public predicate: macOS-only, best-effort, never raises."""

    def test_returns_bool_and_never_raises(self) -> None:
        """On any host the probe returns a plain bool without raising."""
        assert isinstance(secure_input.is_secure_input_active(), bool)

    def test_non_darwin_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Off macOS there is no signal, so it fails open (capture normally)."""
        monkeypatch.setattr(secure_input.sys, "platform", "linux")
        assert secure_input.is_secure_input_active() is False

    def test_read_failure_fails_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A probe that raises on call degrades to False, not an exception."""

        def _boom() -> bool:
            raise OSError("secure-input read failed")

        monkeypatch.setattr(secure_input, "_load_probe", lambda: _boom)
        assert secure_input.is_secure_input_active() is False

    def test_probe_is_loaded_once_and_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The framework probe resolves once, not on every keystroke."""
        calls = {"n": 0}

        def _counting_load() -> object:
            calls["n"] += 1
            return lambda: False

        monkeypatch.setattr(secure_input, "_load_probe", _counting_load)
        secure_input.is_secure_input_active()
        secure_input.is_secure_input_active()
        assert calls["n"] == 1

    def test_unavailable_probe_does_not_retry_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed load is remembered (via _load_failed), not retried each call."""
        calls = {"n": 0}

        def _failing_load() -> None:
            calls["n"] += 1
            return None

        monkeypatch.setattr(secure_input, "_load_probe", _failing_load)
        assert secure_input.is_secure_input_active() is False
        assert secure_input.is_secure_input_active() is False
        assert calls["n"] == 1
