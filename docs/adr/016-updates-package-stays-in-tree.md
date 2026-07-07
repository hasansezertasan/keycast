# ADR-016: `keycast.updates` stays in-tree — extraction trigger is a second consumer, not more channels

## Status

Accepted — 2026-07-07. Records why the update-check code stays a `keycast`
subpackage rather than becoming a standalone dependency, and the condition that
would reverse that. Extends the build-vs-buy through-line of
[ADR-004](004-update-check-build-vs-buy.md) and the package-structure decision of
[ADR-005](005-updates-package-structure.md); ADR-002 remains the source of truth
for *what* the feature does. Triggered by a review question: "as we add publish
channels, should `updates/` become an external package we depend on?"

## Context

The publish-channel count keeps growing — pip, pipx, uv tool, Homebrew formula,
Homebrew cask, GitHub Release, Windows installer, Scoop (per-user + global),
Microsoft Store ([ADR-009](009-microsoft-store.md)), Mac App Store
([ADR-014](014-mac-app-store.md)). Each new channel adds an `InstallSource`
member, a detection branch, an upgrade command, and a label to
`updates/sources.py`. A growing surface *feels* like it wants its own home, so
the question is whether to extract `keycast.updates` into a reusable package (an
"install-source-aware update notifier") that keycast then depends on.

Two facts frame the answer:

1. **Adding a channel is already a localized, checked change.** A new channel
   touches one file (`sources.py`) in four disciplined steps — enum member,
   detection branch, `_UPGRADE_COMMANDS` entry, `_SOURCE_LABELS` entry — and the
   paired `assert set(...) == set(InstallSource)` at module load fails loudly if
   any member is left unwired. The module is *designed* to absorb channels
   cheaply; the assert already enforces the "don't forget the new case"
   discipline that extraction is often reached for.

2. **The code is saturated with keycast specifics.** Not a generic library
   wearing a keycast hat:
   - `sources.py`: `RELEASES_URL`, the upgrade-command table (`pip install -U
     keycast`, `brew upgrade --cask keycast`, …), path markers (`/cellar/keycast/`,
     `/scoop/apps/keycast/`), `read_installer("keycast")`, the `_MASReceipt` probe
     assuming keycast's bundle layout.
   - `versions.py`: the hardcoded GitHub repo URL and `keycast/{__version__}`
     User-Agent.
   - `state.py` / `__init__.py`: imports of `keycast.__version__`,
     `keycast.settings.UPDATE_CHECK_FILE_PATH`, and the `check_for_updates`
     opt-out from `Settings`.

## Decision

**Keep `keycast.updates` in-tree.** More publish channels is **not** a trigger to
extract — it grows the *first* consumer, it does not create a *second* one, and
adding a channel is cheaper inside the package than across a released dependency
boundary.

**The extraction trigger is a concrete second consumer** — a second app (another
Python GUI/CLI) that wants the same "detect how I was installed → recommend the
right upgrade action" behavior. Until that exists, a package boundary is an
abstraction with one user.

**Cheap intermediate step, taken now: keep the keycast-specific constants
injectable.** Several seams already exist for tests (`read_installer=`,
`cask_receipt_exists=`, `fetch=`, `spawn=`, `location=`, `env=`). Continue to
prefer parameters over module-level constants for anything keycast-specific that
detection/fetch consume, so a future extraction is a lift-and-shift (constants
become a caller-supplied config object) rather than a rewrite. This costs
near-nothing today and does not introduce a boundary.

If the trigger fires, the shape is roughly: a small `install-source` package
exposing `detect_install_source(config)` and a fetch/notify pair, where `config`
carries the distribution name, repo, marker set, and command table; keycast
depends on it and supplies its ADR-005 heuristics as data. That extraction gets
its own ADR at that time.

## Rationale

- **Second consumer, not bigger first consumer.** A package earns its boundary
  when two codebases would otherwise copy-paste it. Channel count optimizes the
  wrong variable — it makes the single existing consumer larger, which the
  in-tree structure ([ADR-005](005-updates-package-structure.md)) already handles.
- **Extraction makes the frequent operation harder.** Adding a channel is the
  thing done often; a package boundary puts a version pin and a dependency release
  in front of every future channel. Optimizing for the rare event (reuse) at the
  expense of the common one (add a channel) is backwards.
- **The reusable IP is narrow and the generic part is small.** `versions.py`
  (PEP 440 compare + guarded GitHub fetch) and `state.py` (atomic throttle file)
  are ~generic npm-pattern boilerplate; the *valuable* part — install-source
  disambiguation — is exactly the part least generic, because its correctness
  lives in per-distribution heuristics (formula-vs-brew-Python, cask-vs-drag,
  Scoop per-user-vs-global, MAS-before-cask ordering). Generalizing it dilutes
  the thing worth reusing and pushes those decisions onto a caller.
- **Consistent with build-vs-buy.** [ADR-004](004-update-check-build-vs-buy.md)
  already found that no external library covers concern #1 (source routing) and
  that adding an HTTP dependency to save ~30 stdlib lines is the wrong trade.
  Extracting *our own* code into a package we maintain separately carries the
  boundary cost without the reuse benefit — the same calculus, one step further.
- **The assert already provides the safety extraction is used for.** Load-time
  failure on an unwired `InstallSource` gives the "new case can't be forgotten"
  guarantee without a package split.

## Consequences

- **No structural change now.** `keycast.updates` remains the four-module package
  from [ADR-005](005-updates-package-structure.md); the public API
  (`notify_pending_update`, `detect_install_source`, `install_source_label`,
  `InstallSource`) is unchanged.
- **A documented trigger exists.** The next contributor tempted to extract on
  channel-count has this ADR as the answer; the real condition (a second
  consumer) is written down, so the decision does not get re-litigated per channel.
- **Injectability is now a standing convention, not just a test seam.** New
  keycast-specific inputs to detection/fetch should be parameters with defaults,
  keeping a future extraction a lift-and-shift.
- **Revisit when a second tool appears.** If keycast spawns or shares code with
  another distributed app, this ADR is superseded by an extraction ADR that
  defines the `config` contract and the package's ownership of the generic
  concerns (#2, #3) versus the caller's ownership of the heuristics (#1).
