# ADR-009: Distribute keycast on Windows via the Microsoft Store (MSIX, `runFullTrust`)

## Status

Proposed — 2026-07-04. Recorded **ahead of implementation** (DDD: this ADR is the
design contract; the packaging recipe, pipeline job, and install-source wiring
land in follow-up changes). Builds on [ADR-001](001-desktop-app-packaging.md)
(the PyInstaller `dist/keycast/` folder), [ADR-002](002-update-check.md) /
[ADR-005](005-updates-package-structure.md) (install-source-aware update advice),
and [ADR-007](007-prerelease-release-channels.md) (stable-only gating). Sits
alongside [ADR-006](006-windows-installer.md) (Inno Setup installer) and
[ADR-008](008-scoop-bucket.md) (Scoop bucket) as the **fourth** Windows channel.
Supersedes nothing; does **not** reopen #6 (Authenticode) — see Rationale.

## Context

Windows has three channels — the portable zip (ADR-001), the Inno installer
(ADR-006), and Scoop (ADR-008). All three ship **unsigned** binaries — the zip
and installer trip SmartScreen ("More info → Run anyway") on first run; Scoop
sidesteps the prompt but not the missing signature — and none has mainstream
discovery: the zip and installer require finding the GitHub Releases page;
Scoop is a developer tool. The Microsoft Store is the only channel preinstalled
on effectively every consumer Windows 10/11 machine, and — decisive for an
unsigned-binary project —
**Store-delivered apps bypass SmartScreen entirely**, because trust is
established by Store signing and review rather than Authenticode reputation.

Store registration is now **free** for individuals and companies (Microsoft has
dropped both former registration fees). Two submission routes exist:

- **Win32 (EXE/MSI) listing.** The Store links to a self-hosted installer. But
  the installer **must be Authenticode-signed** with a certificate chaining to
  the Microsoft Trusted Root Program — exactly the cost/complexity blocker that
  closed #6. Worse, the cheap route (Azure Artifact Signing, formerly Trusted
  Signing) is **geo-restricted**
  to US/CA individuals and US/CA/EU/UK organizations, which excludes this
  project's maintainer. The remaining options (SignPath Foundation's free OSS
  program, a Certum open-source certificate ~€70/yr) add an external dependency
  or a recurring cost.
- **MSIX package.** The Store **signs the package itself** (no publisher
  certificate needed), hosts the artifact, and delivers updates automatically.
  The cost moves from certificates to packaging: an `AppxManifest.xml`, a
  `makeappx` step, and Partner Center identity plumbing.

One structural fact constrains the design: keycast installs **global low-level
input hooks** (pynput's `WH_KEYBOARD_LL` / `WH_MOUSE_LL` via Win32). A plain
MSIX runs in an AppContainer, which blocks global hooks. The **`runFullTrust`**
restricted capability lifts the container for desktop-bridge apps: the packaged
process runs with normal desktop privileges, and the existing PyInstaller build
works unchanged.

## Decision

- **Route: MSIX with `runFullTrust`,** not a Win32 listing. The Store signs and
  hosts the package, so no Authenticode certificate is acquired and #6 stays
  closed. The capability is declared in the manifest and justified in the
  submission notes (visible overlay, open-source repo, no storage or
  transmission of input — a visualizer, not a keylogger).
- **Package the existing bundle.** A committed `packaging/AppxManifest.xml`
  template wraps the untouched `dist/keycast/` folder; `makeappx pack` (ships
  in the Windows SDK on `windows-latest` runners, though not on `PATH` — the
  pack step resolves it under `Windows Kits`) produces `keycast.msix` in
  `build-windows` as a **workflow artifact only** — the Partner Center
  submission input, deliberately **not** a GitHub Release asset. An MSIX must
  be signed before Windows will install it, and this package is unsigned until
  the Store signs it, so attaching it to the Release would publish an artifact
  users cannot install (the zip and installer already cover direct download).
  No change to `keycast.spec`.
- **Version mapping: tag → four-part numeric.** MSIX versions are
  `Major.Minor.Build.Revision`, all numeric — no prerelease suffixes. A stable
  tag `vX.Y.Z` maps to `X.Y.Z.0`, injected at pack time (mirrors the ADR-006
  `iscc /D` pattern; the template defaults to `0.0.0.0` so PR checks compile
  without a tag). The tag exists at pack time for the same reason hatch-vcs can
  stamp the right version inside the draft-release window: release-please's
  `force-tag-creation: true` creates it immediately. Prerelease tags **cannot**
  be expressed, which coincides with ADR-007's stable-only gating: the Store
  job is skipped when `is_prerelease` (a guard that is currently inert —
  mainline cuts only stable tags — but binding if the beta channel is
  re-enabled).
- **Submission: manual first, automated later.** The first submission (identity
  reservation, listing copy, capability justification, age rating) is manual in
  Partner Center. Subsequent version bumps are a **best-effort job outside the
  atomic release gate** (mirrors `bump-cask` / `bump-scoop`) using `msstore-cli`
  / the Store submission API — added only after the manual flow has succeeded
  once.
- **New install source: `MICROSOFT_STORE`.** Store-installed MSIX apps run from
  under `C:\Program Files\WindowsApps\<PackageFamilyName>…`;
  `detect_install_source()` matches the POSIX-lowered `/windowsapps/` path
  fragment — a location-only path predicate like the Scoop probes (ADR-008), checked
  before the `GITHUB_RELEASE` fallback. Update advice: "updates are delivered
  automatically by the Microsoft Store" (no upgrade command).

## Rationale

- **MSIX over Win32 listing.** The Win32 route re-opens the certificate problem
  that ADR-006 explicitly closed, adds a geo-restricted or third-party-dependent
  signing story, and still leaves the maintainer hosting versioned installer
  URLs. MSIX trades all of that for packaging work that CI does once —
  and gains Store-managed updates, which none of the other three Windows
  channels provide.
- **`runFullTrust` over AppContainer.** Not a preference — a requirement. Global
  input hooks are the product; AppContainer forbids them. The capability is
  routinely granted to desktop-bridge apps and its optics are addressed head-on
  in the submission notes rather than engineered around.
- **Store alongside Scoop, not replacing it.** ADR-008 chose Scoop over
  Chocolatey/WinGet ceremony for the package-manager audience; that reasoning
  stands, and the Store question it left untouched is decided here. The Store
  serves a different audience (mainstream users who will never run a terminal)
  and removes SmartScreen — a problem Scoop users don't have and zip/installer
  users do.
- **Manual-first submission.** The Store has a human review queue (24–72 h) and
  one-time identity/listing setup that automation cannot do. Automating before
  the manual path has succeeded once would be building on unverified ground —
  the same reason ADR-001 validated the bundle empirically before pipelining it.

## Consequences

- **Release pipeline:** `build-windows` gains a `makeappx pack` step producing
  the `keycast.msix` **workflow artifact** (retained for the submission job /
  manual upload; never attached to the GitHub Release — see Decision); a new
  best-effort `submit-store` job (post-`publish-release`, gated on
  `is_prerelease == false` and on a Partner Center API secret being present —
  warns and exits 0 otherwise, like `bump-scoop`).
- **CI:** the PR-level `build-windows` check also runs `makeappx pack` against
  the `0.0.0.0` default and asserts the `.msix` emerged — catching a broken
  manifest on the PR, not at release (mirrors the ADR-006 `iscc` check).
- **Partner Center is a second source of truth:** listing copy, screenshots,
  age rating, and the capability justification live there, not in the repo. The
  reserved identity (`Name` / `Publisher` in the manifest) must match Partner
  Center exactly or `makeappx`-built packages are rejected at upload.
- **Update advice (ADR-002 extended):** `keycast info` recognises
  `MICROSOFT_STORE`; `tests/test_updates_sources.py` covers the path probe and
  ordering. The in-app update *check* stays (it is informational), but the
  advice never points Store users at GitHub Releases.
- **Review risk is real and accepted:** an input-capture app may be rejected or
  asked for clarification. Mitigation is transparency (OSS repo link, visible
  overlay screenshots, explicit "no storage/transmission" statement). A
  rejection costs nothing but time — the other three channels are unaffected.
- **Docs (DDD):** `README.md` gains a Store install section and
  `docs/PACKAGING.md` a "Microsoft Store" section (manifest, version mapping,
  submission flow) in the implementing change.
- **Validation limit:** as with ADR-001/006/008, nothing Store-related runs on
  the macOS dev machine. `makeappx` is exercised by CI; an end-to-end
  install-from-Store → launch → hooks-work check on a real Windows box remains a
  **manual** gate before the first Store release.
