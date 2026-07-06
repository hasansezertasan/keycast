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
- **Mainline cuts stable releases** — the prerelease/beta channel is **designed
  but currently disabled.** The pipeline *can* run mainline as a rolling `beta`
  channel (`prerelease` + `versioning: "prerelease"` + `prerelease-type: "beta"`),
  but those keys are intentionally **absent** from `release-please-config.json`, so
  a normal merge bumps to a stable version. The `is_prerelease` guards in
  `release.yml` remain in place but **inert**: a stable tag has no `-` →
  `is_prerelease=false` → `bump-cask`/`bump-scoop` fire and the release is marked
  "Latest", exactly as before the channel existed. To re-activate the channel, add
  the three config keys back; the full design, rationale, and graduation workflow
  are recorded in [ADR-007](docs/adr/007-prerelease-release-channels.md).
- The `publish` job checks out with `fetch-depth: 0` (hatch-vcs needs the tag
  history), builds with `uv build`, and publishes to PyPI via **trusted publishing**
  (no token; `[tool.uv] trusted-publishing = "always"`), then un-drafts the release.
  PyPI must have a trusted publisher configured for this repo/workflow, and a
  `publish` GitHub environment must exist.
- **CI** (`ci.yml`) runs `prek` hooks (`prek.toml`) and the full `tox` suite
  (`[tool.tox]`) on Linux/macOS/Windows; the Linux job needs `xvfb` because `pynput`
  imports an X backend at import time. **PR titles** are linted as Conventional
  Commits (`check-pr-title.yml`) since release-please derives versions from them.
- `src` is type-checked by four checkers in the `style` gate: **mypy, pyright, ty,
  and pyrefly** (`[tool.tox]` runs `pyrefly check`). pyrefly is the strictest: it
  prunes platform-guarded bodies (`if sys.platform != "darwin": return`) as dead
  code on non-darwin CI targets, then false-positives on the "unreachable"
  bindings. Where a macOS-only body must stay analyzable everywhere, widen the
  guard to a plainly-typed local (`host_platform: str = sys.platform`) to defeat
  its literal-narrowing — see `secure_input.py` and commit `f6ac111`.

### Prerelease channel — operational quick reference (currently disabled)

The rolling `beta` prerelease channel is **designed but not active** (see the
release-pipeline note above and [ADR-007](docs/adr/007-prerelease-release-channels.md)
for the full rationale — the maturity/cadence/audience three-axis model, why `beta`
over alpha/rc, what release-please does and does not own, and why
nightly / canary / insiders / edge are deferred). **To enable it**, add
`prerelease: true` + `versioning: "prerelease"` + `prerelease-type: "beta"` to
`release-please-config.json`. Once enabled, the maturity ladder is
`alpha < beta < rc < final` (default `beta`), and day-to-day:

- **Cut a beta: just merge.** release-please bumps `0.2.0-beta.1 → 0.2.0-beta.2`,
  tagging SemVer (`v0.2.0-beta.1`) which hatch-vcs normalizes to PEP 440 `0.2.0b1`.
  Betas reach **PyPI** (hidden until `pip install --pre`) and the **GitHub
  release** (flagged `--prerelease --latest=false`); `bump-cask` / `bump-scoop` are
  **skipped**, so brew/scoop users stay on stable. The `is_prerelease` workflow
  output (`true` when the tag contains a `-`) drives these guards.
- **Escalate to a final-candidate:** land `Release-As: 0.2.0-rc.1` → `0.2.0rc1`.
- **Graduate to stable:** land `Release-As: 0.2.0` (no suffix). Only a hyphen-free
  tag clears the `is_prerelease` guard, so this is the build that reaches the
  Homebrew cask + Scoop bucket and is marked "Latest".
  - **Consolidate the changelog by hand in this PR.** release-please generates
    each entry from the diff since the *previous* (pre)release, so the `## 0.2.0`
    section contains only what landed *after the last prerelease* — often empty,
    since most features ship in the first `0.2.0-beta`. Before merging the
    `Release-As: 0.2.0` PR, edit `CHANGELOG.md` to fold the `-beta*`/`-rc*`
    subsections into one `## 0.2.0` section, then edit the `v0.2.0` GitHub Release
    notes to match. This manual roll-up is the supported workflow — there is no
    auto-aggregate flag (see [ADR-007](docs/adr/007-prerelease-release-channels.md)).
- **First-beta `b0` quirk:** release-please's first beta in a cycle is unnumbered
  (`0.2.0-beta` → PEP 440 `0.2.0b0`) — valid, just unusual on PyPI. To force a
  clean `b1`, land `Release-As: 0.2.0-beta.1` before merging the release PR.
