# ADR-003: In-place self-update for downloaded Release builds (Phase 2)

## Status

**Proposed — deferred.** Captures the design space for **Phase 2** of the update
mechanism (issue [#19](https://github.com/hasansezertasan/keycast/issues/19);
parent [#9](https://github.com/hasansezertasan/keycast/issues/9)). **Phase 1**
(install-source-aware *notify*) is specified in [ADR-002](002-update-check.md)
and implemented in PR #18 (in review at the time of writing); this ADR is the
contract for the *self-update* that Phase 1 deliberately leaves out. **Phase 2
depends on Phase 1 landing first** — it reuses Phase 1's `GITHUB_RELEASE`
detection gate (`keycast.updates`), which only exists once #18 merges.

This ADR is intentionally **not yet Accepted**: its macOS path is blocked on a
prerequisite (code signing) and its central build-vs-buy decision (Sparkle vs
custom) is an open question below. It will be revised to *Accepted* — and will
**supersede [ADR-001](001-desktop-app-packaging.md)'s "unsigned" stance** for
macOS — when the work is picked up.

## Context

ADR-002 routes every install channel to the *correct* update action and reserves
the `keycast update` verb for this phase. Recapping that channel matrix, only one
row is a self-update candidate:

| Channel | `InstallSource` | Phase 2 behavior |
|---|---|---|
| PyPI (`pip`/`uv`/`pipx`/`uvx`) | `PIP` / `PIPX` / `UV_TOOL` | unchanged — recommend the package-manager command |
| Homebrew formula | `HOMEBREW_FORMULA` | unchanged — `brew upgrade keycast` |
| Homebrew cask | `HOMEBREW_CASK` | unchanged — `brew upgrade --cask keycast` |
| **Manual GitHub Release download** | **`GITHUB_RELEASE`** | **self-update in place** |

Self-updating a package-manager-owned install would desync that manager's
receipts, so self-update is offered **only** for `GITHUB_RELEASE` — a manually
downloaded `.dmg`/`.zip` that nothing else manages. Phase 1 isolates this case
(frozen, and *not* under a Homebrew Caskroom receipt), so once it lands the gate
is already in place; what Phase 2 adds is the act of replacing the bundle, which
is the genuinely hard, platform-specific, signing-sensitive part.

## Decision (proposed)

1. **Introduce `keycast update`.** Explicit, user-initiated. For a
   `GITHUB_RELEASE` build it performs the update; for every other source it
   prints the same channel-appropriate command Phase 1 already shows (so the
   verb is safe and meaningful on all channels).
2. **Self-update only `GITHUB_RELEASE` builds.** Flow: resolve the latest release
   asset → download → **verify** → swap the bundle → relaunch.
3. **Verify before swap.** Minimum bar: SHA-256 published with the release;
   target: a real code signature (see signing below). A self-updater is a
   code-execution vector — an unverified artifact must never be executed.
4. **Platform mechanics:**
   - **Windows:** a running `.exe` cannot overwrite itself → rename the running
     binary aside, write the new one, relaunch, exit (or hand off to a tiny
     updater helper that swaps after exit).
   - **macOS:** swap the *whole* `.app` bundle (in-place file replacement breaks
     the signature); verify Developer-ID signature + notarization; relaunch.

### Phasing within Phase 2

- **Windows can ship first.** Its mechanics don't depend on the macOS signing
  question; a checksum-verified rename-relaunch is self-contained.
- **macOS waits on signing** (see Prerequisites). Shipping macOS self-update
  before notarization would mean either swapping an unsigned bundle (Gatekeeper
  friction persists) or building a verifier with nothing trustworthy to verify
  against.

## Open questions (must resolve before Accepted)

- **Build vs buy — the central decision.** Three families:
  - **Sparkle (macOS) + WinSparkle (Windows)** with a signed **appcast** feed:
    mature, handles the relaunch/swap dance and signature checks, but adds a
    framework + an appcast-publishing step to the release pipeline.
  - **Custom download-verify-swap** in `keycast.updates`: no new framework, full
    control, but re-implements the platform dances and signature verification
    that Sparkle already solves.
  - **OS installers** (`.pkg` / MSIX) with their own update channels: heavier
    packaging change, overlaps with ADR-001's PyInstaller decision.
- **Auto-apply vs prompt.** Should the Phase 1 passive notice on a
  `GITHUB_RELEASE` build offer a one-click apply, or always require explicit
  `keycast update`? (Likely a new opt-in setting, e.g. `auto_update`.)
- **Delta vs full** download (full is almost certainly fine at this size).
- **Rollback** if a swapped build fails to launch.

## Prerequisites

- **Apple Developer ID** (~US$99/yr) for Developer-ID signing + notarization —
  the hard blocker for the macOS path, and the trigger to supersede ADR-001.
- **Windows code-signing certificate** — desirable to avoid SmartScreen warnings
  on the replacement binary; not strictly required for the mechanism to work.
- A release-pipeline step to publish whatever the chosen mechanism consumes
  (per-asset SHA-256 today; an `appcast.xml` if Sparkle is chosen).

## Consequences

- **New ADR supersedes ADR-001's "unsigned" stance** (macOS) once accepted;
  signing/notarization become part of the release pipeline (`release.yml`).
- **Security surface:** self-update downloads and executes code — verification is
  mandatory, not optional; failures must abort the swap and leave the working
  build in place.
- **Settings (likely):** an `auto_update` opt-in distinct from
  `check_for_updates` (notify) — so a user can want notices without auto-apply.
- **`keycast.updates` grows** an updater path, or gains a thin wrapper around a
  chosen framework; either way the `GITHUB_RELEASE` gate from Phase 1 is reused.
- **No change for package-manager users** — they keep getting a recommended
  command and are never self-updated.
