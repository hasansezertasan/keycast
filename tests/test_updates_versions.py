"""Tests for version comparison and the GitHub fetch (``keycast.updates.versions``).

``urlopen`` is always patched — these tests never hit the network.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from keycast.updates import versions

_ALLOWED_URL = "https://api.github.com/repos/hasansezertasan/keycast/releases/latest"


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

    def _patch_urlopen(
        self,
        monkeypatch: pytest.MonkeyPatch,
        payload: object,
        *,
        url: str = _ALLOWED_URL,
        raw: bytes | None = None,
    ) -> None:
        # Build a realistic response so the real read()/geturl()/json.loads path
        # runs: geturl() drives the redirect/scheme guard and read(n) drives the
        # size cap. ``raw`` overrides the body for the size-limit test.
        response = MagicMock()
        response.geturl.return_value = url
        response.read.return_value = (
            raw if raw is not None else json.dumps(payload).encode()
        )
        cm = MagicMock()
        cm.__enter__.return_value = response
        monkeypatch.setattr(versions.urllib.request, "urlopen", lambda *_a, **_k: cm)

    def test_returns_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, {"tag_name": "v1.2.3"})
        assert versions.fetch_latest_release_tag() == "v1.2.3"

    def test_missing_tag_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, {"name": "no tag here"})
        assert versions.fetch_latest_release_tag() is None

    def test_non_dict_payload_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_urlopen(monkeypatch, ["unexpected"])
        assert versions.fetch_latest_release_tag() is None

    def test_off_host_redirect_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A redirect that leaves HTTPS-on-GitHub is rejected before trusting the body.

        urllib follows 30x automatically; a spoofed release notice is a
        social-engineering vector, so a final URL off api.github.com yields None
        even if the (attacker-controlled) body parses.
        """
        self._patch_urlopen(
            monkeypatch, {"tag_name": "v9.9.9"}, url="http://evil.example/latest"
        )
        assert versions.fetch_latest_release_tag() is None

    def test_oversize_response_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A body larger than MAX_RESPONSE_BYTES is treated as a failed check."""
        # read(MAX+1) returns MAX+1 bytes -> over the cap -> None, before json.loads.
        oversize = b"x" * (versions.MAX_RESPONSE_BYTES + 1)
        self._patch_urlopen(monkeypatch, {"tag_name": "v1.0"}, raw=oversize)
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
        response = MagicMock()
        response.geturl.return_value = _ALLOWED_URL
        response.read.return_value = json.dumps({"tag_name": "v1.0"}).encode()
        cm = MagicMock()
        cm.__enter__.return_value = response

        def fake_urlopen(request: object, timeout: float) -> object:
            captured["request"] = request
            captured["timeout"] = timeout
            return cm

        monkeypatch.setattr(versions.urllib.request, "urlopen", fake_urlopen)

        assert versions.fetch_latest_release_tag() == "v1.0"
        assert captured["timeout"] == versions.REQUEST_TIMEOUT_SECONDS
        request = captured["request"]
        assert request.get_header("Accept") == "application/vnd.github+json"  # type: ignore[attr-defined]
        assert request.get_header("User-agent", "").startswith("keycast/")  # type: ignore[attr-defined]
