"""Detect macOS secure keyboard entry, so secret input can be masked.

macOS lets an app enable *secure event input* while the user types into a
password field (or a Touch ID / authentication prompt). While it is active the
window server withholds keystrokes from other listeners -- which is also why
pynput misses release events during those windows (see
:data:`keycast.listeners._MODIFIER_STALE_SECONDS`). ``IsSecureEventInputEnabled``
(Carbon / HIToolbox) reports that state without a prompt or special entitlement,
so :class:`keycast.listeners.KeyListener` can suppress the label instead of
rendering a typed password onto the overlay.

This is the cleanest of the three platforms: Windows exposes no global
"secure field" flag and X11 none at all, so detection is macOS-only and
best-effort. The public entry point, :func:`is_secure_input_active`, returns
``False`` (fail *open* -- capture normally) on every non-macOS host and whenever
the symbol cannot be read, because failing *closed* would blank the overlay
indefinitely and read as a broken app rather than a protected one.
"""

import ctypes
import logging
import sys
from collections.abc import Callable

from keycast.logging_setup import format_event

# The Carbon umbrella framework re-exports HIToolbox, where
# ``IsSecureEventInputEnabled`` lives. Loading Carbon (rather than reaching into
# HIToolbox's private path) keeps this on the same supported surface as the
# ApplicationServices load in ``application.py``.
_MACOS_CARBON_FRAMEWORK = "/System/Library/Frameworks/Carbon.framework/Carbon"
_SECURE_INPUT_SYMBOL = "IsSecureEventInputEnabled"

# The resolved ``() -> bool`` probe, cached after the first successful load so the
# per-keystroke hot path does not reload the framework each press. ``None`` means
# "not yet resolved"; ``_load_failed`` distinguishes "resolved to nothing" from
# "never tried" so a broken load is logged once, not on every keystroke.
_probe: Callable[[], bool] | None = None
_load_failed = False


def _load_probe() -> Callable[[], bool] | None:
    """Resolve ``IsSecureEventInputEnabled`` into a ``() -> bool`` callable.

    The framework load mirrors the ``ctypes.CDLL`` load in
    :meth:`keycast.application.Keycast._macos_permission_precheck`; the
    symbol-resolution steps (fetch the symbol, pin its ``restype``/``argtypes``,
    degrade to ``None`` rather than raise) mirror
    :meth:`keycast.application.Keycast._read_macos_permission`, which receives an
    already-loaded ``CDLL``. Returns ``None`` off macOS and whenever the
    framework or symbol is unavailable.
    """
    logger = logging.getLogger(__name__)
    if sys.platform != "darwin":
        return None
    try:
        carbon = ctypes.CDLL(_MACOS_CARBON_FRAMEWORK)
    except (OSError, TypeError, ValueError, ctypes.ArgumentError) as exc:
        # Carbon should always load on macOS; a failure is a genuine host anomaly
        # worth surfacing above DEBUG, matching the ApplicationServices path.
        logger.warning(
            format_event(
                "macos_secure_input_unavailable",
                reason=type(exc).__name__,
                detail=str(exc),
            )
        )
        return None
    probe = getattr(carbon, _SECURE_INPUT_SYMBOL, None)
    if probe is None:
        logger.info(
            format_event(
                "macos_secure_input_symbol_missing", symbol=_SECURE_INPUT_SYMBOL
            )
        )
        return None
    probe.restype = ctypes.c_bool
    probe.argtypes = []
    return probe


def is_secure_input_active() -> bool:
    """Return whether macOS secure keyboard entry is currently active.

    Best-effort and macOS-only: returns ``False`` on other platforms and whenever
    the probe cannot be loaded or raises, so a host without the signal keeps
    capturing normally rather than silently blanking the overlay.

    Returns:
        ``True`` only when macOS reports secure event input is enabled.
    """
    global _probe, _load_failed
    if _probe is None and not _load_failed:
        _probe = _load_probe()
        _load_failed = _probe is None
    if _probe is None:
        return False
    try:
        return bool(_probe())
    except Exception as exc:
        # Catch broadly on purpose: this is a ctypes FFI call, whose fault set is
        # not limited to the load-time tuple (a wrongly pinned or vanished symbol
        # can surface AttributeError/SystemError, etc.). Catching Exception keeps
        # the fault named as ``macos_secure_input_read_failed`` instead of letting
        # it propagate into ``KeyListener._on_press`` -- whose broad catch would
        # mislabel a detection fault as ``key_format_error``. A symbol that loaded
        # but raises on call is unexpected on macOS; log at INFO (not DEBUG) so it
        # is visible, but never let it kill the keystroke.
        logging.getLogger(__name__).info(
            format_event(
                "macos_secure_input_read_failed",
                reason=type(exc).__name__,
                detail=str(exc),
            )
        )
        return False
