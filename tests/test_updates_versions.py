"""Tests for version comparison and the GitHub fetch (``keycast.updates.versions``).

``urlopen`` is always patched — these tests never hit the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from keycast.updates import versions


class TestVersionComparison:
    """PEP 440 comparison and tag normalization."""

    @pytest.mark.parametrize(
        ("raw", "expected"), [("v0.3.0", "0.3.0"), ("V1.0", "1.0"), ("2.0", "2.0")]
    )
    def test_strip_v(self, raw: str, expected: str) -> None:
        assert versions.strip_v(raw) == expected

    def test_newer_is_true(self) -> None:
        assert versions.is_newer("v0.5.0", "0.4.9") is True

    def test_same_or_older_is_false(self) -> None:
        assert versions.is_newer("0.4.0", "0.4.0") is False
        assert versions.is_newer("0.3.0", "0.4.0") is False

    def test_dev_version_orders_below_release(self) -> None:
        # hatch-vcs dev build in a source checkout vs a clean release tag.
        assert versions.is_newer("v0.3.1", "0.3.1.dev4+g1234abc") is True

    def test_unparsable_latest_is_not_newer(self) -> None:
        assert versions.is_newer("not-a-version", "0.1.0") is False

    def test_unparsable_current_is_not_newer(self) -> None:
        # The `current`-side parse failure shares the except but needs its own case.
        assert versions.is_newer("1.0.0", "not-a-version") is False


class TestFetchLatestReleaseTag:
    """The GitHub fetch, with ``urlopen`` patched (never real network)."""

    def _patch_urlopen(self, monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
        cm = MagicMock()
        cm.__enter__.return_value = object()
        monkeypatch.setattr(versions.urllib.request, "urlopen", lambda *_a, **_k: cm)
        monkeypatch.setattr(versions.json, "load", lambda _resp: payload)

    def test_returns_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, {"tag_name": "v1.2.3"})
        assert versions.fetch_latest_release_tag() == "v1.2.3"

    def test_missing_tag_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, {"name": "no tag here"})
        assert versions.fetch_latest_release_tag() is None

    def test_non_dict_payload_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, ["unexpected"])
        assert versions.fetch_latest_release_tag() is None

    def test_network_error_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: object, **_k: object) -> None:
            raise OSError("offline")

        monkeypatch.setattr(versions.urllib.request, "urlopen", boom)
        assert versions.fetch_latest_release_tag() is None

    def test_request_carries_timeout_and_github_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The timeout (hard cap against a hung socket) and GitHub headers
        # (User-Agent is required; Accept selects the v3 JSON) are easy to drop in
        # a refactor and would silently reintroduce hangs / rate-limit 403s, so
        # pin them by capturing what `fetch` actually hands to urlopen.
        captured: dict[str, object] = {}
        cm = MagicMock()
        cm.__enter__.return_value = object()

        def fake_urlopen(request: object, timeout: float) -> object:
            captured["request"] = request
            captured["timeout"] = timeout
            return cm

        monkeypatch.setattr(versions.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(versions.json, "load", lambda _resp: {"tag_name": "v1.0"})

        assert versions.fetch_latest_release_tag() == "v1.0"
        assert captured["timeout"] == versions.REQUEST_TIMEOUT_SECONDS
        request = captured["request"]
        assert request.get_header("Accept") == "application/vnd.github+json"  # type: ignore[attr-defined]
        assert request.get_header("User-agent", "").startswith("keycast/")  # type: ignore[attr-defined]
