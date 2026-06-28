# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

keycast is a cross-platform keystroke and mouse-click visualizer: a transparent
Tk overlay that shows input events in real time. Python 3.14+, built on pynput
(input capture), tkinter (overlay), and Pydantic (settings).

## Commands

| Task | Command |
|------|---------|
| Install deps (incl. dev group) | `uv sync` |
| Run the app | `uv run keycast` |
| CLI subcommands | `uv run keycast version` · `uv run keycast info` |
| Run all tests | `uv run python -m pytest` |
| Run one module | `uv run python -m pytest tests/test_settings.py` |
| Run one test | `uv run python -m pytest -k test_rotation_defaults` |
| Coverage (config in `pyproject.toml`) | `uv run pytest --cov` |
| Lint | `uv run ruff check .` |
| Full check suite (CI parity) | `uv run --locked tox run` |
| Linters/formatters only | `uv run --locked tox run -e style` |
| Run git hooks across all files | `uv run --locked prek run --all-files` |

## Architecture

Read these together — the design is spread across small modules that only make
sense as a pipeline.

- **Single-sink event flow.** `KeyListener` and `MouseListener`
  (`listeners.py`) capture input on pynput threads, format each event into one
  display string, and push it to a `TextSink` — a `Callable[[str], None]`
  protocol. They know nothing about the display. `DisplayWindow.show_text`
  (`display.py`) is the production sink; tests pass `list.append`. Mouse
  position, when enabled, is formatted *into* the string, so the sink signature
  stays uniform.
- **Composition root.** `Keycast` (`application.py`) is the only place that
  wires components: it loads settings, configures logging, constructs the window
  and listeners, and connects each listener's `show_text` to the window.
  `main.py`, `cli.py`, and `__main__.py` are thin entry points that call
  `Keycast().run()`.
- **Threading & shutdown (subtle).** Listeners run on pynput threads; the fade
  timer is a self-rescheduling `root.after(100, ...)` on the Tk main loop (no
  separate thread). `show_text` marshals widget updates onto that loop via
  `root.after`. Shutdown is two-phase: `request_stop()` (safe from any thread /
  the signal handler) schedules `root.quit`; `stop()` runs on the main thread
  after `mainloop` returns and destroys the window. Destroying a window while
  still nested in `mainloop` raises Tcl errors — hence the split.
- **Settings load from JSON only.** `Settings` (`settings.py`, pydantic-settings,
  `frozen`) overrides `settings_customise_sources` to use *only* the JSON file —
  constructor kwargs and env vars are intentionally ignored for the top-level
  `Settings`. Don't `Settings(display=...)`; in tests, patch the JSON source.
  `Settings.create_settings_file()` is the load entry point: first run writes
  defaults atomically (tempfile + `os.replace`); a corrupt file is moved aside to
  `config.json.<epoch>.bak` and defaults are used; failures degrade to in-memory
  defaults rather than crashing. Config lives at `~/.keycast/config.json`, logs
  default to `~/.keycast/main.log` (rotating). Settings load *before* logging is
  configured, so recovery warns via stderr, not the logger.
- **Cross-platform key labels.** pynput names modifiers inconsistently across
  OSes. `_default_key_mappings` + `_super_key_labels` (`settings.py`) normalize
  labels per platform (e.g. Super key → "Command"/"Windows"/"Super"); unmapped
  keys fall back to `name.capitalize()`. Users override via
  `KeyboardSettings.key_mappings`.

## Conventions

- **Docs are a contract (DDD).** `README.md` and `docs/` (API, ARCHITECTURE,
  DESIGN_DECISIONS, PROJECT_OVERVIEW) must match the code. When changing the
  public API, defaults, or key labels, update the docs in the same change.
- **`tests/test_docs_contract.py` enforces the above** — it pins class/constructor
  names, the `Settings` section set, default key labels, and logging defaults. A
  failure means a doc claim and the code diverged; fix the mismatch, not the test.
- Commits follow Conventional Commits; do not add an AI `Co-Authored-By` trailer.

## Release pipeline

Releases are automated by **release-please** (`.github/workflows/release.yml`),
driven entirely by Conventional Commit messages on `main`:

- The **version is dynamic**, derived from git tags by **hatch-vcs**
  (`[tool.hatch.version] source = "vcs"`; `pyproject.toml` declares
  `dynamic = ["version"]`, no static literal). release-please bumps only
  `CHANGELOG.md`, opens a release PR, and on merge tags + drafts a GitHub release —
  the tag *is* the version. `bump-minor-pre-major: true` keeps pre-1.0 breaking
  changes at a minor bump (0.x → 0.(x+1)) instead of jumping to 1.0.0.
- The release is created as a **draft** (`draft: true`), and the `publish` job
  builds and publishes to PyPI *before* un-drafting it. GitHub normally withholds
  a draft release's git tag until it is published, which would make hatch-vcs build
  the wrong version; **`force-tag-creation: true`** makes release-please create the
  tag immediately, so the tag exists at build time.
- **Mainline is a rolling beta channel.** `prerelease: true` + `versioning:
  "prerelease"` + `prerelease-type: "beta"` make release-please cut prereleases by
  default: a normal merge bumps `0.2.0-beta.1 → 0.2.0-beta.2` rather than to a
  stable version. release-please tags in SemVer (`v0.2.0-beta.1`); hatch-vcs
  normalizes that to the **PEP 440** `0.2.0b1` (verified — `packaging` accepts the
  SemVer pre-release forms), so PyPI accepts it and `pip install keycast` ignores
  it unless `--pre` is passed. **To graduate to stable**, land a commit with a
  `Release-As: X.Y.Z` footer (no suffix) — release-please then opens a stable
  release PR at that exact version. The `is_prerelease` job output (`true` when the
  tag contains a `-`) drives the channel guards: `publish-release` marks betas
  `--prerelease --latest=false` (stable forces the inverse), and **`bump-cask` /
  `bump-scoop` are skipped for prereleases** — Homebrew/Scoop have no `--pre`
  notion, so a beta must never reach those buckets. Betas stop at PyPI + the
  GitHub release.
- The `publish` job checks out with `fetch-depth: 0` (hatch-vcs needs the tag
  history), builds with `uv build`, and publishes to PyPI via **trusted publishing**
  (no token; `[tool.uv] trusted-publishing = "always"`), then un-drafts the release.
  PyPI must have a trusted publisher configured for this repo/workflow, and a
  `publish` GitHub environment must exist.
- **CI** (`ci.yml`) runs `prek` hooks (`prek.toml`) and the full `tox` suite
  (`[tool.tox]`) on Linux/macOS/Windows; the Linux job needs `xvfb` because `pynput`
  imports an X backend at import time. **PR titles** are linted as Conventional
  Commits (`check-pr-title.yml`) since release-please derives versions from them.
- `pyrefly` is installed but intentionally **not** in the `style` gate: its strict
  mode rejects pydantic `Field(default=...)` against `Literal` types. mypy, pyright,
  and ty cover `src` instead.

### Choosing a prerelease type (alpha / beta / rc) — and where nightly/canary/insiders fit

There are **three orthogonal axes** here, and conflating them is the usual mistake:

- **Maturity** — *how done is the code?* The ordered ladder
  `alpha < beta < rc < final` (with `dev`/snapshot builds sitting *below* alpha).
  PEP 440 recognizes exactly these three pre-release segments (`a`, `b`, `rc`).
- **Cadence / trigger** — *when and how often is a build cut?* On-demand
  milestone (what release-please does) vs scheduled (`nightly`) vs continuous
  (`rolling` / `edge`).
- **Audience / access** — *who is allowed to get it?* Public vs a small
  risk-detection slice (`canary`) vs an enrolled-or-paying group (`insiders`) vs
  internal-only (`dogfood`).

release-please (and therefore `prerelease-type`) only ever speaks the **maturity**
axis. Cadence and audience are separate mechanisms — see below. `nightly`,
`canary`, and `insiders` look alike ("a build that's ahead of stable") but each is
defined by a *different* axis, which is exactly why they get confused.

**The maturity ladder — pick by "merge this if…":**

| Type | PEP 440 | Meaning | Merge this if… |
|------|---------|---------|----------------|
| **alpha** | `a` (`0.2.0a1`) | Feature-*incomplete*, expect breakage; early/internal testers | …you're still adding or changing features for this release |
| **beta** | `b` (`0.2.0b1`) | Feature-*complete*, hunting bugs; API may still shift slightly | …the features are in and you want real users to shake it out |
| **rc** | `rc` (`0.2.0rc1`) | Believed shippable; ships unless a blocker appears | …this exact build *becomes* the final unless something's wrong |

Sort order is `0.2.0a1 < 0.2.0b1 < 0.2.0rc1 < 0.2.0`, and `pip`/`uv` respect it;
all three are hidden from a plain `pip install` (only surface with `--pre`).

**Current default for keycast: `beta`** (set in `release-please-config.json` as
`prerelease-type: "beta"`). Rationale, specific to this project:

- We are pre-1.0 (0.x) and features for a given release are **done and merged**
  before the prerelease is cut, so `alpha` is semantically too early — we're not
  feature-incomplete.
- The risk the prerelease actually manages is the **packaging / distribution
  surface** (PyInstaller bundles, the Inno installer, the `.dmg`, the Scoop
  manifest) being exercised in the wild — not API churn. That is textbook *beta*:
  "feature-complete, help me find bugs."
- `rc` carries a stronger contract — each rc means "this *is* the final, pending
  sign-off," and the artifact should be bit-for-bit promotable. That ceremony fits
  a 1.0 launch with a formal gate, not a rolling 0.x desktop app.

**The type is not fixed forever — escalate within a cycle via `Release-As`.**
The channel *default* is `beta`, but a `Release-As:` footer overrides the computed
version per-release, so the natural progression is:

1. Roll betas as features land: `0.2.0-beta.1`, `0.2.0-beta.2`, … (just merge).
2. When you believe it's done, cut a final-candidate: land a commit with
   `Release-As: 0.2.0-rc.1` → tag `v0.2.0-rc.1` → hatch-vcs `0.2.0rc1`.
3. Graduate to stable: land `Release-As: 0.2.0` (no suffix). Only a hyphen-free
   tag clears the `is_prerelease` guard, so this is the build that reaches the
   Homebrew cask + Scoop bucket and is marked "Latest".

**First-beta numbering quirk:** release-please's first beta in a cycle is
unnumbered (`0.2.0-beta`), which normalizes to PEP 440 `0.2.0b0` — valid and
correctly ordered (`b0 < b1`), just slightly unusual to see on PyPI. To force a
clean `b1`, land `Release-As: 0.2.0-beta.1` before merging the release PR.

**nightly vs canary vs insiders — the three that look alike:**

- **nightly** *(cadence axis)* — an **automated, scheduled** build (cron) from the
  tip of `main`, cut *whether or not anything is "ready."* Milestone-blind,
  available to anyone, no access gate. The defining trait is the **schedule**. In
  PEP 440 these use the **`.devN` developmental segment** (e.g. `0.3.0.dev20260628`),
  which sorts *below* alpha: `.dev < a < b < rc < final`. Audience intent: "I want
  the absolute latest and accept breakage."
- **canary** *(audience axis — risk)* — a bleeding-edge build pushed to a **small
  slice as a tripwire** (Chrome's term — the canary in the coal mine) to catch
  regressions before the wider channel. The defining trait is **early warning via
  progressive exposure**; the slice is often chosen automatically (e.g. a small %
  of installs). Frequently continuous like nightly, but the *point* is risk
  detection, not freshness.
- **insiders** *(audience axis — access)* — early access gated by **membership,
  enrollment, or sponsorship**, usually a *standing parallel channel* rather than a
  one-off. Two common flavors:
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

**How they'd map to keycast's stack (none implemented today):**

- `nightly` / `canary` / `edge` are **not** modeled by release-please (which is
  milestone- and commit-driven — "given the commits since the last release, what's
  next? open a PR"). They'd be a **separate `on: schedule:` workflow** building
  from `main` HEAD and publishing a `.dev`/date version, with **no human-gated
  release PR**.
- `insiders` is **not a release-please setting at all** — it's a *distribution +
  access-control* problem: a private package index, a sponsor-gated wheel, or a
  separate project name (e.g. a hypothetical `keycast-insiders` on a private
  index). Public PyPI cannot gate by audience, so it could not live there.

> **Wrinkle if nightlies are ever added:** `pyproject.toml` pins
> `version_scheme = "only-version"`, which reports the *exact last tag* between
> tags (no dev distance), so every nightly would collide on the previous version.
> A nightly workflow must override that scheme (or compute a unique date/`.devN`
> version) to get ordered, non-colliding builds.

**Other terms you'll encounter (vocabulary, not because keycast needs them):**

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

**Recommendation:** keycast needs **none** of nightly / canary / insiders / edge
yet — the rolling **beta** channel already covers "let people test before stable
reaches brew/scoop," which is the 90% case. Revisit only post-1.0, and even then
reach for a `nightly`/`edge` workflow first (cheap), before `canary` (needs a
rollout/% mechanism) or `insiders` (needs sponsorship + access control to be worth
the machinery).
