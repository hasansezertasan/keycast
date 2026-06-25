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


def strip_v(tag: str) -> str:
    """Drop a single leading ``v`` from a release tag (``v0.3.0`` -> ``0.3.0``).

    Args:
        tag: A release tag or version string.

    Returns:
        The tag without a leading ``v``.
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
            payload = json.load(response)
    except Exception:
        logger.debug("Update check could not reach GitHub", exc_info=True)
        return None
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    return tag if isinstance(tag, str) else None
