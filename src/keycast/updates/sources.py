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
    SCOOP = "scoop"
    SCOOP_GLOBAL = "scoop-global"
    MICROSOFT_STORE = "microsoft-store"
    MAC_APP_STORE = "mac-app-store"
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

    Matching is at a path boundary, not a bare prefix: a sibling whose name
    merely *starts with* ``raw_dir`` (``D:\\toolsX`` vs root ``D:\\tools``) is not
    "under" it, so the location must equal the root or sit beneath its trailing
    separator.

    Returns:
        True only when ``raw_dir`` is non-empty and contains ``location_posix``.
    """
    if not raw_dir:
        return False
    root = Path(raw_dir).as_posix().lower().rstrip("/")
    return location_posix == root or location_posix.startswith(root + "/")


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


def _mas_receipt_exists() -> bool:
    """Return whether a Mac App Store receipt sits in the running bundle.

    A MAS-distributed ``.app`` carries ``Contents/_MASReceipt/receipt``. App
    Store apps install into ``/Applications`` — the same place as a cask or a
    manual drag-install — so this receipt is the only reliable signal that
    distinguishes it from a cask / drag-install (ADR-011), the macOS-store
    analogue of the Caskroom receipt. ``sys.executable`` is
    ``<bundle>/Contents/MacOS/keycast``, so the receipt is one level up from
    ``MacOS`` under ``Contents``.

    Guarded by a macOS platform check: only a MAS build carries this receipt, so
    a stray ``_MASReceipt`` on another OS must never classify as
    :data:`InstallSource.MAC_APP_STORE`.

    Any ``OSError`` from the probe degrades to ``False`` — detection is
    best-effort, so an unreadable path falls through to the next branch rather
    than crashing the caller (mirrors :func:`_read_installer`).

    Returns:
        True if running on macOS and the receipt exists inside the bundle.
    """
    if sys.platform != "darwin":
        return False
    try:
        return (Path(sys.executable).parent.parent / "_MASReceipt" / "receipt").exists()
    except OSError:
        return False


_INSTALLER_MARKER_NAME = ".install-source"
"""Sentinel file the Windows installer drops beside ``keycast.exe``.

The Inno Setup installer and the plain ``.zip`` ship the *same* frozen
PyInstaller bundle, so the only thing that tells an installed copy from an
extracted one is this extra file — the Windows analogue of the macOS Caskroom
receipt. Inno writes it (it is not part of ``dist/keycast/``, so the zip never
contains it); its presence — checked only on Windows, see
:func:`_installer_marker_exists` — flips ``GITHUB_RELEASE`` to
``WINDOWS_INSTALLER``.
"""


def _installer_marker_exists() -> bool:
    """Return whether the Windows-installer marker sits beside the executable.

    Checks for :data:`_INSTALLER_MARKER_NAME` next to ``sys.executable`` (the
    frozen ``keycast.exe``). The zip extraction has no such file, so this is the
    signal used to recommend the installer/uninstall path over a zip re-download.

    Guarded by a Windows platform check: only the Inno installer writes this
    marker, so a stray ``.install-source`` beside a frozen macOS/Linux build must
    never classify as :data:`InstallSource.WINDOWS_INSTALLER`.

    Returns:
        True if running on Windows and the marker file exists alongside the
        running executable.
    """
    if sys.platform != "win32":
        return False
    return (Path(sys.executable).parent / _INSTALLER_MARKER_NAME).exists()


_SCOOP_PATH_MARKER = "/scoop/apps/keycast/"
"""Lower-cased POSIX fragment marking a per-user Scoop-managed keycast install.

Scoop extracts the *same* ``keycast-windows.zip`` bundle as a manual download —
no ``.install-source`` marker, no Caskroom-style receipt — under
``~/scoop/apps/keycast/current/``. The Scoop signal is therefore the *location*
itself: this fragment for the default per-user root, plus the ``SCOOP`` env var
for a custom one (see :func:`_scoop_source`).
"""

_SCOOP_GLOBAL_PATH_MARKER = "/programdata/scoop/apps/keycast/"
"""Lower-cased POSIX fragment marking a **global** Scoop install.

``scoop install -g`` lands under ``C:\\ProgramData\\scoop`` (or a custom
``SCOOP_GLOBAL`` root). A global install updates with ``-g`` and elevation
(``sudo scoop update keycast -g``), so it is a *distinct* source from the
per-user one — plain ``scoop update keycast`` would not touch it. Checked first,
since a global path also contains :data:`_SCOOP_PATH_MARKER`.
"""


_MS_STORE_PATH_MARKER = "/windowsapps/"
"""Lower-cased POSIX fragment marking a Microsoft Store (MSIX) install.

The Store-signed MSIX (ADR-009) deploys the *same* frozen bundle as every other
Windows channel — no ``.install-source`` marker, no receipt — under
``C:\\Program Files\\WindowsApps\\<PackageFamilyName>…``, so, as with Scoop, the
*location* is the signal. The ``WindowsApps`` tree is ACL-locked and owned by
the Store's deployment stack; nothing else installs there, which makes the
fragment a safe location-only predicate.
"""


def _scoop_source(location_posix: str, env: dict[str, str]) -> InstallSource | None:
    """Classify a frozen bundle as a global / per-user Scoop install, or neither.

    Global is tested first (its default path also contains the per-user marker):
    the ``C:\\ProgramData\\scoop`` fragment or a custom ``SCOOP_GLOBAL`` root.
    Per-user is then the default-root fragment or a custom ``SCOOP`` root. Env
    roots are matched via :func:`_is_under`, so a var that is merely *set* (empty,
    or pointing elsewhere) never matches — only a bundle that truly lives under it.

    Args:
        location_posix: ``location.as_posix().lower()`` of the bundle executable.
        env: The process environment to consult for the Scoop root vars.

    Returns:
        :attr:`InstallSource.SCOOP_GLOBAL`, :attr:`InstallSource.SCOOP`, or
        ``None`` when the location is not Scoop-managed.
    """
    if _SCOOP_GLOBAL_PATH_MARKER in location_posix or _is_under(
        location_posix, env.get("SCOOP_GLOBAL", "")
    ):
        return InstallSource.SCOOP_GLOBAL
    if _SCOOP_PATH_MARKER in location_posix or _is_under(
        location_posix, env.get("SCOOP", "")
    ):
        return InstallSource.SCOOP
    return None


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
    mas_receipt_exists: Callable[[], bool] = _mas_receipt_exists,
    installer_marker_exists: Callable[[], bool] = _installer_marker_exists,
    read_installer: Callable[[], str | None] = _read_installer,
) -> InstallSource:
    """Classify how the running keycast was installed.

    Resolution is a first-match-wins tree (see ADR-002 / ADR-005). ``sys.frozen``
    splits "Python import" from "PyInstaller bundle"; past that the signals are
    heuristic. A Homebrew **cask** ships the *same* frozen bundle as a manual
    Release download, so it is disambiguated by a Caskroom receipt; a **Mac App
    Store** build shares the ``/Applications`` location too and is disambiguated
    by its ``_MASReceipt`` (checked first).

    Args:
        frozen: Override for ``sys.frozen`` (defaults to the real value).
        location: Override for the path classified — the bundle executable when
            frozen, otherwise this package's location (defaults accordingly).
        env: Override for the process environment (defaults to ``os.environ``).
        cask_receipt_exists: Predicate for a Homebrew cask receipt (injectable;
            defaults to a filesystem check).
        mas_receipt_exists: Predicate for a Mac App Store receipt (injectable;
            defaults to a filesystem check inside the running bundle).
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
        # A Mac App Store .app installs into /Applications just like a cask or a
        # manual drag-install; the bundle's _MASReceipt is the only signal, and
        # it is checked first — before the cask branch (which also keys on
        # /Applications) — so a MAS install never misclassifies as a cask
        # (ADR-011).
        if mas_receipt_exists():
            return InstallSource.MAC_APP_STORE
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
        # Scoop extracts the same bundle as a manual download (no marker); its
        # location — ~/scoop or C:\ProgramData\scoop, or a custom SCOOP /
        # SCOOP_GLOBAL root — is the only signal, and per-user vs global get
        # different update commands. Checked before the GitHub-release fallback.
        scoop = _scoop_source(posix, env)
        if scoop is not None:
            return scoop
        # A Store-delivered MSIX (ADR-009) also ships the same bundle; it
        # deploys under the ACL-locked WindowsApps tree, so — like Scoop — the
        # location alone classifies it. Checked before the GitHub-release
        # fallback: the Store updates apps itself, and this source is what
        # keeps the notice from wrongly pointing Store users at the Releases
        # page.
        if _MS_STORE_PATH_MARKER in posix:
            return InstallSource.MICROSOFT_STORE
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
    InstallSource.SCOOP: "scoop update keycast",
    InstallSource.SCOOP_GLOBAL: "sudo scoop update keycast -g",
    # Not a command: the Store updates its apps itself, so the recommended
    # action is a statement of that fact rather than something to run — and
    # pointing a Store user at the Releases page would be wrong (ADR-009).
    InstallSource.MICROSOFT_STORE: (
        "updates are delivered automatically by the Microsoft Store"
    ),
    # Same statement-not-a-command shape as the Microsoft Store: the Mac App
    # Store updates its apps itself, and pointing a MAS user at the Releases
    # page would be wrong (ADR-011).
    InstallSource.MAC_APP_STORE: (
        "updates are delivered automatically by the Mac App Store"
    ),
}

_SOURCE_LABELS: dict[InstallSource, str] = {
    InstallSource.PIP: "pip",
    InstallSource.PIPX: "pipx",
    InstallSource.UV_TOOL: "uv tool",
    InstallSource.HOMEBREW_FORMULA: "Homebrew formula",
    InstallSource.HOMEBREW_CASK: "Homebrew cask",
    InstallSource.GITHUB_RELEASE: "GitHub release download",
    InstallSource.WINDOWS_INSTALLER: "Windows installer",
    InstallSource.SCOOP: "Scoop",
    InstallSource.SCOOP_GLOBAL: "Scoop (global)",
    InstallSource.MICROSOFT_STORE: "Microsoft Store",
    InstallSource.MAC_APP_STORE: "Mac App Store",
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
        A package-manager command when one fits (for the Microsoft Store or Mac
        App Store, a statement that the store updates the app itself); otherwise
        :data:`RELEASES_URL` (for a manual Release download, a
        Windows-installer copy, or an undetermined source, where guessing a
        command would be wrong — the user re-downloads the asset / installer
        from the Releases page).
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
