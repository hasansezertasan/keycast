# ADR-002: Install-source-aware update check (notify now, self-update later)

## Status

Accepted — 2026-06-25. Documents the design contract for GitHub issue
[#9](https://github.com/hasansezertasan/keycast/issues/9) ("In-app update /
version check"); the contract was written first, per the project's
Document-Driven Development workflow. **Phase 1** (automatic background notify,
no dedicated command) is **implemented** in `keycast.updates`; **Phase 2** (the
`keycast update` verb + in-place self-update of the frozen executable) is a
committed follow-up and is *not* built yet.

Builds on [ADR-001](001-desktop-app-packaging.md), which established the three
install channels this decision routes between.

## Context

keycast has no update mechanism. Users learn about new releases by chance and
update through whatever channel they installed from. ADR-001 left the project
with **three distinct install channels**, each with a different correct way to
update:

| Channel | Artifact | `sys.frozen`? | Correct update action |
|---|---|---|---|
| PyPI via `pip` / `uv` / `pipx` / `uvx` | wheel (real Python import) | ❌ | `pipx upgrade keycast` / `uv tool upgrade keycast` / re-run `uvx keycast@latest` / `pip install -U keycast` |
| Homebrew **formula** (CLI) | wheel via brew Python | ❌ | `brew upgrade keycast` |
| Homebrew **cask** (`.app`) | the release `.dmg` (PyInstaller bundle) | ✅ | `brew upgrade --cask keycast` |
| GitHub Release, manual download | `.dmg` / `.zip` (PyInstaller bundle) | ✅ | replace the app — the only channel where *self-update* is meaningful |

The issue proposed either (a) a lightweight "newer version available" check
against the GitHub Releases API with an opt-out, or (b) leaning entirely on
distribution-managed updates. This ADR adopts a hybrid: **always notify; never
self-update something a package manager owns; reserve self-update for the one
channel that nobody else manages** (manually-downloaded Release builds).

### The detection problem (why `sys.frozen` alone is insufficient)

The intuitive rule "frozen build ⇒ self-update, otherwise recommend a command"
is **wrong**, because the Homebrew cask installs the *same frozen `.dmg`* as a
manual download. A cask install is frozen but must still be updated via
`brew upgrade --cask` — self-updating it would fight Homebrew and desync its
receipts. So `sys.frozen` distinguishes "Python import" from "bundle", but not
"manually downloaded bundle" from "brew-managed bundle". A second, path-based
signal is required, and it is a heuristic, not a certainty.

## Decision

Add an **install-source-aware update check** with two surfaces and a privacy
opt-out, implemented in two phases.

### Source detection (decision tree)

A new helper (`keycast.updates.detect_install_source()`) classifies the running
process. Resolution order — first match wins:

1. **Not `getattr(sys, "frozen", False)`** → a Python-import install. Sub-classify
   by location to pick the recommended command:
   - path under `pipx`'s venvs (`PIPX_HOME` or `~/.local/pipx/venvs`) → **pipx**
   - path under uv's tool dir (`~/.local/share/uv/tools`) or uv cache → **uv tool / uvx**
   - path under a Homebrew prefix (`$(brew --prefix)`, typically `/opt/homebrew`
     or `/usr/local`) → **Homebrew formula**
   - otherwise → **pip** (generic `pip install -U`)
2. **Frozen, and the executable path is under a Homebrew prefix / `Caskroom`**
   (or `/Applications/keycast.app` with a matching cask receipt) → **Homebrew cask**.
3. **Frozen, anywhere else** → **manual GitHub Release download** — the only
   `SELF_UPDATABLE` source.

When the heuristic cannot decide (step 1's sub-classification or step 2 is
ambiguous), it returns an **`UNKNOWN`** source. Rather than guess a wrong
command, the notice then points at the Releases page —
`"keycast 0.5.0 available — https://github.com/hasansezertasan/keycast/releases"` —
which is correct for every channel. Detection never raises; any error degrades
to `UNKNOWN`.

### Version comparison

- "Current" is `keycast.__version__` (hatch-vcs, baked into the bundle at build
  time — already correct in every channel; no new plumbing).
- "Latest" is the `tag_name` of
  `GET https://api.github.com/repos/hasansezertasan/keycast/releases/latest`,
  fetched with **stdlib `urllib.request`** (no new HTTP dependency), a short
  timeout, and a `User-Agent: keycast/<version>` header.
- The leading `v` is stripped and the two are compared with **PEP 440 ordering
  via `packaging.version.Version`**. `packaging` is the comparator every Python
  packaging tool uses (pip/setuptools vendor it; hatch/pipx/pdm/poetry-core
  depend on it), and PEP 440 awareness is *required* here: hatch-vcs hands a
  source checkout a local/dev version such as `0.3.1.dev4+g1234abc`, which naive
  string/tuple comparison orders incorrectly. **`packaging` is declared as an explicit
  runtime dependency** — it is currently only a dev/transitive dep, so it is
  absent from PyInstaller bundles unless declared (it would import under
  `uv run` and then `ImportError` in the shipped `.app`/`.exe`).
- Pre-releases and drafts are ignored (`/releases/latest` already excludes them).

### Throttle & privacy

- A new top-level boolean flag **`check_for_updates: bool = True`** on `Settings`
  gates the *passive* check. Default-on with opt-out, honoring the issue's
  acceptance bar; set `false` to disable all automatic network calls.
- Throttle state lives in a **separate file `~/.keycast/update-check.json`**
  (`{ "last_checked": <epoch>, "last_seen_tag": "v0.x.y" }`), *not* in
  `config.json` — `Settings` is `frozen` and rewritten atomically, so mutable
  runtime state does not belong there. The passive check runs at most once per
  **24 h**.
- **Offline / failure is silent.** Any network, DNS, timeout, rate-limit (HTTP
  403/429), or parse error is swallowed and logged at `DEBUG`; the app never
  blocks, warns loudly, or crashes because a check failed.

### Surfaces (no dedicated command)

There is **no `keycast check`/`keycast update` subcommand in Phase 1.** The
`update` verb is deliberately reserved for the Phase 2 self-update, so it never
ships meaning "just check" only to be redefined to "actually update" later.
Instead the check is a **callback wired into the Typer root callback**, so it
runs on *every* invocation (gated by `check_for_updates` + the 24 h throttle),
following the npm-style "show cached result now, refresh in the background"
pattern:

- **Read cache, notify instantly.** On every invocation the callback reads
  `update-check.json` and, if a newer version than `__version__` is already
  cached, shows the notice immediately — **no network call on the hot path**.
  - **GUI launch** (`keycast`): the notice is pushed through the **existing
    `TextSink`** to the overlay (e.g.
    `"keycast 0.5.0 available — brew upgrade --cask keycast"`), reusing the
    single-sink display path; it is transient (fades like any event), never modal.
  - **CLI** (`keycast version` / `info`): a single line is printed to **stderr**
    so it never corrupts the parseable stdout of `version`/`info`.
- **Refresh in the background.** If the throttle window has elapsed, a
  **background daemon thread** refreshes the cache (the one GitHub request); the
  result surfaces on a *later* invocation.
  - *Known tradeoff:* a short-lived CLI call (`keycast version`) usually exits
    before the daemon thread's request completes, so cache refresh realistically
    lands during the long-lived **GUI** session — acceptable, since the GUI is
    the primary surface and this is npm's exact behavior. A tight-timeout
    *synchronous* CLI check was rejected because it would break the "`version` /
    `info` stay instant and network-free" property the codebase already
    establishes via lazy imports.
- `keycast info` also gains an **`Install source:`** line (e.g.
  `Install source: Homebrew cask`) from `detect_install_source()` — cheap, no
  network, and useful in bug reports.

### Phasing

- **Phase 1 (notify) — specified for build now.** Everything above *except*
  performing the binary swap. For a `SELF_UPDATABLE` build the notice names the
  GitHub Releases page rather than a package-manager command.
- **Phase 2 (self-update) — committed follow-up, not built.** Introduces the
  reserved **`keycast update`** subcommand and in-place update of a
  manually-downloaded Release build only: download the new `.dmg`/`.zip`, verify
  it, and replace the bundle. This carries the platform hazards that make it a
  separate phase:
  - **Windows** cannot overwrite a running `.exe`; requires the
    rename-aside → write-new → relaunch → exit dance (or a small updater helper).
  - **macOS** `.app` bundles are signed/notarized (eventually — ADR-001 ships
    unsigned today); replacing files in place breaks the signature, so the whole
    bundle must be swapped, and a signed feed (Sparkle-style appcast) is the
    mature path. Until ADR-001's "unsigned" stance is revisited, Phase 2 stays
    deferred.

## Rationale

- **Routes to the channel that owns the install.** Self-updating a brew- or
  pipx-managed install would desync the manager; recommending its command is
  both safer and what users expect. Self-update is offered only where no manager
  is in play.
- **Honest about detection limits.** Cask-vs-manual is a path heuristic; the
  `UNKNOWN` fallback (point at the Releases page) is correct behavior, not a bug,
  and the worst case is a slightly-off suggestion the user can ignore.
- **One small, standard dependency.** The HTTP call uses stdlib
  `urllib.request`; the only added package is `packaging`, the PEP 440 comparator
  every Python packaging tool already relies on — keeping the stack lean while
  not re-implementing version ordering.
- **Architecturally minimal.** The notice is just another `TextSink` string and
  a daemon thread, consistent with the single-sink event flow; throttle state is
  isolated from the frozen `Settings`.
- **De-risked by phasing.** The valuable 80 % (knowing an update exists and how
  to get it) ships without the signing/relaunch machinery that is the genuinely
  hard, platform-specific 20 %.

## Consequences

- **Settings API change (Phase 1):** `Settings` gains a 4th top-level scalar
  flag, `check_for_updates: bool = True`. This is a real public-API change, so
  `tests/test_docs_contract.py` must be updated — its `scalar_flags` set and the
  "exactly N sections + M scalars" assertion go from 3 → 4 scalars. Updating that
  pin is the correct fix (the docs and code change together), not a test
  workaround.
- **New runtime dependency:** `packaging` is added to `[project.dependencies]`
  (PEP 440 comparison; see [Version comparison](#version-comparison)). It is the
  only new dependency — the HTTP call uses stdlib `urllib`.
- **New package:** `keycast.updates` (source detection, version compare,
  throttle-file I/O, GitHub fetch, and the check callback). It is split into
  modules by concern — `sources`, `versions`, `state`, and the `__init__`
  orchestrator — and anchors non-frozen detection on the stdlib `INSTALLER`
  record; both decisions are recorded in [ADR-005](005-updates-package-structure.md).
  No new CLI subcommand in Phase 1 — the check is invoked from the existing Typer
  root callback in `cli.py`; the `keycast update` verb is reserved for Phase 2.
- **`keycast info` change:** gains an `Install source:` line. This is additive
  output; `tests/test_docs_contract.py` does not pin `info`'s text, so no
  contract change is needed for it (only the `check_for_updates` flag triggers
  the scalar-count update noted above).
- **New state file:** `~/.keycast/update-check.json`, created lazily; corrupt or
  unreadable state degrades to "check now" (same defensive posture as
  `create_settings_file`).
- **Network behavior:** keycast makes at most one outbound request per 24 h,
  in the background. All optional and opt-out-able; fully offline-safe. Privacy
  note added to README and `docs/PROJECT_OVERVIEW.md` (Security & Privacy).
- **Docs (DDD):** this ADR is the rationale; README has an **Updates** section
  and the `check_for_updates` flag in the config example; `docs/API.md` documents
  the flag. (These shipped as the contract before Phase 1 code, then had their
  "Planned" markers removed once it landed.)
- **Phase 2 triggers:** acquiring an Apple Developer ID (per ADR-001's supersede
  trigger) is a prerequisite for a safe macOS self-update; Windows self-update
  can proceed independently. Phase 2 should be recorded as its own ADR when built.

### Resolved during design

- **Version comparison** → `packaging.version.Version`, declared as an explicit
  runtime dependency (not a local parser).
- **No `--check` / `update` command in Phase 1** → the check runs automatically
  from the Typer root callback on every invocation; the `update` verb is reserved
  for Phase 2 self-update.
- **`UNKNOWN` source** → notice points at the Releases page rather than guessing
  a command.
- **`keycast info`** → adds an `Install source:` line.

### Open questions (to settle at implementation)

- Exact stderr-notice formatting for `version`/`info` (single line; wording).
- Throttle interval is specified at 24 h — confirm during implementation it
  shouldn't be configurable (kept fixed in Phase 1 to avoid a second new
  setting).
