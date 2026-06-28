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

### Choosing a prerelease type (alpha / beta / rc) — and where nightly/canary fit

There are **two orthogonal axes** here, and conflating them is the usual mistake:

- **Maturity** — *how done is the code?* This is the ordered ladder
  `alpha < beta < rc < final`. PEP 440 recognizes exactly these three pre-release
  segments (`a`, `b`, `rc`).
- **Cadence / trigger** — *when and how is the build cut, and for whom?*
  `nightly` and `canary` live here, **not** on the maturity ladder.

release-please (and therefore `prerelease-type`) only ever speaks the **maturity**
axis. The cadence axis is a separate mechanism — see the nightly/canary note below.

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

**Where nightly and canary sit (the cadence axis):**

- **nightly** — an **automated, scheduled** build (cron) from the tip of `main`,
  cut *whether or not anything is "ready."* Milestone-blind. In PEP 440 these use
  the **`.devN` developmental segment** (e.g. `0.3.0.dev20260628`), which sorts
  *below* alpha: `.dev < a < b < rc < final`. Audience: "I want the absolute
  latest and accept breakage."
- **canary** — a continuously bleeding-edge build pushed to a **small audience as
  a tripwire** (Chrome's term — the canary in the coal mine) to catch problems
  before the wider channel. Same scheduled/continuous cadence as nightly; the
  defining trait is *progressive exposure*, not the schedule.

These are **not implemented through release-please**, which is milestone- and
commit-driven (it answers "given the conventional commits since the last release,
what's next? open a PR" — inherently a *planned-release* tool). nightly/canary
are schedule-driven with **no human-gated release PR**, so they would be a
**separate `on: schedule:` workflow** that builds from `main` HEAD and publishes a
`.dev`/date version.

> **Wrinkle if nightlies are ever added:** `pyproject.toml` pins
> `version_scheme = "only-version"`, which reports the *exact last tag* between
> tags (no dev distance), so every nightly would collide on the previous version.
> A nightly workflow must override that scheme (or compute a unique date/`.devN`
> version) to get ordered, non-colliding builds.

**Recommendation:** keycast does **not** need nightly/canary yet — the rolling
beta channel already covers "let people test before stable reaches brew/scoop,"
which is the 90% case. Revisit only post-1.0 if "latest `main`, accept breakage"
becomes a real audience (enough contributors/users to justify it).
