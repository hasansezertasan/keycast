"""Install-source-aware update check (Phase 1: notify only).

The package is split by concern (ADR-005):

- :mod:`keycast.updates.sources` — how keycast was installed → the right action.
- :mod:`keycast.updates.versions` — GitHub fetch + PEP 440 compare.
- :mod:`keycast.updates.state` — the once-a-day throttle state file.
- this module — orchestration (:func:`notify_pending_update`) and the public API.

:func:`notify_pending_update` follows the npm pattern: show any *cached*
newer-version notice instantly (no network on the hot path), then refresh the
cache on a background daemon thread for a later run. Every network/file operation
is best-effort — a failure is logged at ``DEBUG`` and swallowed, never blocking
or crashing the caller. See ``docs/adr/002-update-check.md`` for the full design.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from keycast import __version__
from keycast.settings import UPDATE_CHECK_FILE_PATH
from keycast.updates.sources import (
    InstallSource,
    detect_install_source,
    install_source_label,
    recommended_action,
)
from keycast.updates.state import (
    CHECK_INTERVAL_SECONDS,
    UpdateState,
    due_for_check,
    read_state,
    write_state,
)
from keycast.updates.versions import fetch_latest_release_tag, is_newer, strip_v

__all__ = [
    "InstallSource",
    "detect_install_source",
    "install_source_label",
    "notify_pending_update",
]

logger = logging.getLogger(__name__)


def format_notice(latest: str, source: InstallSource) -> str:
    """Build the user-facing "update available" line.

    Args:
        latest: The newer release tag (a leading ``v`` is dropped for display).
        source: The detected install source, selecting the recommended action.

    Returns:
        e.g. ``"keycast 0.5.0 available — brew upgrade --cask keycast"``.
    """
    return f"keycast {strip_v(latest)} available — {recommended_action(source)}"


def refresh_state(
    now: float,
    *,
    path: Path = UPDATE_CHECK_FILE_PATH,
    fetch: Callable[[], str | None] = fetch_latest_release_tag,
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
        logger.debug(
            "Could not read check_for_updates; defaulting to enabled", exc_info=True
        )
        return True


def notify_pending_update(
    *,
    notify: Callable[[str], None],
    current: str = __version__,
    enabled: bool | None = None,
    state_path: Path = UPDATE_CHECK_FILE_PATH,
    now: float | None = None,
    interval: float = CHECK_INTERVAL_SECONDS,
    fetch: Callable[[], str | None] = fetch_latest_release_tag,
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

    # Outer guard: this runs on a *foreground* path (Keycast.start on the main
    # thread; the Typer root callback for the CLI), so an unexpected raise here
    # would abort app startup or crash `version`/`info`. detect_install_source()
    # touches the filesystem and `notify` is a caller-supplied sink — neither is
    # contractually raise-free — so the whole hot path degrades silently at DEBUG
    # to honor the "never crash the caller" promise (ADR-002 offline-safety).
    try:
        now = time.time() if now is None else now
        state = read_state(state_path)

        if state.last_seen_tag and is_newer(state.last_seen_tag, current):
            notify(format_notice(state.last_seen_tag, detect_install_source()))

        if due_for_check(state, now, interval):
            spawn(lambda: refresh_state(now, path=state_path, fetch=fetch))
    except Exception:
        logger.debug("Update notice hot path failed", exc_info=True)
