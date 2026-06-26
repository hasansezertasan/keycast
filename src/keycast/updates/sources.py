"""Install-source detection: how was this keycast process installed?

The detected :class:`InstallSource` drives the *right* update advice — a cask
user is told ``brew upgrade --cask``, a pipx user ``pipx upgrade``, and so on
(see ADR-002). The frozen-vs-not split is reliable; everything past it is a
heuristic, with an ``UNKNOWN`` fallback that points at the Releases page rather
than guessing a wrong command. Per ADR-005 the non-frozen path is anchored where
it can be on the stdlib ``INSTALLER`` record, falling back to path markers for
the cases that record cannot distinguish (pipx and Homebrew-formula both install
via pip, so both record ``"pip"``).
"""

from __future__ import annotations

import enum
import importlib.metadata
import os
import sys
from collections.abc import Callable
from pathlib import Path

RELEASES_URL = "https://github.com/hasansezertasan/keycast/releases"
"""User-facing page the notice points at when no upgrade command fits."""


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
    WINDOWS_INSTALLER = "windows-installer"
    UNKNOWN = "unknown"


_HOMEBREW_PATH_MARKERS = ("/cellar/", "/caskroom/", "/homebrew/", "/linuxbrew/")
"""Lower-cased path fragments that mark a Homebrew-managed location."""

_HOMEBREW_PREFIXES = ("/opt/homebrew/", "/usr/local/cellar/")
"""Lower-cased absolute prefixes that mark a Homebrew-managed location."""

_HOMEBREW_CASK_PREFIXES = ("/opt/homebrew", "/usr/local")
"""Default Homebrew prefixes (Apple Silicon, Intel) checked for a cask receipt."""


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


_INSTALLER_MARKER_NAME = ".install-source"
"""Sentinel file the Windows installer drops beside ``keycast.exe``.

The Inno Setup installer and the plain ``.zip`` ship the *same* frozen
PyInstaller bundle, so the only thing that tells an installed copy from an
extracted one is this extra file — the Windows analogue of the macOS Caskroom
receipt. Inno writes it (it is not part of ``dist/keycast/``, so the zip never
contains it); its presence flips ``GITHUB_RELEASE`` to ``WINDOWS_INSTALLER``.
"""


def _installer_marker_exists() -> bool:
    """Return whether the Windows-installer marker sits beside the executable.

    Checks for :data:`_INSTALLER_MARKER_NAME` next to ``sys.executable`` (the
    frozen ``keycast.exe``). The zip extraction has no such file, so this is the
    signal used to recommend the installer/uninstall path over a zip re-download.

    Returns:
        True if the marker file exists alongside the running executable.
    """
    return (Path(sys.executable).parent / _INSTALLER_MARKER_NAME).exists()


def _read_installer(dist_name: str = "keycast") -> str | None:
    """Return the recorded ``INSTALLER`` for the distribution, lower-cased.

    pip and uv stamp an ``INSTALLER`` file in the ``.dist-info`` (``"pip"`` /
    ``"uv"``); it is the most authoritative signal for the pip-vs-uv split. It is
    absent for a frozen bundle and cannot tell pipx or Homebrew-formula apart from
    pip (both install via pip), so callers still need path heuristics for those.

    Args:
        dist_name: Distribution to inspect.

    Returns:
        The lower-cased installer token, or ``None`` if unknown/unreadable.
    """
    try:
        text = importlib.metadata.distribution(dist_name).read_text("INSTALLER")
    except Exception:
        return None
    return text.strip().lower() if text else None


def detect_install_source(
    *,
    frozen: bool | None = None,
    location: Path | None = None,
    env: dict[str, str] | None = None,
    cask_receipt_exists: Callable[[], bool] = _homebrew_cask_receipt_exists,
    installer_marker_exists: Callable[[], bool] = _installer_marker_exists,
    read_installer: Callable[[], str | None] = _read_installer,
) -> InstallSource:
    """Classify how the running keycast was installed.

    Resolution is a first-match-wins tree (see ADR-002 / ADR-005). ``sys.frozen``
    splits "Python import" from "PyInstaller bundle"; past that the signals are
    heuristic. A Homebrew **cask** ships the *same* frozen bundle as a manual
    Release download, so it is disambiguated by a Caskroom receipt.

    Args:
        frozen: Override for ``sys.frozen`` (defaults to the real value).
        location: Override for the path classified — the bundle executable when
            frozen, otherwise this package's location (defaults accordingly).
        env: Override for the process environment (defaults to ``os.environ``).
        cask_receipt_exists: Predicate for a Homebrew cask receipt (injectable;
            defaults to a filesystem check).
        installer_marker_exists: Predicate for the Windows-installer marker
            (injectable; defaults to a filesystem check beside the executable).
        read_installer: Reader for the ``INSTALLER`` record (injectable; defaults
            to the stdlib metadata lookup).

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
        # A Windows installer ships the same frozen bundle as the zip; the marker
        # Inno drops beside the exe is the only thing that tells them apart.
        if installer_marker_exists():
            return InstallSource.WINDOWS_INSTALLER
        return InstallSource.GITHUB_RELEASE

    location = Path(__file__) if location is None else location
    posix = location.as_posix().lower()

    # pipx installs via pip (INSTALLER="pip") into a dedicated venv — the path is
    # the only signal, so it is checked before the INSTALLER-based uv split.
    if "/pipx/" in posix or _is_under(posix, env.get("PIPX_HOME", "")):
        return InstallSource.PIPX
    # uv stamps INSTALLER="uv"; path markers / env dir are the fallback.
    if (
        read_installer() == "uv"
        or "/uv/tools/" in posix
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
    InstallSource.WINDOWS_INSTALLER: "Windows installer",
    InstallSource.UNKNOWN: "unknown",
}

# Fail fast at import if a new InstallSource is added without wiring it up: every
# member needs a label, and every member except the URL-fallback sources (GitHub
# download / Windows installer / unknown — where guessing a command would be
# wrong, so the notice points at the Releases page to re-download) needs an
# upgrade command. Converts an otherwise-latent runtime KeyError into a loud
# developer error at module load.
assert set(_SOURCE_LABELS) == set(InstallSource), "every InstallSource needs a label"
assert set(_UPGRADE_COMMANDS) | {
    InstallSource.GITHUB_RELEASE,
    InstallSource.WINDOWS_INSTALLER,
    InstallSource.UNKNOWN,
} == set(InstallSource), "every non-URL-fallback InstallSource needs an upgrade command"


def recommended_action(source: InstallSource) -> str:
    """Return the upgrade command for ``source``, or the Releases URL.

    Args:
        source: The detected install source.

    Returns:
        A package-manager command when one fits; otherwise :data:`RELEASES_URL`
        (for a manual Release download, a Windows-installer copy, or an
        undetermined source, where guessing a command would be wrong — the user
        re-downloads the asset / installer from the Releases page).
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
