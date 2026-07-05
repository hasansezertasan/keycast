# ADR-008: Distribute keycast on Windows via a Scoop bucket

## Status

Accepted — 2026-07-04. Implemented: the `hasansezertasan/scoop-bucket` repo (two
manifests — `keycast` and `keycast-pipx` — plus its updater and dispatch/cron
workflows), the `bump-scoop` job in `release.yml`, and the `InstallSource.SCOOP`
/ `InstallSource.SCOOP_GLOBAL` classification in `keycast.updates.sources`. The
install steps and update advice are documented in `README.md` and
`docs/PACKAGING.md` (§ Scoop bucket). Builds on
[ADR-001](001-desktop-app-packaging.md) (the PyInstaller `keycast-windows.zip`),
[ADR-002](002-update-check.md) / [ADR-005](005-updates-package-structure.md)
(install-source-aware update advice), and sits alongside
[ADR-006](006-windows-installer.md) (the Inno Setup installer) as the third
Windows channel. Supersedes nothing.

This ADR is written **after the fact** — the Scoop channel shipped before it was
recorded, and ADR-002's install-source decision tree predates it. Rather than
retroactively edit those accepted records, this ADR documents the decision as its
own point-in-time entry and extends ADR-002's source model.

## Context

ADR-001 ships Windows as `keycast-windows.zip` (a manual download) and ADR-006
adds `keycast-setup.exe` for install/uninstall hygiene. Neither gives Windows a
**package manager** — the `brew`-equivalent one-line install + upgrade that macOS
users already get from the Homebrew tap. On Windows that role belongs to
[Scoop](https://scoop.sh): a user runs `scoop bucket add …` once, then
`scoop install` / `scoop update` by name.

The tap ships a **cask** (the `.app`) and a **formula** (the CLI). The goal was
to mirror that split on Windows so the two audiences — double-click app users and
terminal users — each get an idiomatic path, and so `keycast info` keeps
reporting an accurate install source (per ADR-002) for the update advice.

Two structural facts constrain the design:

- **Scoop has no cask/formula namespace.** A bucket is a flat set of JSON
  manifests keyed by name; there is no first-class "app vs. CLI" distinction to
  mirror Homebrew's two verbs (`install` vs. `install --cask`).
- **A Scoop install leaves no marker.** Unlike the ADR-006 installer (which drops
  a `.install-source` file) or a Homebrew cask (Caskroom receipt), Scoop just
  extracts the **same `keycast-windows.zip`** under `~/scoop/apps/keycast/current/`.
  There is nothing bundle-internal to distinguish it from a manual
  `GITHUB_RELEASE` download.

## Decision

- **Two manifests, distinct names.** The bucket carries `keycast` (mirrors the
  cask — downloads `keycast-windows.zip`, shims `keycast.exe`) and `keycast-pipx`
  (mirrors the formula — `"depends": "pipx"`, installs via `pipx install keycast`).
  Since Scoop has no cask/formula axis, the split is expressed as two installable
  names rather than two verbs.
- **New install sources: `SCOOP` and `SCOOP_GLOBAL`.** Classified by **location
  alone**, since no marker exists. `detect_install_source()` matches the POSIX
  path fragment `/scoop/apps/keycast/` (per-user) or `/programdata/scoop/apps/keycast/`
  (global), with a `$SCOOP` / `$SCOOP_GLOBAL` env-root fallback for relocated
  roots. Global is checked **first** (a global path also contains the per-user
  fragment), and the whole probe runs **after** the ADR-006 installer marker and
  **before** the `GITHUB_RELEASE` fallback, so the three Windows channels stay
  separable by orthogonal signals.
- **`keycast-pipx` reports `PIPX`, not `SCOOP` — intentionally.** It installs
  *through* pipx, so the running process lives in a pipx venv and
  `detect_install_source()` returns `PIPX` (via the ADR-005 pipx-by-path rule).
  This mirrors the tap's *formula* reporting `HOMEBREW_FORMULA` rather than a
  cask. Only the binary `keycast` manifest yields `SCOOP`.
- **The bucket owns its manifests; this repo keeps none.** As with the Homebrew
  tap, keycast holds no copy of `keycast.json` / `keycast-pipx.json`. The bucket
  repo re-derives each version from its **own** source (GitHub Releases for
  `keycast`, PyPI for `keycast-pipx`) and opens a bump PR.
- **Prompt bumps via `repository_dispatch`, safety net via cron.** `release.yml`'s
  `bump-scoop` job `POST`s a `update-manifest` dispatch to the bucket after a
  release publishes; the bucket's cron is the source of truth if the dispatch is
  skipped or fails. The job is **best-effort and outside the atomic release
  gate** (mirrors `bump-cask`), and — per ADR-007 — is **gated to stable
  releases** so betas never reach Scoop users.

## Rationale

- **Scoop over Chocolatey/WinGet.** Scoop's per-user, no-admin, extract-a-zip
  model is the closest Windows analogue to a Homebrew cask and needs no signed
  package or MSI. It reuses the *exact* `keycast-windows.zip` already built for
  ADR-001, so the app manifest is "point at the release asset + hash" with zero
  new build steps. Chocolatey/WinGet would add packaging ceremony (and WinGet a
  moderation queue) for an audience a bucket already serves.
- **Two names over one manifest with variants.** Scoop has no cask/formula
  concept to fold the two into, and the audiences want different things (a GUI
  shim vs. a CLI on PATH). Two names keep each install idiomatic and each
  `checkver` anchored to the right upstream (Releases vs. PyPI).
- **Location-only detection over a marker.** We *could* have the bucket drop a
  marker like ADR-006's installer, but that would mean forking the shared
  `keycast-windows.zip` handling per channel. Scoop's install location is already
  a stable, test-injectable predicate (a path fragment + env-root), consistent
  with the filesystem-predicate approach `sources.py` uses for the Caskroom
  receipt and the installer marker. No bundle change, no per-channel zip.
- **Global as a separate source.** `scoop install -g` updates only with `-g` and
  elevation (`sudo scoop update keycast -g`); plain `scoop update keycast` would
  not touch it. Conflating the two would emit wrong upgrade advice, so
  `SCOOP_GLOBAL` is distinct and carries its own command string.

## Consequences

- **Update advice (ADR-002 extended).** `keycast info` now recognises two more
  sources. Per-user `keycast` → `scoop update keycast`; global → `sudo scoop
  update keycast -g`; and a `keycast-pipx` install surfaces as `PIPX`, whose
  advice already covers `pipx upgrade keycast`. `README.md`'s Scoop section names
  both manifest update paths explicitly, because `scoop update` is per-manifest.
- **Release pipeline:** `bump-scoop` needs a fine-grained PAT (`BUCKET_TOKEN`,
  **Contents: write**, scoped to the bucket only) because `repository_dispatch`
  is cross-repo and the automatic `GITHUB_TOKEN` cannot reach another repo. When
  the secret is absent the job **warns and exits 0** — releases still succeed and
  the bucket's cron keeps the manifests current.
- **First-beta / prerelease behaviour (ADR-007):** the `is_prerelease` guard
  skips `bump-scoop` for any tag containing a `-`, so Scoop users stay on stable
  exactly like the Homebrew cask.
- **Tests:** `tests/test_updates_sources.py` covers the `SCOOP` / `SCOOP_GLOBAL`
  path-and-env probes and their ordering; the module-load assertions in
  `sources.py` already fail fast if a new source lacks a label or an
  upgrade-command/fallback wiring.
- **Validation limit:** like the bundle (ADR-001) and the installer (ADR-006),
  a real Scoop install cannot be exercised on the macOS dev machine. Detection is
  unit-tested against synthesized paths; an end-to-end `scoop bucket add →
  install → update` on a clean Windows box remains a **manual** check.
- **Two repos to keep in step:** the manifest schema, `checkver` sources, and the
  `update-manifest` dispatch contract live in the bucket repo. A change to the
  release asset names or the dispatch event type must be coordinated across both.
