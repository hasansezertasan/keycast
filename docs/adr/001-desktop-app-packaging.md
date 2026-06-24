# ADR-001: Package keycast as native desktop apps (macOS + Windows) via PyInstaller

## Status

Accepted — 2026-06-24. Build recipe (`packaging/keycast.spec`, `entry.py`) and
release pipeline (`release.yml` + `ci.yml` check) implemented and validated
against a real build; the **Windows** build is verified green by CI (PR #3). The
**cask** (in the tap) remains.

Supersedes nothing. May be **superseded** if code signing + notarization are
adopted (see [Consequences](#consequences)) or if Briefcase ships Tk in its
macOS support package.

## Context

keycast was added to the author's Homebrew tap
([hasansezertasan/homebrew-tap](https://github.com/hasansezertasan/homebrew-tap))
as a **formula**. A formula is the right vehicle for a pip-installable CLI, and
keycast genuinely is one (`keycast`, `keycast version`, `keycast info`). But
keycast is *also* a GUI overlay, and a double-click-to-launch macOS `.app`
distributed via a **cask** is a materially better experience for GUI users — and
gives pynput a stable bundle identity to hold Accessibility / Input-Monitoring
permissions against, instead of a bare `python` interpreter that loses the grant
on every reinstall.

**Goal:** ship keycast's GUI as installable desktop bundles — a macOS `.app`
(Homebrew **cask**) and a Windows `.zip` (GitHub Release) — *in addition to* the
existing formula, without regressing the cross-platform app. (The work began with
the macOS cask question; Windows packaging was folded in once PyInstaller proved
out as the bundler.)

A cask does not build anything — it downloads a pre-built artifact
(`.dmg`/`.zip`/`.pkg`) and relocates the `.app`. So the real work is (a) building
the bundle and (b) hosting it. The repo already has the host: release-please
drafts a GitHub Release per tag, to which CI jobs attach the build artifacts.

The open question was **which bundler**. Five were evaluated. Because earlier
claims about Tk support proved unreliable from memory, every load-bearing claim
below was verified **empirically** on this platform (macOS arm64), not from docs.

### Foundation: which Python 3.14 actually has working Tk

macOS bundlers copy Tk *from the building Python*, so a working build Python is a
prerequisite for any bundler. Astral's `python-build-standalone` only began
shipping working dynamic Tcl/Tk on macOS in release **`20250808`**. Measured
locally:

| Python 3.14 build | `_tkinter` | `Tk()` at runtime |
|---|---|---|
| Homebrew `python@3.14` (3.14.6) | ❌ absent | — (needs `python-tk@3.14`) |
| uv / Astral `3.14.3` | ✅ present | ❌ "Tcl wasn't installed properly" (pre-`20250808`) |
| **uv / Astral `3.14.6`** | ✅ present | ✅ **Tk 9.0 / Tcl 9.0.3** |

The build foundation is therefore **uv-managed Astral Python `3.14.6`**. Note it
ships **Tk 9.0**, not 8.6; the overlay realized cleanly under Tk 9 in the bundle.

### Bundlers evaluated

| Bundler | Rewrite `display.py`? | Tk on 3.14 | macOS `.app` | Verified outcome |
|---|---|---|---|---|
| **Briefcase** | yes (and still fails) | ❌ stripped | ✅ | Built a minimal Tk app → bundle launched with `ModuleNotFoundError: No module named 'tkinter'`. BeeWare's support package (`Python-3.14-macOS-support.b9`, *not* Astral's build) omits Tk because it targets Toga. |
| **Toga** | full rewrite | n/a | ✅ | Toga's `Window` API exposes none of the four overlay primitives keycast needs (frameless, always-on-top, transparency, click-through) — verified against the live API. Reaching them requires per-platform native code, defeating Toga's only benefit. |
| **Flet** | full rewrite + Flutter runtime | n/a | ✅ (`flet build`) | Window *can* do the overlay (`frameless`, `always_on_top`, `opacity`, transparent `bgcolor`, `ignore_mouse_events` click-through). But `page.on_keyboard_event` is **focus-bound** — an overlay is never focused, so it cannot capture keys typed into *other* apps. pynput stays regardless; the hoped-for "first-class keystroke tracking" does not apply. |
| **Nuitka** | none | ✅ (Astral 3.14.6) | ✅ | Built a `.app` (285.7 s, 78 MB) with `_tkinter` + Tcl/Tk 9 bundled via `--enable-plugin=tk-inter`, but **crashed at runtime**: `NameError: name 'LoggingSettings' is not defined`. Compiling Python→C perturbs Pydantic v2's runtime annotation resolution (`settings.py:500` `logging: LoggingSettings`, eagerly evaluated, no `from __future__ import annotations`). |
| **PyInstaller** ✅ | **none** | ✅ (Astral 3.14.6) | ✅ | Built a `.app` (**13.4 s, 41 MB**) bundling `_tkinter.cpython-314-darwin.so`, `libtcl9.0`/`libtk9`, and pyobjc-Quartz (pynput's macOS backend). The bundle launched the **real** `Keycast()` composition root → `OK keycast=0.1.0 tk=9.0 pynput=ok py=3.14.6`. |

The two compilers/packagers (Nuitka, PyInstaller) keep the working Tk code
unchanged; the two GUI toolkits (Toga, Flet) require rewriting all ~394 lines of
`display.py`. Toga cannot even express the overlay; Flet can but does not remove
the pynput dependency and brings a heavy Flutter runtime + toolchain.

## Decision

Package and distribute keycast's GUI as native desktop builds, alongside the
existing PyPI/formula CLI path:

- **Build:** **PyInstaller** against **uv-managed Astral Python `3.14.6`** from a
  single committed spec — a macOS `.app` (windowed) and a Windows folder
  (`keycast.exe`, zipped).
- **Package & ship:** a decomposed release pipeline (`release.yml`) builds the
  `.app` → `.dmg`, the Windows `.zip`, and the sdist/wheel on separate runners and
  attaches them to the GitHub Release. The release is **atomic** — PyPI publishes
  only if all builds succeed.
- **Install:** macOS via a **cask** in the Homebrew tap (release `.dmg` +
  `sha256`); Windows via direct `.zip` download from the GitHub Release; CLI/Linux
  via the existing formula / `pip install` from PyPI.

The bundler decision below was reached by **macOS-only empirical evaluation**; the
chosen recipe extends to Windows because PyInstaller's macOS `BUNDLE` step is a
no-op there (verified), and the Windows build was confirmed green by CI (PR #3).

Initial macOS releases are **unsigned** (ad-hoc signed only); no Apple Developer
account is in use yet.

## Rationale

- **Zero rewrite.** PyInstaller bundles the existing Tk + pynput code as-is. Tk
  is the *right* toolkit for a borderless, semi-transparent, always-on-top
  overlay (`overrideredirect` / `-alpha` / `-topmost` in `display.py:80-84`);
  the "nicer" toolkits hide exactly those window-manager primitives.
- **Briefcase / Toga are disqualified, not merely worse.** Briefcase ships no Tk
  (proven); Toga's API cannot express an overlay (proven). Neither is a tuning
  problem.
- **Flet's headline feature doesn't fit.** Global keystroke capture is an
  OS-privilege operation (Quartz event taps / Win32 hooks / X11 XRecord); no
  focus-bound GUI event API substitutes for pynput. So Flet would cost a full
  Flutter rewrite to land in the same place (still using pynput) plus a heavier
  runtime and a pre-1.0, churning API.
- **Nuitka's advantages are moot here, its costs are measured.** Compiled-binary
  speed and source protection are irrelevant for a tiny, open-source overlay;
  meanwhile its build is ~21× slower (285.7 s vs 13.4 s), the bundle ~2× larger
  (78 MB vs 41 MB), and it crashes at runtime on this codebase's Pydantic usage
  without further workarounds. The runtime break was invisible to every
  doc/plugin/changelog check and only surfaced by running the real app.
- **PyInstaller was already half-adopted:** `types-pyinstaller` is in the `lint`
  dependency group and `pyinstaller` is a commented-out entry in `tool`.

## Consequences

- **Dependencies:** `pyinstaller` is pinned in the build jobs (`==6.16.0`,
  matching the `types-pyinstaller` dev pin). The build venv is separate from the
  dev environment, so it is not added to the `tool` dependency group.
- **Build recipe:** committed as `packaging/keycast.spec` + `packaging/entry.py`
  (windowed, bundle id `com.hasansezertasan.keycast`; no hidden imports needed).
  **One spec drives both platforms** — PyInstaller's `BUNDLE` is a no-op off
  macOS, so Windows stops at the `dist/keycast/` folder, which CI zips.
- **CI (new):** the release pipeline `release.yml` is a decomposed DAG —
  `build-package` / `build-macos` / `build-windows` (pure producers,
  `contents: read`) → `publish-pypi` (Trusted Publishing, `id-token` only) →
  `publish-release` (attach all artifacts + un-draft) → `reconcile`. It is
  **atomic**: `publish-pypi` needs all three builds, so a failed bundle blocks the
  PyPI release too (chosen so a version never ships with a missing artifact). The
  macOS/Windows builds **must** pin Astral `3.14.6` — Homebrew's `python@3.14`
  lacks `_tkinter` and Astral `3.14.3` has broken Tk, so an unpinned Python
  silently produces a Tk-less or crashing bundle. A `build-macos` build-only check
  also runs on every PR in `ci.yml`.
- **Tap (new cask):** `cask "keycast"` → release `.dmg` URL + `sha256`. Because
  the app is unsigned, the cask must document the Gatekeeper right-click→Open
  step (or an equivalent note); Homebrew discourages `quarantine` workarounds.
  The **formula stays** for CLI users.
- **Docs (DDD):** `docs/PACKAGING.md` is the operational contract (this ADR is
  the rationale). `tests/test_docs_contract.py` pins the API surface, not the
  pipeline, so it needs no change for this work.
- **Scope:** the **cask** is macOS-only, but the pipeline also produces a Windows
  `.zip` (PyInstaller) as a GitHub Release asset; Linux users install from PyPI.
  The cross-platform Python app and the PyPI/formula path are unaffected. macOS
  bundle is ~41 MB. (The Windows build, unverifiable locally, was validated green
  by CI in PR #3.)
- **Future / supersede triggers:** acquiring an Apple Developer account would add
  Developer-ID signing + notarization (removing the Gatekeeper friction) and
  should be recorded as a follow-up ADR superseding this one's "unsigned" stance.

### Validation limits

The smoke tests exercised the real composition root — Settings load, logging
setup, `DisplayWindow` construction with `overrideredirect`/`-alpha`/`-topmost`,
Tk window realization, and pynput backend import — but **not** a full interactive
session: `mainloop` was not entered and live global capture was not attempted
(it requires an Accessibility / Input-Monitoring grant). End-to-end verification
(`.dmg` install → Gatekeeper → permission grant → actual keystroke
visualization) on a clean Mac remains a manual step before first cask release.
