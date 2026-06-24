# Packaging & Distribution

> **Status: in progress.** The PyInstaller recipe (`packaging/keycast.spec`,
> `packaging/entry.py`) and the release pipeline (`.github/workflows/release.yml`,
> plus the PR-time check in `ci.yml`) are implemented and validated against a real
> build (PyInstaller, Astral Python 3.14.6, Tk 9.0). The **cask** in the tap is
> the remaining piece; the Windows build is implemented and verified green by CI
> (PR #3). This file is the operational contract (the **how**); the **why**
> behind every choice lives in [ADR-001](adr/001-desktop-app-packaging.md).

## Two distribution channels

keycast ships through two Homebrew vehicles that intentionally coexist:

| Channel | Command | Audience | Source of truth |
|---|---|---|---|
| **Formula** | `brew install keycast` | CLI users (`keycast version`, `keycast info`, run from a terminal) | PyPI package |
| **Cask** | `brew install --cask keycast` | GUI users (double-click `.app`, grant input permissions once) | GitHub Release `.dmg` |

Most of what follows concerns the **macOS `.app`** and its cask. The release
pipeline also builds a **Windows `.zip`** (PyInstaller, attached as a GitHub
Release asset for direct download); Linux users install from PyPI. Casks are
macOS-only.

## Build foundation (non-negotiable)

PyInstaller copies Tk **from the building Python** on every platform, so the
build Python must be one with working Tcl/Tk. Both the macOS and Windows builders
pin **uv-managed Astral CPython `3.14.6`**. On **macOS** this is verified-good
(tested: Tk 9.0 / Tcl 9.0.3; see [ADR-001](adr/001-desktop-app-packaging.md)) —
verified-good, not a proven minimum, since the fix landed in
`python-build-standalone` release `20250808`. On **Windows** the same pin is used
and was **verified green by CI** (PR #3 builds a working `_tkinter` bundle). Bump
the pin deliberately:

```bash
uv python install 3.14.6
uv python find 3.14.6   # path used by the build venv
```

> ⚠️ Do **not** build against Homebrew `python@3.14` (no `_tkinter`) or Astral
> `3.14.3` (Tk present but Tcl init fails — predates `python-build-standalone`
> release `20250808`). An unpinned runner Python will silently produce a
> Tk-less or crashing bundle. See ADR-001 for the measured matrix.

## Build the bundle (PyInstaller)

### Entry point

The bundled app launches straight into the overlay (the GUI default), i.e. the
behavior of `keycast` with no subcommand. The PyInstaller entry script calls the
overlay entry point directly:

```python
# packaging/entry.py
from keycast.main import main

if __name__ == "__main__":
    main()
```

### Recipe

The committed **`packaging/keycast.spec`** is the source of truth — one spec for
both platforms. Build from the repo root in a venv on Astral 3.14.6 with keycast
+ pyinstaller installed:

```bash
pyinstaller --noconfirm packaging/keycast.spec
# macOS:   dist/keycast.app
# Windows: dist/keycast/  (keycast.exe + deps; BUNDLE is a no-op off macOS)
```

PyInstaller auto-detects `_tkinter` + Tcl/Tk and the platform input backend
pynput uses (pyobjc-Quartz on macOS, win32 on Windows) — no extra
`--hidden-import`/`--collect` flags as of keycast 0.1.0, though CI must re-verify
after any dependency bump. The spec was generated from this equivalent CLI form,
kept for reference:

```bash
pyinstaller --noconfirm --windowed --name keycast \
  --osx-bundle-identifier com.hasansezertasan.keycast packaging/entry.py
```

Open items (tracked, not yet decided): an app **icon** (`--icon keycast.icns`)
once one exists; whether to expose the CLI subcommands from inside the bundle
(default: no — the formula owns the CLI).

## Package the bundle

**macOS — `.dmg`:**

```bash
hdiutil create -volname keycast -srcfolder dist/keycast.app \
  -ov -format UDZO dist/keycast.dmg
shasum -a 256 dist/keycast.dmg   # sha256 for the cask
```

(`create-dmg` may replace `hdiutil` later if a styled background/layout is
wanted; `hdiutil` is the dependency-free baseline.)

**Windows — `.zip`** (the `dist/keycast/` folder PyInstaller produces, since
`BUNDLE` is a no-op off macOS):

```powershell
Compress-Archive -Path dist/keycast -DestinationPath keycast-windows.zip
```

## Release & CI

The release pipeline (`.github/workflows/release.yml`, workflow name **Release**)
is a decomposed DAG gated on the release-please flow (see `CLAUDE.md`). The
release is **atomic** — nothing publishes unless every artifact builds:

```text
release-please ─┬─ build-package  (sdist + wheel,  ubuntu)
                ├─ build-macos    (.app → .dmg,    macos-15 / arm64)
                └─ build-windows  (.exe folder → .zip, windows-latest)
                          │  publish-pypi needs ALL three
                          ▼
                   publish-pypi    (Trusted Publishing; id-token only)
                          ▼
                   publish-release (download all artifacts, attach, un-draft)
                          ▼
                   reconcile       (close phantom PR, re-dispatch)
```

- **Builders** are pure producers (`contents: read`): each builds on its own
  runner and uploads a workflow artifact — they never touch the release. The
  macOS/Windows builders **must** pin Astral Python 3.14.6 (see the
  build-foundation warning above); both build from the committed
  `packaging/keycast.spec` (PyInstaller's `BUNDLE` step is a no-op on Windows, so
  there it yields the `dist/keycast/` folder, which is zipped).
- **`publish-pypi`** depends on all three builds, downloads the sdist/wheel, and
  publishes via PyPI Trusted Publishing (`id-token: write`, no other scope).
- **`publish-release`** downloads every artifact, attaches them to the release
  tag, and un-drafts it (`contents: write`). The GitHub Release **intentionally
  mirrors the PyPI sdist/wheel** alongside the `.dmg`/`.zip`, for a complete,
  offline-installable release page.
- **`reconcile`** closes the phantom release PR and re-dispatches the workflow
  (`pull-requests` + `actions` write).

Each write scope lives on exactly one job (least privilege). Because the release
is **atomic**, a flaky platform build blocks the PyPI release too — the trade
chosen so a published version never ships with a missing artifact.

`ci.yml` runs **build-only checks** on every PR — `build-macos` and
`build-windows` — that bundle from the same spec and assert the result contains
the launcher and `_tkinter`, so packaging regressions fail on the PR, not at
release. Each also uploads an **unsigned, version-0.0.0 preview artifact** (7-day
retention: `keycast-macos-preview`, `keycast-windows-preview`) so a reviewer can
download and launch-test it — the live path CI cannot exercise (see the
verification checklist below). The macOS preview is wrapped in a `.dmg` before
upload: `actions/upload-artifact` re-zips its input and drops the exec bit and
symlinks a `.app` depends on, so a raw `.app` would download "damaged"; the
`.dmg` carries its own filesystem and survives intact (the Windows preview is the
plain `dist/keycast/` folder, which needs neither). These previews are **not**
release artifacts; `release.yml` produces those.

## Cask (in the tap)

In [hasansezertasan/homebrew-tap](https://github.com/hasansezertasan/homebrew-tap),
alongside the existing formula:

```ruby
cask "keycast" do
  version "X.Y.Z"
  sha256 "<sha256 of keycast.dmg>"

  url "https://github.com/hasansezertasan/keycast/releases/download/v#{version}/keycast.dmg"
  name "keycast"
  desc "Cross-platform keystroke and mouse-click visualizer"
  homepage "https://github.com/hasansezertasan/keycast"

  app "keycast.app"

  caveats <<~EOS
    keycast needs Accessibility and Input Monitoring permission:
      System Settings > Privacy & Security > Accessibility / Input Monitoring
    On first launch, macOS Gatekeeper will block the unsigned app — right-click
    the app and choose Open once to approve it.
  EOS
end
```

> The app is **unsigned** (ad-hoc only) until an Apple Developer account is
> available; hence the Gatekeeper caveat. Adopting Developer-ID signing +
> notarization later removes that step and supersedes ADR-001's "unsigned"
> stance.

## Local reproduction

```bash
uv python install 3.14.6
uv venv --python 3.14.6 .venv-pkg
uv pip install --python .venv-pkg/bin/python . pyinstaller==6.16.0
.venv-pkg/bin/pyinstaller --noconfirm packaging/keycast.spec
open dist/keycast.app
```

## Verification checklist

The smoke build proved the bundle **constructs** keycast (Settings, logging, the
Tk overlay with `overrideredirect`/`-alpha`/`-topmost`, and the pynput backend
import). It did **not** prove a live session. The quickest build to test is the
`keycast-macos-preview` / `keycast-windows-preview` artifact from a PR's CI run
(or build locally as above). Before the first cask release, verify manually on a
clean Mac:

- [ ] `dist/keycast.dmg` mounts and the app drags to `/Applications`.
- [ ] First launch: right-click → Open clears Gatekeeper (unsigned).
- [ ] Granting Accessibility + Input Monitoring lets the overlay show real
      keystrokes typed into *other* apps (the live pynput path the smoke test
      could not exercise).
- [ ] The overlay renders correctly under **Tk 9.0** (transparency, topmost,
      borderless).
- [ ] `brew install --cask keycast` from the tap installs the released `.dmg`.
