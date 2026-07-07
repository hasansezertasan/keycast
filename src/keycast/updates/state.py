"""Throttle state for the update check (``~/.keycast/update-check.json``).

Kept separate from ``config.json`` on purpose: ``Settings`` is ``frozen`` and
rewritten atomically from defaults, so this mutable runtime state does not belong
there. Reads degrade to an empty state on any problem; writes are atomic and
best-effort (a failure is logged at ``DEBUG`` and swallowed), mirroring the
defensive posture of ``Settings.create_settings_file``.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from keycast.settings import UPDATE_CHECK_FILE_PATH

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS: float = 24 * 60 * 60
"""Minimum time between network checks (once a day)."""


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
    :class:`UpdateState` (treated as "never checked").

    Args:
        path: The state file path.

    Returns:
        The parsed state, or an empty :class:`UpdateState` on any error.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        # PEP 758 (3.14): ``ruff format`` normalizes a no-``as`` multi-except to
        # this bare form on our 3.14 floor -- it is valid and formatter-enforced,
        # not the Py2 syntax error it resembles. A missing/unreadable file
        # (OSError) or malformed JSON (ValueError) both degrade to an empty state.
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
                # Derive the JSON keys from the dataclass fields so a future
                # field rename can't silently drift the on-disk schema.
                json.dump(dataclasses.asdict(state), tmp_file)
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
