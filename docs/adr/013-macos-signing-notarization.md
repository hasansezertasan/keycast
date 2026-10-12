# ADR-013: Sign and notarize macOS builds with Developer ID

## Status

Proposed — 2026-07-05. Recorded **ahead of implementation** (DDD: this ADR is
the design contract) and **gated on one decision**: enrolling in the paid Apple
Developer Program (see Context). Accepting that cost is what promotes this ADR
to *Accepted*; until then it is a design on the shelf. **Supersedes the
"unsigned" stance of
[ADR-001](001-desktop-app-packaging.md)** — its named supersede trigger
("acquiring an Apple Developer account … should be recorded as a follow-up ADR")
— and **reopens #4** (signing + notarization) and **#5** (hardened-runtime
entitlements), both previously closed as cost-gated. Prerequisite for
[ADR-014](014-mac-app-store.md) (Mac App Store), which reuses the Program
membership and signing infrastructure established here.

## Context

ADR-001 ships the macOS `.app` ad-hoc signed only. Two costs of that stance have
grown since it was accepted:

- **Gatekeeper friction got worse.** ADR-001's documented workaround was
  right-click → Open. **macOS 15 (Sequoia) removed that bypass**: users must now
  attempt to open the app, then approve it in System Settings → Privacy &
  Security — a flow most non-developers abandon. The cask's caveat text
  describes a path that no longer works as written on current macOS.
- **Permission grants don't survive updates.** TCC keys the Input Monitoring
  grant to the app's code signature. An ad-hoc signature is unique per build, so
  **every release invalidates the grant** and users re-approve keycast in System
  Settings after each upgrade — the exact instability ADR-001 built the `.app`
  bundle to avoid ("a stable bundle identity to hold … permissions against").
  A Developer ID signature is stable across releases; the grant sticks.

The blocker named in ADR-001 was cost, not engineering: the Apple Developer
Program ($99/yr). That fee is the **sole remaining gate** — everything else in
this ADR is engineering that can be built now. Accepting the fee (enrolling)
promotes this ADR from Proposed to Accepted; declining it leaves the design on
the shelf and the ad-hoc stance in force. Note the asymmetry with the Windows
side: ADR-009's Microsoft Store channel, since shipped, needed **no** fee
(Partner Center is free and the Store signs the package), so Apple is the one
paid channel in keycast's distribution.

## Decision

- **Join the Apple Developer Program** (individual). Certificates: **Developer
  ID Application** for this ADR; the Program also unlocks the Apple Distribution
  certificate ADR-014 needs.
- **Sign inside-out with hardened runtime.** All nested Mach-O binaries in the
  PyInstaller bundle, then the `.app`, are signed with the Developer ID identity
  and `--options runtime`. PyInstaller 6 performs nested signing itself when
  `codesign_identity` is set in `keycast.spec` — the committed spec gains that
  (CI injects the identity; local unsigned builds keep working when it is
  unset).
- **Commit the entitlements file** (`packaging/entitlements.plist`, reopening
  #5). PyInstaller apps under hardened runtime need
  `com.apple.security.cs.allow-unsigned-executable-memory` (ctypes/libffi) and
  `com.apple.security.cs.disable-library-validation` (Python loading its own
  dylibs). Each entitlement carries a comment naming why it exists; nothing else
  is granted.
- **Notarize and staple in `build-macos`.** After the `.dmg` is built:
  `xcrun notarytool submit --wait` with an App Store Connect **API key** (not an
  Apple ID password), then `xcrun stapler staple`. Secrets:
  `MACOS_CERTIFICATE` (base64 `.p12`) + password, and the API key
  triple (key id / issuer / key file), imported into a throwaway CI keychain.
- **Signing is inside the atomic gate.** Unlike `bump-cask`/`bump-scoop`, this
  is not best-effort: a release with a broken signature is worse than no
  release, so a signing or notarization failure fails `build-macos` and blocks
  `publish-pypi` (ADR-001's atomicity, unchanged).

## Rationale

- **Developer ID + notarization, not just signing.** Since macOS 10.15 an
  unnotarized Developer-ID app still hits Gatekeeper; notarization is what
  removes the wall. The two are one decision, not two.
- **API key over Apple-ID password for notarytool.** App-specific passwords
  break on account 2FA changes; the API key is scoped, revocable, and the
  documented CI path.
- **Spec-driven signing over a post-build `codesign --deep`.** `--deep` is
  deprecated and signs in the wrong order (outside-in); PyInstaller's own
  nested signing is inside-out and keeps the recipe in the committed spec —
  one source of truth, consistent with ADR-001.
- **Why now:** three independent motivations converged — Sequoia broke the
  documented workaround, per-update permission loss contradicts the bundle's
  purpose, and ADR-014 needs the Program membership anyway. The $99/yr buys all
  three. (The design and CI wiring can land *before* enrolling — identity unset
  means builds stay unsigned, exactly as today — so the fee gates the *cutover*,
  not the work.)

## Consequences

- **The cask's Gatekeeper caveat is deleted** (tap-side change, coordinated with
  the first signed release). `README.md`'s "More info → Open anyway" note goes
  with it. The Windows SmartScreen note **stays** — Authenticode remains not
  planned (#6; the Store route of ADR-009 sidesteps it).
- **Input Monitoring grants persist across updates** once users are on a signed
  build (one final re-grant when upgrading from an ad-hoc build to the first
  signed one — worth a release-notes callout).
- **Release path gains an external dependency:** Apple's notary service.
  Submissions usually clear in minutes but have no SLA; a service outage blocks
  the release (accepted — atomicity is worth more than release-latency
  guarantees for this project).
- **Recurring cost:** $99/yr Program membership; certificate renewal is part of
  the yearly cycle. Lapse ⇒ releases fail loudly at the signing step, not
  silently ship unsigned.
- **Secrets hygiene:** four new repo secrets; the CI keychain is created and
  deleted per run. Forks and PRs never see them — the PR-level `build-macos`
  check keeps building unsigned (identity unset), so contributors are
  unaffected.
- **Docs (DDD):** `docs/PACKAGING.md` gains a "Signing & notarization" section
  (entitlements rationale, secret setup, local-unsigned vs CI-signed matrix) in
  the implementing change. `tests/test_docs_contract.py` pins none of this and
  needs no change.
- **Validation limit:** notarization cannot be rehearsed without the real
  account and certificate. First signed release requires a manual end-to-end
  check on a clean Mac: install from the cask → no Gatekeeper wall → grant
  Input Monitoring → upgrade → grant survives.
