# ADR-014: Distribute keycast on the Mac App Store (sandboxed)

## Status

Proposed — 2026-07-05. Recorded **ahead of implementation** (DDD: this ADR is
the design contract), and explicitly **experimental**: it carries a bail-out
condition (see Consequences). Inherits ADR-013's **Apple Developer Program
gate** — it cannot ship until that fee is accepted — and builds on
[ADR-013](013-macos-signing-notarization.md) (signing infrastructure) and
[ADR-001](001-desktop-app-packaging.md) (the PyInstaller `.app`). The cask and
formula channels are unaffected — the Mac App Store (MAS) is an **additional**
channel, as ADR-009's Microsoft Store now is on Windows. Supersedes nothing.

## Context

The reflexive assumption — "a keystroke visualizer can't be sandboxed, so MAS is
impossible" — is **wrong for this app**, and the distinction is worth recording
precisely because it is subtle:

- macOS has **two** TCC permissions for input capture. **Accessibility** gates
  *active* event taps (modify/suppress events) and synthetic input, and is
  **not available to sandboxed apps** — this is the permission the "impossible"
  folklore is about. **Input Monitoring** gates *listen-only* event taps
  (`CGEventTapCreate` with `kCGEventTapOptionListenOnly`), is requestable by
  sandboxed apps via `CGRequestListenEventAccess`, and **is MAS-compatible**.
- keycast is on the permitted side of that line, verified empirically in this
  repo (per the ADR-001 verify-don't-trust rule): pynput's macOS backend
  (`pynput/_util/darwin.py`, `_create_event_tap`) selects
  `kCGEventTapOptionListenOnly` whenever `suppress=False` and no intercept is
  installed — and `listeners.py` never sets either. keycast *listens only*; it
  never suppresses or injects.
- **Existence proof:** Keystroke Pro (id 1572206224) and KeyScreen
  (id 6753302381) — keystroke visualizers of exactly this shape — are live on
  MAS today.

What *is* genuinely hard is the stack, not the policy: a **PyInstaller + Tk app
under App Sandbox** means every nested Mach-O signed with sandbox entitlements,
child processes inheriting them (`com.apple.security.inherit`), and Tk behaving
inside a container. Precedent is sparse; this is where MAS-bound Python apps
historically die, and why the design is staged with a bail-out rather than
committed unconditionally.

One sandbox side effect is load-bearing for the docs contract: under App
Sandbox, `Path.home()` resolves to the **container** home
(`~/Library/Containers/com.hasansezertasan.keycast/Data/`), so the config and
log paths documented as `~/.keycast/…` live inside the container for MAS
installs. The code (`settings.py`) is unchanged — the *docs* need a MAS note,
and `tests/test_docs_contract.py`'s pinned claims must stay true for the
non-MAS builds it actually tests.

## Decision

- **Pursue MAS in parallel with the notarized Developer ID channel** (ADR-013),
  which remains the primary macOS distribution and the fallback if MAS fails.
- **A separate MAS build variant** in `release.yml`: same `keycast.spec`
  bundle, signed with the **Apple Distribution** certificate and a dedicated
  `packaging/entitlements-mas.plist` — `com.apple.security.app-sandbox` (true),
  `com.apple.security.network.client` (the ADR-002 update check; harmless, and
  removing it would silently break `keycast info`), plus the PyInstaller
  hardened-runtime pair from ADR-013. Packaged as a `.pkg` via `productbuild`
  with an installer-signing certificate.
- **Upload manual first, automated later** — the same staging as ADR-009's
  Partner Center: first submission (listing, screenshots, privacy labels,
  review notes) is manual via Transporter / App Store Connect; automation is
  added only after one submission has survived App Review.
- **Review-notes strategy is part of the design:** cite the listen-only tap
  (Input Monitoring, not Accessibility), the always-visible overlay, the
  open-source repo, and an explicit "keystrokes are rendered, never stored or
  transmitted" privacy statement. The privacy nutrition label declares no data
  collection. Price: **free**.
- **New install source: `MAC_APP_STORE`.** Detected by the presence of
  `Contents/_MASReceipt/receipt` in the running bundle — a filesystem predicate
  mirroring the Caskroom-receipt pattern in `sources.py`, and following the same
  shape ADR-009 shipped for `MICROSOFT_STORE`: a location/receipt predicate plus
  a *statement-style* advice string (not a command) held in the upgrade-command
  map so the module-load assertion in `sources.py` still passes. Advice:
  "updates are delivered by the Mac App Store." **Ordering is load-bearing:** the
  frozen-branch cask check matches `/Applications/` + a Caskroom receipt, and a
  MAS app also lives in `/Applications`, so the `_MASReceipt` probe must run
  **before** the cask check or a MAS install would misreport as `HOMEBREW_CASK`.
- **Stable releases only:** App Store versions cannot carry prerelease
  suffixes; the MAS job is gated on `is_prerelease == false` (ADR-007), reusing
  the exact guard ADR-009 shipped for the MSIX pack step in `release.yml`.
- **The listen-only constraint becomes a documented invariant:** any future
  feature that sets `suppress=True` or posts synthetic events would flip
  pynput to an active tap, require Accessibility, and forfeit MAS eligibility.
  Recording it here makes that a *decision to revisit this ADR*, not an
  accident.

## Rationale

- **Parallel, not sequential.** ADR-013 stands alone and ships first regardless;
  the MAS experiment reuses its Program membership and signing plumbing at the
  marginal cost of a second entitlements file and a `.pkg` step. If MAS fails,
  nothing is stranded.
- **MAS despite having a cask.** Same argument as ADR-009: the cask serves the
  Homebrew audience; MAS is the only channel with mainstream discovery, zero
  Gatekeeper/terminal involvement, and automatic updates. It is also the only
  macOS channel where the *platform* vouches for an input-capture app — which
  matters more for keycast than for most apps.
- **`.pkg`/`productbuild` because that is the only MAS delivery format** for a
  non-Xcode app; there is no decision space here, only a recipe.
- **Bail-out framed up front** because the risk is concentrated and known
  (PyInstaller × sandbox × Tk), unlike ADR-009 where `runFullTrust` removes the
  sandbox variable entirely. An honest experiment with an exit beats an
  open-ended commitment.

## Consequences

- **Bail-out condition:** if the sandboxed bundle cannot pass upload validation
  or App Review after a bounded effort (child-process entitlement inheritance,
  Tk-under-sandbox, or TCC-prompt failures being the expected failure modes),
  this ADR is marked **Rejected** with the findings appended, and ADR-013's
  notarized channel remains the sole macOS distribution. The findings stay
  valuable — that is the point of recording the experiment.
- **Release pipeline:** `build-macos` gains (or a sibling job adds) the MAS
  variant: Distribution-sign → sandbox entitlements → `productbuild` →
  validation. Upload stays manual until proven; automation would mirror the
  best-effort post-release jobs.
- **Update advice (ADR-002 extended):** `MAC_APP_STORE` joins the enum with
  the receipt probe; `tests/test_updates_sources.py` covers probe and ordering
  (before `HOMEBREW_CASK` — a MAS install is not in the Caskroom, but the
  receipt is the more specific signal and costs one `Path.exists`).
- **Docs (DDD):** `README.md` gains the MAS badge/link; `docs/PACKAGING.md` a
  "Mac App Store" section (entitlements diff vs ADR-013, `.pkg` recipe, review
  notes); the settings/logging docs gain the container-path note for MAS
  installs described in Context.
- **App Review is a recurring gate:** every release waits on review (typically
  ~24–48 h) and can be rejected — MAS releases may therefore **lag** the
  GitHub/cask/PyPI release for the same tag. Accepted: the release itself stays
  atomic (ADR-001); MAS is eventually-consistent by nature, like the
  cask/Scoop bump PRs.
- **First-run UX differs:** the sandboxed app prompts for Input Monitoring via
  the system dialog (`CGRequestListenEventAccess`) rather than the
  manual-System-Settings flow; the README's permission section needs a
  per-channel note.
- **Validation limit:** sandbox behaviour, the TCC prompt, and App Review can
  only be exercised with the real account on real hardware. Before the first
  MAS release, a manual end-to-end check: install from TestFlight-for-Mac or a
  development-signed sandbox build → prompt appears → grant → keystrokes render
  → config/logs land in the container.
