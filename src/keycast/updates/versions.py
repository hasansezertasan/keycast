"""Version comparison and the GitHub Releases fetch.

"Latest" is the ``tag_name`` of the GitHub *latest release* (drafts and
pre-releases excluded by the endpoint); "current" is :data:`keycast.__version__`.
They are compared with PEP 440 ordering via ``packaging`` so a hatch-vcs dev
version in a source checkout (e.g. ``0.3.1.dev4+g1234abc``) sorts correctly. The
fetch uses stdlib ``urllib`` and is best-effort: any failure yields ``None`` and
a ``DEBUG`` log line, never an exception (ADR-002's offline-safety).
"""

from __future__ import annotations

import json
import logging
import urllib.request

from packaging.version import InvalidVersion, Version

from keycast import __version__

logger = logging.getLogger(__name__)

LATEST_RELEASE_API_URL = (
    "https://api.github.com/repos/hasansezertasan/keycast/releases/latest"
)
"""GitHub API endpoint for the latest (non-pre-release, non-draft) release."""

REQUEST_TIMEOUT_SECONDS: float = 5.0
"""Hard cap on the GitHub request so a slow network never stalls a refresh."""

MAX_RESPONSE_BYTES: int = 1 << 20
"""Ceiling on the response body we will read (1 MiB).

The latest-release payload is a few KB; anything approaching this is a
compromised, MITM'd, or misdirected endpoint. Bounding the read keeps a hostile
or runaway body from exhausting memory on the background refresh thread. A
response at or over the cap is treated as a failed check (``None``)."""

_ALLOWED_URL_PREFIX = "https://api.github.com/"
"""The final response URL must still start with this.

``urllib`` follows redirects automatically and will happily follow a 30x to
``http://`` or another host, silently downgrading TLS. The tag is only
*displayed*, but a spoofed "update available -- run brew upgrade ..." notice is a
social-engineering vector, so a redirect that leaves HTTPS-on-GitHub is rejected
before the body is trusted."""


def strip_v(tag: str) -> str:
    """Drop a single leading ``v`` from a release tag (``v0.3.0`` -> ``0.3.0``).

    Case-insensitive: an uppercase ``V`` is stripped too (``V1.0`` -> ``1.0``).

    Args:
        tag: A release tag or version string.

    Returns:
        The tag without a leading ``v``/``V``.
    """
    return tag[1:] if tag[:1] in {"v", "V"} else tag


def is_newer(latest: str, current: str) -> bool:
    """Return whether ``latest`` is a strictly newer version than ``current``.

    Uses PEP 440 ordering via ``packaging`` so dev/local installed versions
    (e.g. ``0.3.1.dev4+g1234abc`` from hatch-vcs in a source checkout) sort
    correctly against a clean release tag. An unparsable version is treated as
    "not newer" rather than raising.

    Args:
        latest: The candidate newer version/tag (may carry a leading ``v``).
        current: The installed version (may carry a leading ``v``).

    Returns:
        True only if both parse and ``latest`` > ``current``.
    """
    try:
        return Version(strip_v(latest)) > Version(strip_v(current))
    except InvalidVersion:
        return False


def fetch_latest_release_tag(timeout: float = REQUEST_TIMEOUT_SECONDS) -> str | None:
    """Fetch the latest release tag from GitHub, or ``None`` on any failure.

    Best-effort and silent: network, timeout, rate-limit, and parse errors all
    degrade to ``None`` and a ``DEBUG`` log line (per ADR-002's offline-safety).

    Args:
        timeout: Socket timeout in seconds.

    Returns:
        The ``tag_name`` string (e.g. ``"v0.5.0"``), or ``None``.
    """
    request = urllib.request.Request(
        LATEST_RELEASE_API_URL,
        headers={
            "User-Agent": f"keycast/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Reject a redirect that left HTTPS-on-GitHub before trusting the body.
            final_url = response.geturl()
            if not final_url.startswith(_ALLOWED_URL_PREFIX):
                logger.debug("Update check redirected off-host to %s", final_url)
                return None
            # Read one byte past the cap so an over-size body is detectable rather
            # than silently truncated into a parseable-but-wrong payload.
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            logger.debug("Update check response exceeded %d bytes", MAX_RESPONSE_BYTES)
            return None
        payload = json.loads(raw)
    except Exception:
        # Network, timeout, rate-limit (HTTP 403/429), and JSON-parse errors all
        # land here; the traceback says which, so keep the message neutral rather
        # than asserting "could not reach GitHub" (wrong for a 403 or bad body).
        logger.debug("Update check failed", exc_info=True)
        return None
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    return tag if isinstance(tag, str) else None
