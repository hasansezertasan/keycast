"""Install-source-aware update check (Phase 1: notify only).

This module knows three things and nothing about the display:

1. **How keycast was installed** (:func:`detect_install_source`) — so the notice
   can recommend the *right* update action instead of guessing. The frozen-vs-not
   split is reliable; the cask-vs-manual split is a path heuristic (see ADR-002).
2. **Whether a newer release exists** — comparing :data:`keycast.__version__`
   against the latest GitHub release tag with PEP 440 ordering (``packaging``).
3. **When it last looked** — throttle state in ``~/.keycast/update-check.json``,
   so it contacts GitHub at most once a day.

The orchestrator :func:`notify_pending_update` glues them together following the
npm pattern: show any *cached* newer-version notice instantly (no network on the
hot path), then refresh the cache in a background daemon thread for a later run.
Every network/file operation is best-effort — a failure is logged at ``DEBUG``
and swallowed, never blocking or crashing the caller. See
``docs/adr/002-update-check.md`` for the full design.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from keycast import __version__
from keycast.settings import UPDATE_CHECK_FILE_PATH

logger = logging.getLogger(__name__)

RELEASES_URL = "https://github.com/hasansezertasan/keycast/releases"
"""User-facing page the notice points at when no upgrade command fits."""

LATEST_RELEASE_API_URL = (
    "https://api.github.com/repos/hasansezertasan/keycast/releases/latest"
)
"""GitHub API endpoint for the latest (non-pre-release, non-draft) release."""

CHECK_INTERVAL_SECONDS: float = 24 * 60 * 60
"""Minimum time between network checks (once a day)."""

REQUEST_TIMEOUT_SECONDS: float = 5.0
"""Hard cap on the GitHub request so a slow network never stalls a refresh."""


class InstallSource(enum.Enum):
    """How this keycast process was installed.

    The value is the stable token used in logs; user-facing strings come from
    :func:`install_source_label` and :func:`recommended_action`.
    """

    PIP = "pip"
    PIPX = "pipx"
    UV_TOOL = "uv-tool"
    HOMEBREW_FORMULA = "homebrew-formula"
    HOMEBREW_CASK = "homebrew-cask"
    GITHUB_RELEASE = "github-release"
    UNKNOWN = "unknown"


_HOMEBREW_PATH_MARKERS = ("/cellar/", "/caskroom/", "/homebrew/", "/linuxbrew/")
"""Lower-cased path fragments that mark a Homebrew-managed location."""

_HOMEBREW_PREFIXES = ("/opt/homebrew/", "/usr/local/cellar/")
"""Lower-cased absolute prefixes that mark a Homebrew-managed location."""


def _looks_homebrew(location_posix: str) -> bool:
    """Return whether a lower-cased POSIX path looks Homebrew-managed.

    Args:
        location_posix: ``str(path).lower()`` with forward slashes.

    Returns:
        True if any Homebrew marker or prefix is present.
    """
    return any(marker in location_posix for marker in _HOMEBREW_PATH_MARKERS) or any(
        location_posix.startswith(prefix) for prefix in _HOMEBREW_PREFIXES
    )


def _is_under(location_posix: str, raw_dir: str) -> bool:
    """Return whether a POSIX path lives under a (possibly native) directory.

    The directory comes from an env var, so it may be a native Windows path with
    backslashes; it is normalized to lower-cased POSIX before comparison so the
    check works the same on every platform. An empty directory never matches —
    an env var being *set* is not by itself evidence of where the package lives.

    Args:
        location_posix: ``location.as_posix().lower()`` of the package.
        raw_dir: The candidate parent directory (env-supplied, any separator).

    Returns:
        True only when ``raw_dir`` is non-empty and contains ``location_posix``.
    """
    if not raw_dir:
        return False
    return location_posix.startswith(Path(raw_dir).as_posix().lower())


_HOMEBREW_CASK_PREFIXES = ("/opt/homebrew", "/usr/local")
"""Default Homebrew prefixes (Apple Silicon, Intel) checked for a cask receipt."""


def _homebrew_cask_receipt_exists() -> bool:
    """Return whether a Homebrew **cask** receipt for keycast is on disk.

    A cask moves ``keycast.app`` into ``/Applications`` — the same location a
    manual drag-install lands — but leaves a receipt under
    ``<brew-prefix>/Caskroom/keycast``. That receipt is the only thing that
    distinguishes the two, so it is the signal used to recommend
    ``brew upgrade --cask`` rather than the Releases page. ``HOMEBREW_PREFIX`` is
    honored for non-standard prefixes.

    Returns:
        True if a Caskroom receipt directory for keycast exists.
    """
    prefixes = [*_HOMEBREW_CASK_PREFIXES]
    custom = os.environ.get("HOMEBREW_PREFIX")
    if custom:
        prefixes.append(custom)
    return any((Path(prefix) / "Caskroom" / "keycast").exists() for prefix in prefixes)


def detect_install_source(
    *,
    frozen: bool | None = None,
    location: Path | None = None,
    env: dict[str, str] | None = None,
    cask_receipt_exists: Callable[[], bool] = _homebrew_cask_receipt_exists,
) -> InstallSource:
    """Classify how the running keycast was installed.

    Resolution is a first-match-wins tree (see ADR-002). ``sys.frozen`` splits
    "Python import" from "PyInstaller bundle"; a second, path-based signal is
    needed because a Homebrew **cask** ships the *same* frozen bundle as a manual
    Release download yet must still be updated via ``brew``.

    Args:
        frozen: Override for ``sys.frozen`` (defaults to the real value).
        location: Override for the path classified — the bundle executable when
            frozen, otherwise this package's location (defaults accordingly).
        env: Override for the process environment (defaults to ``os.environ``).
        cask_receipt_exists: Predicate for a Homebrew cask receipt (injectable
            for tests; defaults to a filesystem check).

    Returns:
        The detected :class:`InstallSource`; :attr:`InstallSource.UNKNOWN` when
        no rule matches (the notice then falls back to the Releases page).
    """
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    env = dict(os.environ) if env is None else env

    if frozen:
        location = Path(sys.executable) if location is None else location
        posix = location.as_posix().lower()
        # Either a Caskroom-path bundle, or the app moved to /Applications by a
        # cask (same path as a manual drag — disambiguated by the cask receipt).
        if _looks_homebrew(posix) or (
            "/applications/" in posix and cask_receipt_exists()
        ):
            return InstallSource.HOMEBREW_CASK
        return InstallSource.GITHUB_RELEASE

    location = Path(__file__) if location is None else location
    posix = location.as_posix().lower()

    if "/pipx/" in posix or _is_under(posix, env.get("PIPX_HOME", "")):
        return InstallSource.PIPX
    if (
        "/uv/tools/" in posix
        or "/share/uv/" in posix
        or _is_under(posix, env.get("UV_TOOL_DIR", ""))
    ):
        return InstallSource.UV_TOOL
    if _looks_homebrew(posix):
        return InstallSource.HOMEBREW_FORMULA
    return InstallSource.PIP


_UPGRADE_COMMANDS: dict[InstallSource, str] = {
    InstallSource.PIP: "pip install -U keycast",
    InstallSource.PIPX: "pipx upgrade keycast",
    InstallSource.UV_TOOL: "uv tool upgrade keycast",
    InstallSource.HOMEBREW_FORMULA: "brew upgrade keycast",
    InstallSource.HOMEBREW_CASK: "brew upgrade --cask keycast",
}

_SOURCE_LABELS: dict[InstallSource, str] = {
    InstallSource.PIP: "pip",
    InstallSource.PIPX: "pipx",
    InstallSource.UV_TOOL: "uv tool",
    InstallSource.HOMEBREW_FORMULA: "Homebrew formula",
    InstallSource.HOMEBREW_CASK: "Homebrew cask",
    InstallSource.GITHUB_RELEASE: "GitHub release download",
    InstallSource.UNKNOWN: "unknown",
}


def recommended_action(source: InstallSource) -> str:
    """Return the upgrade command for ``source``, or the Releases URL.

    Args:
        source: The detected install source.

    Returns:
        A package-manager command when one fits; otherwise :data:`RELEASES_URL`
        (for a manual Release download or an undetermined source, where guessing
        a command would be wrong).
    """
    return _UPGRADE_COMMANDS.get(source, RELEASES_URL)


def install_source_label(source: InstallSource) -> str:
    """Return the human-readable label for ``source`` (used by ``keycast info``).

    Args:
        source: The detected install source.

    Returns:
        A short label such as ``"Homebrew cask"``.
    """
    return _SOURCE_LABELS[source]


def _strip_v(tag: str) -> str:
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
        return Version(_strip_v(latest)) > Version(_strip_v(current))
    except InvalidVersion:
        return False


def format_notice(latest: str, source: InstallSource) -> str:
    """Build the user-facing "update available" line.

    Args:
        latest: The newer release tag (a leading ``v`` is dropped for display).
        source: The detected install source, selecting the recommended action.

    Returns:
        e.g. ``"keycast 0.5.0 available — brew upgrade --cask keycast"``.
    """
    return f"keycast {_strip_v(latest)} available — {recommended_action(source)}"


@dataclass(frozen=True)
class UpdateState:
    """Persisted throttle state for the update check.

    Attributes:
        last_checked: Epoch seconds of the last network check, or ``None`` if
            never checked.
        last_seen_tag: The latest release tag seen on the last successful fetch,
            or ``None`` if unknown.
    """

    last_checked: float | None = None
    last_seen_tag: str | None = None


def read_state(path: Path = UPDATE_CHECK_FILE_PATH) -> UpdateState:
    """Read the throttle state, degrading to an empty state on any problem.

    A missing, unreadable, or malformed file yields a default
    :class:`UpdateState` (treated as "never checked"), mirroring the defensive
    posture of ``Settings.create_settings_file``.

    Args:
        path: The state file path.

    Returns:
        The parsed state, or an empty :class:`UpdateState` on any error.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return UpdateState()
    if not isinstance(raw, dict):
        return UpdateState()
    last_checked = raw.get("last_checked")
    last_seen_tag = raw.get("last_seen_tag")
    return UpdateState(
        last_checked=last_checked if isinstance(last_checked, (int, float)) else None,
        last_seen_tag=last_seen_tag if isinstance(last_seen_tag, str) else None,
    )


def write_state(state: UpdateState, path: Path = UPDATE_CHECK_FILE_PATH) -> None:
    """Atomically write the throttle state, best-effort.

    Writes to a temp file in the same directory and ``os.replace``s it so a crash
    mid-write cannot leave a truncated file. Any failure is logged at ``DEBUG``
    and swallowed — persisting the throttle state must never break the app.

    Args:
        state: The state to persist.
        path: The destination path.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(
                    {
                        "last_checked": state.last_checked,
                        "last_seen_tag": state.last_seen_tag,
                    },
                    tmp_file,
                )
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    except Exception:
        logger.debug("Could not write update-check state to %s", path, exc_info=True)


def due_for_check(
    state: UpdateState, now: float, interval: float = CHECK_INTERVAL_SECONDS
) -> bool:
    """Return whether enough time has elapsed to check again.

    Args:
        state: The current throttle state.
        now: Current epoch seconds.
        interval: Minimum seconds between checks.

    Returns:
        True if never checked or the interval has elapsed.
    """
    return state.last_checked is None or (now - state.last_checked) >= interval


def _fetch_latest_release_tag(timeout: float = REQUEST_TIMEOUT_SECONDS) -> str | None:
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


def refresh_state(
    now: float,
    *,
    path: Path = UPDATE_CHECK_FILE_PATH,
    fetch: Callable[[], str | None] = _fetch_latest_release_tag,
) -> None:
    """Fetch the latest tag and persist updated throttle state.

    ``last_checked`` is recorded even when the fetch fails, so a persistently
    offline machine is not re-probed on every invocation; ``last_seen_tag`` is
    only advanced on a successful fetch (otherwise the previous value is kept).

    Args:
        now: Epoch seconds to record as the check time.
        path: The state file path.
        fetch: The tag fetcher (injectable for tests).
    """
    tag = fetch()
    previous = read_state(path)
    write_state(
        UpdateState(last_checked=now, last_seen_tag=tag or previous.last_seen_tag),
        path,
    )


def _spawn_daemon(target: Callable[[], None]) -> threading.Thread:
    """Run ``target`` on a daemon thread so it never blocks process exit.

    Args:
        target: The zero-arg callable to run.

    Returns:
        The started thread (returned for tests to join on).
    """
    thread = threading.Thread(target=target, name="keycast-update-check", daemon=True)
    thread.start()
    return thread


def _update_enabled() -> bool:
    """Read the ``check_for_updates`` flag from config without side effects.

    Loads settings via the JSON source (no first-run write, unlike
    ``create_settings_file``). A missing or corrupt config degrades to the
    default (enabled); real corrupt-config recovery happens on the app path.

    Returns:
        Whether automatic update checks are enabled.
    """
    try:
        from keycast.settings import Settings

        return bool(Settings().check_for_updates)
    except Exception:
        return True


def notify_pending_update(
    *,
    notify: Callable[[str], None],
    current: str = __version__,
    enabled: bool | None = None,
    state_path: Path = UPDATE_CHECK_FILE_PATH,
    now: float | None = None,
    interval: float = CHECK_INTERVAL_SECONDS,
    fetch: Callable[[], str | None] = _fetch_latest_release_tag,
    spawn: Callable[[Callable[[], None]], object] = _spawn_daemon,
) -> None:
    """Surface a cached update notice and refresh the cache in the background.

    The hot path does **no** network I/O: it reads the cached state and, if a
    newer version than ``current`` is already known, calls ``notify`` once. When
    the throttle window has elapsed it then schedules a background refresh whose
    result surfaces on a *later* invocation.

    Args:
        notify: Sink for the notice string (overlay ``show_text`` for the GUI,
            an stderr writer for the CLI). Called at most once.
        current: The installed version to compare against.
        enabled: The opt-out flag; when ``None`` it is read from config.
        state_path: The throttle state file path.
        now: Current epoch seconds (defaults to ``time.time()``).
        interval: Minimum seconds between background refreshes.
        fetch: The tag fetcher (injectable for tests).
        spawn: Runs the refresh callable (a daemon thread by default; tests pass
            a synchronous runner).
    """
    if enabled is None:
        enabled = _update_enabled()
    if not enabled:
        return

    now = time.time() if now is None else now
    state = read_state(state_path)

    if state.last_seen_tag and is_newer(state.last_seen_tag, current):
        notify(format_notice(state.last_seen_tag, detect_install_source()))

    if due_for_check(state, now, interval):
        spawn(lambda: refresh_state(now, path=state_path, fetch=fetch))
