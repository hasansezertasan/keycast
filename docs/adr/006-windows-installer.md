# ADR-006: Ship a Windows installer (Inno Setup) alongside the zip

## Status

Accepted — 2026-06-26. Implemented: `packaging/keycast.iss` + the
`.install-source` marker, the `build-windows` installer step in `release.yml`,
the per-PR compile check in `ci.yml`, and the `InstallSource.WINDOWS_INSTALLER`
classification in `keycast.updates.sources`. Builds on
[ADR-001](001-desktop-app-packaging.md) (the PyInstaller bundle) and
[ADR-002](002-update-check.md) / [ADR-005](005-updates-package-structure.md)
(install-source-aware update advice). Supersedes nothing.

## Context

ADR-001 ships Windows as `keycast-windows.zip` — the bare `dist/keycast/`
PyInstaller folder. Users extract it by hand: no Start Menu entry, no shortcuts,
no uninstaller, no Add/Remove-Programs presence. That is a poor experience for a
double-click GUI overlay, and it is the macOS-cask gap restated for Windows
([#7](https://github.com/hasansezertasan/keycast/issues/7)).

Three toolchain families were considered: **Inno Setup**, **NSIS**, and
**WiX/MSI**. All three can wrap a PyInstaller folder build and create a Start
Menu shortcut + uninstaller; the question was cost, not capability.

One constraint shapes everything: **Authenticode signing
([#6](https://github.com/hasansezertasan/keycast/issues/6)) is closed as not
planned** — it is gated on a paid OV/EV certificate, the same cost blocker that
deferred macOS signing in ADR-001. So the installer ships **unsigned**, exactly
like the bundle today. This rules out "the installer fixes SmartScreen" as a
motivation: the goal is install/uninstall hygiene, not publisher trust.

## Decision

- **Toolchain: Inno Setup.** Compile `packaging/keycast.iss` with `iscc.exe`,
  which **ships in GitHub's `windows-latest` runner image** — no
  toolchain-install step (if a future image drops InnoSetup, the CI compile gate
  fails and an install step is added). It wraps the existing `dist/keycast/`
  folder; no change to `keycast.spec`.
- **Ship both.** Add `keycast-setup.exe` as a release asset and **keep**
  `keycast-windows.zip`. The installer is for normal users; the zip stays the
  portable / no-admin / locked-down option.
- **User chooses scope at install time.** `PrivilegesRequiredOverridesAllowed =
  dialog` adds a wizard page offering per-user (`%LocalAppData%`, no UAC) or
  per-machine (`Program Files`, elevated); `{auto*}` constants resolve to the
  matching install dir, Start Menu group, and desktop shortcut. Per-user is the
  lowest-privilege default, which matters for an unsigned installer (no UAC
  prompt stacked on top of the SmartScreen warning).
- **New install source: `WINDOWS_INSTALLER`.** The installer drops a
  `.install-source` marker beside `keycast.exe`; `detect_install_source()` reads
  it to give correct update advice (point at the Releases page to download the
  new installer) instead of inheriting the zip's `GITHUB_RELEASE` advice.

## Rationale

- **Inno over NSIS/WiX.** All three are pre-installed on the runner, so the
  tiebreaker is authoring cost for *this* shape — a single-folder app needing one
  shortcut and an uninstaller. Inno expresses that in a short declarative `.iss`
  with built-in per-user/per-machine handling. NSIS needs more imperative
  boilerplate for the same result; WiX/MSI's component/GUID/upgrade-code ceremony
  buys Group-Policy/SCCM deployment that a single-user hobby overlay does not
  need. No capability is lost by choosing the simplest.
- **Keep the zip.** Dropping it would remove the only no-install-rights path, at
  near-zero cost to retain. The release already attaches multiple assets.
- **Marker file over the registry.** Inno always writes an uninstall registry
  key, so reading the registry (`winreg`) would also work — but a file beside the
  exe mirrors the **Caskroom-receipt** pattern already in `sources.py`: a
  filesystem predicate that is trivially injectable in tests and needs no
  platform-specific API. The marker is deliberately *not* part of
  `dist/keycast/`, so the `.zip` never carries it and zip installs keep
  classifying as `GITHUB_RELEASE`. `WINDOWS_INSTALLER` is a URL-fallback source
  (no package-manager upgrade command), so it points at the Releases page like
  `GITHUB_RELEASE` — the difference is honesty in `keycast info`, not a different
  mechanism.

## Consequences

- **Release pipeline:** `build-windows` gains an `iscc` step after the zip and
  uploads `keycast-setup.exe` plus `keycast-windows.zip`. The release stays
  **atomic** — a failed installer compile blocks `publish-pypi` like any other
  build failure — so `ci.yml`'s `build-windows` check now **also compiles
  `keycast.iss`** (with the script's `0.0.0` default) and asserts the `.exe`
  emerged, catching a broken script on the PR rather than at release.
- **Version source of truth:** the version is injected via `iscc
  /DMyAppVersion=<release version>`; the `.iss` defaults to `0.0.0` so it
  compiles without a tag (PR checks, local builds). This mirrors hatch-vcs
  deriving the Python `__version__` from the same tag.
- **Stable `AppId`:** the `.iss` hard-codes a fixed GUID `AppId`. It must never
  change, or upgrades would install side-by-side instead of replacing the prior
  version.
- **Still unsigned:** first run trips SmartScreen exactly as the zip does; the
  "More info → Run anyway" note in `README.md` stays. When a certificate is
  acquired (would reopen #6), sign **both** `keycast.exe` and
  `keycast-setup.exe`, and this ADR's "unsigned" stance should be revisited.
- **Tests:** `tests/test_updates_sources.py` covers the marker probe and the
  `WINDOWS_INSTALLER` branch; the module-load assertions in `sources.py` already
  fail fast if a new source lacks a label or an upgrade-command/fallback wiring.
- **Validation limit:** like the bundle (ADR-001), the installer cannot be built
  or run on the macOS dev machine. It is exercised only by the `build-windows` CI
  check (compile + asset-exists). A real install → Start Menu launch → uninstall
  on a clean Windows box remains a **manual** step before the first installer
  release.
