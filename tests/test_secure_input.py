"""Tests for the macOS secure-input probe (best-effort, fail-open)."""

import ctypes
import logging
import types

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

    def test_call_failure_of_any_type_fails_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A probe raising a non-OSError type (e.g. AttributeError) still fails open.

        The call site catches broadly on purpose so a ctypes FFI fault stays
        named as a secure-input read failure rather than escaping to be
        mislabeled by ``KeyListener._on_press``.
        """

        def _boom() -> bool:
            raise AttributeError("symbol vanished mid-call")

        monkeypatch.setattr(secure_input, "_load_probe", lambda: _boom)
        assert secure_input.is_secure_input_active() is False


class TestLoadProbe:
    """The framework load itself: macOS-only, degrades to None, never raises."""

    def test_non_darwin_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Off macOS the probe is never loaded."""
        monkeypatch.setattr(secure_input.sys, "platform", "linux")
        assert secure_input._load_probe() is None

    def test_carbon_load_failure_returns_none_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A CDLL load failure degrades to None and surfaces above DEBUG."""
        monkeypatch.setattr(secure_input.sys, "platform", "darwin")

        def _cdll_boom(_name: str) -> object:
            raise OSError("cannot load Carbon")

        monkeypatch.setattr(secure_input.ctypes, "CDLL", _cdll_boom)
        with caplog.at_level(logging.WARNING, logger="keycast.secure_input"):
            assert secure_input._load_probe() is None
        assert any(
            "macos_secure_input_unavailable" in r.getMessage() for r in caplog.records
        )

    def test_missing_symbol_returns_none_and_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A framework lacking the symbol degrades to None (getattr default)."""
        monkeypatch.setattr(secure_input.sys, "platform", "darwin")

        class _EmptyLib:
            """Stands in for a CDLL with no ``IsSecureEventInputEnabled``."""

        monkeypatch.setattr(secure_input.ctypes, "CDLL", lambda _name: _EmptyLib())
        with caplog.at_level(logging.INFO, logger="keycast.secure_input"):
            assert secure_input._load_probe() is None
        assert any(
            "macos_secure_input_symbol_missing" in r.getMessage()
            for r in caplog.records
        )

    def test_success_pins_signature_and_returns_probe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On success the resolved probe has restype/argtypes pinned."""
        monkeypatch.setattr(secure_input.sys, "platform", "darwin")

        class _FakeSymbol:
            restype: object = None
            argtypes: object = None

            def __call__(self) -> bool:
                return False

        symbol = _FakeSymbol()
        # Key the fake lib off the real symbol name via setattr, so the test
        # stays coupled to the constant the code resolves (and vulture does not
        # see a statically-defined-but-unused attribute).
        lib = types.SimpleNamespace()
        setattr(lib, secure_input._SECURE_INPUT_SYMBOL, symbol)

        monkeypatch.setattr(secure_input.ctypes, "CDLL", lambda _name: lib)
        probe = secure_input._load_probe()
        assert probe is symbol
        assert symbol.restype is ctypes.c_bool
        assert symbol.argtypes == []
