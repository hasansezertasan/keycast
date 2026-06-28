# ADR-007: Prerelease & release-channel strategy (rolling beta; nightly/canary/insiders deferred)

## Status

Accepted — 2026-06-28. Implemented: `prerelease: true` + `versioning:
"prerelease"` + `prerelease-type: "beta"` in `.github/release-please-config.json`,
and the `is_prerelease` output + channel guards in `.github/workflows/release.yml`
(prerelease GitHub releases marked `--prerelease --latest=false`; `bump-cask` /
`bump-scoop` gated to stable). Builds on [ADR-001](001-desktop-app-packaging.md)
(the multi-channel packaging this routes between) and the release pipeline
documented in `CLAUDE.md` → *Release pipeline* and `docs/PACKAGING.md`. The
operational "how to cut / graduate a beta" lives in `CLAUDE.md`; this ADR records
the *why* and the landscape of alternatives. Supersedes nothing.

## Context

0.2.0 accumulated a large, distribution-heavy changeset (PyInstaller bundles, a
styled `.dmg`, an Inno Setup Windows installer, a Scoop bucket, the
install-source-aware update check). Shipping all of that straight to stable means
the new **packaging / distribution surface** is first exercised *by end users* on
Homebrew and Scoop. We wanted a way to publish a release that testers can opt into
**without** it reaching the auto-updating binary channels (`brew`, `scoop`).

The releases are automated by release-please + hatch-vcs (the git tag *is* the
version; see `CLAUDE.md`), publishing to PyPI via Trusted Publishing and producing
a GitHub release with `.dmg`/`.zip`/installer assets, then nudging a Homebrew tap
and a Scoop bucket. Any prerelease scheme had to fit that existing pipeline.

**The conceptual model — three orthogonal axes.** "Prerelease", "nightly",
"canary", and "insiders" are routinely conflated because they all describe "a
build ahead of stable", but each is defined by a *different* axis:

- **Maturity** — *how done is the code?* The ordered ladder
  `alpha < beta < rc < final` (with `dev`/snapshot builds sitting *below* alpha).
  PEP 440 recognizes exactly three pre-release segments: `a`, `b`, `rc`.
- **Cadence / trigger** — *when and how often is a build cut?* On-demand
  milestone (what release-please does) vs scheduled (`nightly`) vs continuous
  (`rolling` / `edge`).
- **Audience / access** — *who is allowed to get it?* Public vs a small
  risk-detection slice (`canary`) vs an enrolled-or-paying group (`insiders`) vs
  internal-only (`dogfood`).

release-please (and therefore `prerelease-type`) only ever speaks the **maturity**
axis. Cadence and audience are separate mechanisms. This is the crux of the
decision below: the maturity axis is cheap (a config flag on the tool we already
run), the other two axes are not (separate workflows, distribution, access
control).

## Decision

- **Run mainline as a rolling `beta` prerelease channel.** Set `prerelease: true`,
  `versioning: "prerelease"`, `prerelease-type: "beta"` in
  `release-please-config.json`. A normal merge now bumps `0.2.0-beta.1 →
  0.2.0-beta.2` rather than to a stable version.
- **Tag in SemVer, ship as PEP 440.** release-please tags `v0.2.0-beta.1`;
  hatch-vcs (`version_scheme = "only-version"`, `local_scheme =
  "no-local-version"`) normalizes that to `0.2.0b1`. Verified end-to-end (the
  `packaging` library accepts the SemVer pre-release forms and normalizes
  `v0.2.0-beta.1 → 0.2.0b1`, `v0.2.0-rc.1 → 0.2.0rc1`, `v0.2.0 → 0.2.0`), so PyPI
  accepts the upload and `pip install keycast` ignores it unless `--pre` is passed.
- **Guard the binary channels.** A new `is_prerelease` workflow output (`true`
  when the tag contains a `-`; a final/graduated tag never does) drives:
  `publish-release` marks betas `--prerelease --latest=false` (stable forces
  `--prerelease=false --latest`), and `bump-cask` / `bump-scoop` are **skipped**
  for prereleases.
- **Graduate via `Release-As`.** A `Release-As: X.Y.Z` commit footer (no suffix)
  overrides the computed version and opens a stable release PR; the hyphen-free
  tag clears the guard and flows through every channel.

**The maturity ladder — pick by "merge this if…":**

| Type | PEP 440 | Meaning | Merge this if… |
|------|---------|---------|----------------|
| **alpha** | `a` (`0.2.0a1`) | Feature-*incomplete*, expect breakage; early/internal testers | …you're still adding or changing features for this release |
| **beta** | `b` (`0.2.0b1`) | Feature-*complete*, hunting bugs; API may still shift slightly | …the features are in and you want real users to shake it out |
| **rc** | `rc` (`0.2.0rc1`) | Believed shippable; ships unless a blocker appears | …this exact build *becomes* the final unless something's wrong |

Sort order is `0.2.0a1 < 0.2.0b1 < 0.2.0rc1 < 0.2.0`, and `pip`/`uv` respect it;
all three are hidden from a plain `pip install` (only surface with `--pre`).

## Rationale

**Why `beta` as the channel default (over alpha / rc):**

- We are pre-1.0 (0.x) and features for a given release are **done and merged**
  before the prerelease is cut, so `alpha` is semantically too early — we're not
  feature-incomplete.
- The risk the prerelease actually manages is the **packaging / distribution
  surface** being exercised in the wild — not API churn. That is textbook *beta*:
  "feature-complete, help me find bugs."
- `rc` carries a stronger contract — each rc means "this *is* the final, pending
  sign-off," and the artifact should be bit-for-bit promotable. That ceremony fits
  a 1.0 launch with a formal gate, not a rolling 0.x desktop app.

**The type is not fixed forever — escalate within a cycle via `Release-As`.** The
channel *default* is `beta`, but a `Release-As:` footer overrides per-release:

1. Roll betas as features land: `0.2.0-beta.1`, `0.2.0-beta.2`, … (just merge).
2. When you believe it's done, cut a final-candidate: land a commit with
   `Release-As: 0.2.0-rc.1` → tag `v0.2.0-rc.1` → hatch-vcs `0.2.0rc1`.
3. Graduate to stable: land `Release-As: 0.2.0` (no suffix).

## Alternatives considered (and deferred): nightly, canary, insiders, edge

These were evaluated as alternative or complementary channels and **deliberately
deferred**. They look alike but each is defined by a different axis:

- **nightly** *(cadence axis)* — an **automated, scheduled** build (cron) from the
  tip of `main`, cut *whether or not anything is "ready."* Milestone-blind,
  available to anyone, no access gate. The defining trait is the **schedule**. In
  PEP 440 these use the **`.devN` developmental segment** (e.g.
  `0.3.0.dev20260628`), which sorts *below* alpha: `.dev < a < b < rc < final`.
  Audience intent: "I want the absolute latest and accept breakage."
- **canary** *(audience axis — risk)* — a bleeding-edge build pushed to a **small
  slice as a tripwire** (Chrome's term — the canary in the coal mine) to catch
  regressions before the wider channel. The defining trait is **early warning via
  progressive exposure**; the slice is often chosen automatically (e.g. a small %
  of installs). Frequently continuous like nightly, but the *point* is risk
  detection, not freshness.
- **insiders** *(audience axis — access)* — early access gated by **membership,
  enrollment, or sponsorship**, usually a *standing parallel channel* rather than
  a one-off. Two common flavors:
  - **Enrollment / program** — a separately-installable build opted-in users run
    alongside stable (VS Code *Insiders*, Windows *Insider* rings).
  - **Sponsorware** — features ship first (or exclusively) to financial sponsors,
    graduating to the public edition as funding goals are met. The canonical
    Python-OSS example is **Material for MkDocs Insiders**. This is a *funding /
    access* model, **not** a maturity stage.
  The defining trait is **who is permitted**, not how done or how fresh — an
  insiders build can itself be stable, beta, *or* nightly underneath.

One-liner: **nightly = "newest" (time), canary = "safest rollout" (risk),
insiders = "privileged access" (membership/money).** They overlap only in the
incidental sense that all three sit ahead of the public stable channel.

**What release-please does and does not own.** Only the maturity axis is a
release-please setting; the others are not, for *different* reasons:

| Concept | A release-please setting? | What owns it instead |
|---|---|---|
| **alpha / beta / rc / final** | **Yes** | The maturity axis — `prerelease`, `prerelease-type`, `versioning`, `Release-As`. |
| **nightly** | No | A **trigger + version-scheme** concern. release-please is *commit-driven* (acts only when commits land, via a release PR); nightly is *clock-driven* and PR-less → needs `on: schedule:` + a `.devN`/date version. |
| **canary** | No | A **rollout / audience** concern. release-please bumps versions and makes GitHub releases — it has no notion of "ship to 5% of users." |
| **insiders** | No | A **distribution + access-control** concern (private index / sponsorware). |

The version *string* is the easy part for all of them (`.devN`, `rcN`, etc.); what
makes nightly/canary/insiders *not* release-please is the part release-please does
not do at all — **scheduling** (nightly), **audience targeting** (canary), and
**access control** (insiders). release-please is a *versioning + release-PR* tool,
not a *scheduler* or a *distributor*.

**How they would map to keycast's stack (none implemented today):**

- `nightly` / `canary` / `edge` would be a **separate `on: schedule:` workflow**
  building from `main` HEAD and publishing a `.dev`/date version, with **no
  human-gated release PR**.
- `insiders` is **not a release-please setting at all** — it's a distribution +
  access-control problem: a private package index, a sponsor-gated wheel, or a
  separate project name (e.g. a hypothetical `keycast-insiders` on a private
  index). Public PyPI cannot gate by audience, so it could not live there.

**Why deferred:** keycast needs **none** of nightly / canary / insiders / edge
yet — the rolling **beta** channel already covers "let people test before stable
reaches brew/scoop," which is the 90% case. Revisit only post-1.0, and even then
reach for a `nightly`/`edge` workflow first (cheap), before `canary` (needs a
rollout/% mechanism) or `insiders` (needs sponsorship + access control to be worth
the machinery).

### Delivering prereleases through Homebrew / Scoop (deferred)

Unlike `pip`/`uv`/`npm`/`cargo` — which carry prereleases on the *same* package
behind a flag (`pip install --pre keycast`) — **Homebrew and Scoop have no `--pre`
notion**: a package manager models a channel as a **separate, explicitly-named
package** the user opts into. The conventions:

- **Homebrew** — the same cask token with an `@<channel>` suffix, e.g.
  `keycast@beta` (cf. `google-chrome@beta`, `visual-studio-code@insiders`). Per the
  [Cask Cookbook](https://docs.brew.sh/Cask-Cookbook). (The old
  `homebrew/cask-versions` tap was deprecated and merged into `homebrew/cask` in
  2024, so variant casks now live beside the stable one.)
- **Scoop** — a separate manifest with a suffix, e.g. `keycast-beta` (cf.
  `vscode-insiders`, `firefox-nightly`), optionally in a `versions` bucket.

This yields **two conventional postures**, and keycast is deliberately at (1):

1. **Don't ship prereleases via package managers at all** — keep them on PyPI
   (`--pre`) + the GitHub pre-release; brew/scoop users only ever see stable. This
   is the common default (e.g. GoReleaser skips the Scoop bump on a prerelease
   tag), and it is exactly what the `is_prerelease` guards above implement.
2. **Ship an explicit opt-in channel package** — a `keycast@beta` cask + a
   `keycast-beta` manifest, each with its *own* checkver/bump automation gated to
   *prerelease* tags (the mirror image of the current stable-only guard). Strictly
   more machinery: a second package per channel, per platform.

Note on granularity: package-manager channels are named by coarse
**cadence/audience** (`beta`, `nightly`, `insiders`), **not** by PEP 440 maturity
— **`rc` rarely gets its own brew/scoop channel** (it folds into `beta` or stays
PyPI-only). So even posture (2) would realistically add just one package:
`keycast@beta`. Move to posture (2) only if users actually want to *track* betas
through their package manager.

**Other terms in the landscape (recorded for vocabulary, not because keycast needs
them):**

- **stable / GA (General Availability)** — the final, recommended release; the
  baseline every channel above is "ahead of." keycast's graduated `X.Y.Z`.
- **dev channel** — in Chrome's four-channel model (**Stable → Beta → Dev →
  Canary**), "Dev" sits between beta and canary: fresher than beta, more baked
  than canary.
- **edge** — common synonym for the continuously-bleeding-edge channel (Docker's
  `edge`); effectively nightly-from-`main` without the "every night" promise.
- **snapshot** — a point-in-time build of in-progress code (Java/Maven
  `-SNAPSHOT`); conceptually a nightly whose version is understood to be mutable.
- **rolling release** — continuous updates with no discrete versioned releases
  (Arch Linux); the opposite of keycast's point-release model.
- **LTS (Long-Term Support)** — a release *line* maintained with fixes for an
  extended window; an orthogonal *maintenance-duration* axis. Irrelevant pre-1.0.
- **preview / technical preview / early access (EA)** — vendor umbrella terms,
  usually equivalent to beta or insiders depending on who is saying it.
- **dogfood / internal** — builds restricted to the team before any external
  exposure; the narrowest audience slice.
- **feature flags / dark launch** — the *alternative to channels*: ship one build
  to everyone but gate new behavior at runtime per-user. This is how you get
  canary-style progressive exposure *without* a separate distribution channel —
  worth knowing because it is often cheaper than standing one up.

## Consequences

- **Which channels receive a beta.** Two of four:

  | Channel | Beta? | Detail |
  |---|---|---|
  | **PyPI** | Yes | Uploaded as `0.2.0bN`, but hidden from `pip install keycast` — only `--pre` / `uv pip install --prerelease=allow` sees it. |
  | **GitHub Releases page** | Yes | Full asset set (`.dmg`, `.zip`, installer, sdist, wheel), flagged **Pre-release**, **not "Latest"**. |
  | **Homebrew cask** | No | `bump-cask` gated off for prereleases. |
  | **Scoop bucket** | No | `bump-scoop` gated off (both the binary-zip and pipx-shim manifests). |

- **Two layers of protection for brew/scoop.** (1) *Push side:* the
  `bump-cask`/`bump-scoop` jobs don't fire for a prerelease, so we never nudge the
  downstream repos. (2) *Pull side:* the tap and bucket also run their own cron
  that re-derives from GitHub's *latest* release / PyPI's *latest* version — and
  because betas are marked `--prerelease --latest=false`, both "latest" endpoints
  exclude them by definition. The `--latest=false` flag is therefore not cosmetic:
  it is what stops the channels we don't own from ever surfacing a beta.
- **First-beta numbering quirk.** release-please's first beta in a cycle is
  unnumbered (`0.2.0-beta`), which normalizes to PEP 440 `0.2.0b0` — valid and
  correctly ordered (`b0 < b1`), just slightly unusual to see on PyPI. To force a
  clean `b1`, land `Release-As: 0.2.0-beta.1` before merging the release PR.
- **Workflow change.** Every release now flows through prerelease mode by default;
  stable requires a deliberate `Release-As`. This makes shipping stable an explicit
  act, which is the intended safety property for a distribution-heavy app.
- **Fragmented changelog — consolidate at graduation.** release-please generates
  each `CHANGELOG.md` entry from the diff since the *previous* (pre)release, and
  leaves the prerelease sections in place. So the final `## X.Y.Z` section contains
  only commits landed *after the last prerelease* — and because most features ship
  in the first `X.Y.Z-beta`, the stable entry (and its GitHub Release notes) is
  often nearly empty. There is no auto-aggregate option; the supported workflow is
  to **hand-edit `CHANGELOG.md` in the `Release-As` PR** (fold the `-beta*`/`-rc*`
  subsections into one stable section) and **edit the stable GitHub Release notes**
  to match. Graduating directly from the first beta (skipping extra beta/rc steps
  when everything is already baked) minimizes how much there is to fold in.
- **Nightly blocker (if ever added).** `pyproject.toml` pins `version_scheme =
  "only-version"`, which reports the *exact last tag* between tags (no dev
  distance), so every nightly would collide on the previous version. A nightly
  workflow must override that scheme (or compute a unique date/`.devN` version) to
  get ordered, non-colliding builds.
- **The Homebrew *formula*** (CLI via PyPI) is not part of the automated bump at
  all — beta or stable — so it is unaffected by this decision either way.
