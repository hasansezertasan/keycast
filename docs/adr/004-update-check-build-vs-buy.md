# ADR-004: Update check — build the notifier, buy the self-updater

## Status

Accepted — 2026-06-25. Records the build-vs-buy decision for the update
mechanism after surveying existing packages (the project's standing preference is
to reuse a library before rolling our own). Relates to
[ADR-002](002-update-check.md) (Phase 1 notify) and
[ADR-003](003-self-update.md) (Phase 2 self-update). Triggered by a review note
that `keycast.updates` felt long to maintain.

## Context

`keycast.updates` (Phase 1) is **504 lines, but only ~163 are code** — the rest
is docstrings (house style) and blanks. The perceived weight comes from the
*number of concerns* it carries, not raw logic:

1. **Install-source detection** — pip / pipx / uv / Homebrew-formula /
   Homebrew-cask / GitHub-Release → the right upgrade action. This is the
   branchy, bespoke part, and the one that has already produced two bugs (Windows
   `UV_TOOL_DIR` false-positive; `/Applications` cask receipt).
2. **Version check** — fetch the latest GitHub release tag, PEP 440 compare
   (~40 stdlib lines).
3. **Throttle state + orchestration** — `update-check.json`, the once-a-day
   gate, the npm-style notify-from-cache + background refresh.

Before adding more, we surveyed packages that "handle updates."

### Packages evaluated — notify (Phase 1)

| Library | What it does | Fit |
|---|---|---|
| [`check4updates`](https://pypi.org/project/check4updates/) | PyPI check + **built-in throttle**, unobtrusive | Closest in spirit — but **PyPI-only** |
| [`update-checker`](https://pypi.org/project/update-checker/) | PyPI check → running-vs-available result | PyPI-only; older |
| [`outdated`](https://github.com/alexmojaki/outdated) | `check_outdated()` + cache | PyPI-only |
| [`lastversion`](https://pypi.org/project/lastversion/) | Latest version from **GitHub releases** (and other forges) | Matches our source, but heavy / CLI-oriented (pulls `requests`) |

**The gap:** every one solves only concern #2 (the ~40 lines we already have in
stdlib). **None** does concern #1 — install-source routing is keycast-specific;
no general package answers "what command should *this* install use to update."
And the version libraries check **PyPI**, whereas keycast's releases live on
**GitHub** (hatch-vcs tags), so adopting one would also change *what* we check.

### Packages evaluated — self-update (Phase 2)

| Library | Status | Notes |
|---|---|---|
| [`tufup`](https://github.com/dennisvang/tufup) | **Maintained** | Successor to PyUpdater; built on **python-tuf** (real signing/verification); **packaging-agnostic** (works with PyInstaller bundles) |
| [`PyUpdater`](https://github.com/Digital-Sapphire/PyUpdater) | **Archived** | PyInstaller auto-updater; no longer maintained — avoid |
| `updater4pyi` | Stale | Old, unmaintained |

## Decision

1. **Build the Phase 1 notifier in-house, with stdlib.** Do **not** adopt a
   notify library. Keep `urllib` for the one GitHub-Releases GET; keep `packaging`
   (already chosen in ADR-002) for the compare.
2. **Buy the Phase 2 self-updater.** Prefer **`tufup`** as the "buy" answer to
   ADR-003's Sparkle-vs-custom-vs-OS-installer question; PyUpdater is archived and
   is explicitly *not* an option. (Decided in ADR-003; recorded here for the
   build-vs-buy through-line.)
3. **Harden the non-frozen detection with stdlib `importlib.metadata`.** Read the
   `INSTALLER` record (pip/uv stamp it) as a primary signal for the pip-vs-uv
   split, with the existing path heuristics retained as the fallback and as the
   *only* way to tell pipx and Homebrew-formula apart (both install via pip, so
   `INSTALLER` reads `"pip"` for both). This reduces — but cannot eliminate —
   reliance on path matching.
4. **Split `keycast.updates` into a package by concern** to address
   maintainability without a dependency:
   - `updates/sources.py` — install-source detection (the fragile part, isolated)
   - `updates/versions.py` — GitHub fetch + PEP 440 compare
   - `updates/state.py` — throttle state file
   - `updates/__init__.py` — orchestration (`notify_pending_update`) + public API

## Rationale

- **No library removes the long part.** The maintenance weight is concern #1
  (detection); the libraries cover concern #2. Adopting one would leave the
  fragile code in place *and* add a dependency.
- **Wrong source.** Notify libraries target PyPI; keycast releases are on GitHub.
- **Bundle + security cost.** keycast ships as a **PyInstaller** bundle. Adding an
  HTTP-checker dependency (some pull `requests`) grows the bundle and the security
  surface to save ~30 lines — the opposite of ADR-002's deliberate "stdlib-only,
  zero new HTTP dependency" stance.
- **Self-update is the opposite calculus.** There, a correct implementation is
  large and security-critical (signature verification, atomic swap, relaunch).
  `tufup` is maintained and built on a real security model (TUF); reinventing that
  by hand is exactly the kind of thing to *buy*.
- **`INSTALLER` is a more honest signal than a path guess** for the cases it
  covers, and it is stdlib — no dependency, consistent with (3).

## Consequences

- **Phase 1 stays dependency-light** (`packaging` remains the only added runtime
  dep). The notifier is now a small package, not one 500-line module.
- **Detection is partly authoritative, partly heuristic** — documented limit:
  `INSTALLER` cannot distinguish pipx from pip or Homebrew-formula from pip, so
  those still rely on path markers (`/pipx/`, Homebrew prefixes). The `UNKNOWN`
  fallback (Releases page) from ADR-002 remains the safety net.
- **Phase 2 is steered toward `tufup`** (see ADR-003); the eventual Phase 2 ADR
  will confirm it against Sparkle/WinSparkle when the work is picked up.
- **Public API is unchanged** by the split: `keycast.updates` still exports
  `notify_pending_update`, `detect_install_source`, `install_source_label`, and
  `InstallSource`; `cli.py` / `application.py` imports do not change.
