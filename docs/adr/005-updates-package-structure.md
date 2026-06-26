# ADR-005: `keycast.updates` package structure and the `INSTALLER` signal

## Status

Accepted — 2026-06-25. Refines the implementation shape of the update check
designed in [ADR-002](002-update-check.md): how the code is organized and how
install-source detection is anchored. ADR-002 remains the source of truth for
*what* the feature does and *why*; this ADR records two structural decisions
made while building Phase 1.

## Context

ADR-002 specified a "new module `keycast.updates`" covering source detection,
version comparison, throttle-file I/O, the GitHub fetch, and the check callback.
Building it surfaced two refinements that ADR-002 did not pin down:

1. **One module became unwieldy.** Detection, PEP 440 comparison, throttle-state
   persistence, and orchestration are four genuinely separate concerns with
   different dependencies (filesystem, `urllib`, `packaging`, `threading`) and
   different test seams. A single file mixed them and made the test injection
   surface hard to follow.
2. **Path-only detection was fragile.** ADR-002's decision tree classifies a
   non-frozen install purely by location (pipx venv path, uv tool dir, Homebrew
   prefix, else pip). But pip and uv both install into ordinary `site-packages`,
   so a path heuristic alone cannot tell a `pip install` from a `uv tool install`
   reliably — the two look identical on disk in the general case.

## Decision

### Split `keycast.updates` into a package by concern

`keycast.updates` is a package, not a single module, split so each file owns one
concern and exposes a narrow, individually-testable surface:

- **`keycast.updates.sources`** — how keycast was installed → the right upgrade
  action (`detect_install_source`, `InstallSource`, labels, commands).
- **`keycast.updates.versions`** — the GitHub fetch + PEP 440 comparison
  (`fetch_latest_release_tag`, `is_newer`, `strip_v`).
- **`keycast.updates.state`** — the once-a-day throttle state file
  (`UpdateState`, `read_state`, `write_state`, `due_for_check`).
- **`keycast.updates.__init__`** — orchestration (`notify_pending_update`) and
  the public API re-exports.

This keeps each module's imports minimal (e.g. `versions` is the only file that
imports `urllib`/`packaging`; `state` the only one touching `tempfile`/`json`)
and gives the dependency-injected test seams a clear home per concern.

### Anchor non-frozen detection on the stdlib `INSTALLER` record

pip and uv both stamp an `INSTALLER` file into the distribution's `.dist-info`
(`"pip"` / `"uv"` respectively). `detect_install_source` reads it
(`importlib.metadata.distribution("keycast").read_text("INSTALLER")`) as the
**authoritative** signal for the pip-vs-uv split, falling back to path markers
and env dirs only for the cases the record cannot distinguish:

- **pipx** installs *via pip* into a dedicated venv, so it also records
  `INSTALLER="pip"`. The dedicated `pipx` venv path (`PIPX_HOME` /
  `~/.local/pipx/venvs`) is the only signal, so it is checked **before** the
  `INSTALLER`-based uv split.
- **Homebrew formula** likewise installs via pip (`INSTALLER="pip"`); its Cellar
  path marker is what classifies it.
- A **frozen** bundle has no `INSTALLER` record at all, so the frozen branch
  (cask-vs-Release, per ADR-002) never consults it.

Resolution stays a first-match-wins tree (ADR-002): frozen split first, then
pipx-by-path, then uv (by `INSTALLER` or path/env fallback), then Homebrew
formula, else pip. The `INSTALLER` read is best-effort — any failure returns
`None` and the tree degrades to the path heuristics, never raising.

## Rationale

- **Separation of concerns.** Four small files with one responsibility each are
  easier to read, test, and evolve than one mixed module; it also matches the
  codebase's existing "small modules as a pipeline" style.
- **Authoritative over heuristic where possible.** The `INSTALLER` record is the
  signal the packaging ecosystem itself writes for exactly this question, so it
  is preferred over guessing from a path; path/env checks remain as the fallback
  for the cases (pipx, Homebrew-formula) the record genuinely cannot resolve.
- **No new dependency.** `importlib.metadata` is stdlib; the refinement adds a
  more reliable signal at zero cost.

## Consequences

- **Import paths.** Consumers import from the package root
  (`from keycast.updates import notify_pending_update, detect_install_source,
  install_source_label, InstallSource`); the public API in
  ADR-002 is unchanged, only its internal layout.
- **Tests mirror the split.** `tests/test_updates_sources.py`,
  `tests/test_updates_versions.py`, `tests/test_updates_state.py`, and
  `tests/test_updates_check.py` each cover one module; `_read_installer` is an
  injectable seam (`read_installer=`) so detection tests never depend on the
  ambient machine's real `INSTALLER` record.
- **No behavior change for users.** This is an internal structuring decision; the
  notice, throttle, opt-out, and offline-safety all behave exactly as ADR-002
  specifies.
