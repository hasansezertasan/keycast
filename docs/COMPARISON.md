# keycast vs. Alternatives

How keycast compares to other keystroke/mouse visualizers, and when you'd reach
for one over another. This is meant to be honest, not a sales pitch — keycast is
young (pre-1.0), and the mature tools below do some things better today.

> Competitor details are current as of **July 2026** and summarized from each
> project's own docs (linked at the bottom). Features change; verify against the
> upstream project before relying on a specific claim.

## TL;DR

- **keycast's niche**: a *system-wide*, *genuinely cross-platform* (macOS **and**
  Linux **and** Windows) visualizer that you install and configure like a normal
  Python package (`pip` / Homebrew / Scoop, JSON config). Its "Screencast Mode"
  presets, chord grouping, and click ripple are aimed at presenters and
  screencasters.
- **Pick KeyCastr** if you're macOS-only and want the most mature, batteries-
  included Mac experience.
- **Pick Keyviz** if you're on Windows/macOS and want the most polished visuals
  and animation controls out of the box.
- **Pick VS Code's Screencast Mode** if everything you demo happens *inside* VS
  Code — it's the only tool here that can show **semantic command names**
  ("Save File"), which keycast structurally cannot do system-wide (see below).

## Feature comparison

| | **keycast** | **KeyCastr** | **Keyviz** | **VS Code Screencast Mode** |
|---|---|---|---|---|
| Scope | System-wide | System-wide | System-wide | VS Code window only |
| macOS | ✅ | ✅ | ✅ | ✅ (in VS Code) |
| Linux | ✅ | ❌ | ❌ (driver limits) | ✅ (in VS Code) |
| Windows | ✅ | ❌ | ✅ | ✅ (in VS Code) |
| Keystroke overlay | ✅ | ✅ | ✅ | ✅ |
| Modifier/chord grouping | ✅ (`presenter`) | ✅ | ✅ | ✅ |
| **Semantic command names** | ❌ (see below) | ❌ | ❌ | ✅ |
| Mouse click highlight | ✅ (ripple) | ✅ (cursor ring) | ✅ | ✅ (click dot) |
| Mouse position / scroll | ✅ position · ❌ scroll | partial | ✅ scroll | ❌ |
| Fade / linger control | ✅ | ✅ | ✅ | ✅ (timeout) |
| Named presets ("modes") | ✅ | ❌ | ~ (styles) | ❌ |
| Config format | JSON (validated) | GUI prefs | GUI | `settings.json` |
| Password/secret masking | ❌ (not yet) | ✅ | ✅ (filters) | n/a |
| Language | Python | Objective-C | Dart/Flutter + C++ | TypeScript (built-in) |
| License | open source | open source | open source | bundled w/ VS Code |
| Maturity | young (0.x) | mature | mature | mature |

Legend: ✅ yes · ❌ no · ~ partial. keycast rows reflect the current feature set
(presets, chord grouping in `presenter`, click ripple, mouse position).

## The one thing keycast cannot do: semantic command names

VS Code's Screencast Mode can display **"Save File"** instead of **`⌘S`**. That
is its standout feature — and it's possible *only because VS Code owns its own
command dispatcher*, so it knows which command a shortcut invoked. It also only
works **inside VS Code**.

keycast (like KeyCastr and Keyviz) listens at the OS input layer (via `pynput`),
so it sees *every* app but only the *physical* keys — there is no system-wide way
to know that `⌘S` meant "Save File" in the frontmost app. So keycast's honest
ceiling is **pretty key labels + chord grouping** (`Command Left + S`), not
semantic names. This is a fundamental trade-off of system-wide capture, not a
missing feature we plan to add. See [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md)
("Chord Grouping").

## Per-tool notes

### KeyCastr (macOS only)
The de-facto standard on the Mac: open-source, mature, and well-loved. Shows
keystrokes in a customizable "lozenge" and mouse clicks as a ring around the
pointer (with an optional Magic Mouse visualizer), plus linger/fade controls,
drag-to-position, menu-bar toggle, and **password masking**. If you only ever
present on macOS, KeyCastr is the safe choice today. keycast's reason to exist
next to it is cross-platform reach and file-based, reproducible configuration.

### Keyviz (Windows + macOS)
A modern, very polished visualizer (Flutter UI) with rich styling, entry/exit
animations, input filtering, a visual history trail, and mouse click/scroll
indicators — all configured through a friendly GUI. **No Linux support** (upstream
cites driver limitations). Choose Keyviz for the best-looking output on Win/Mac;
choose keycast if you need Linux too, or prefer a scriptable JSON config and
package-manager installs over a GUI.

### VS Code Screencast Mode (in-editor only)
Built into VS Code (`Toggle Screencast Mode`). Highlights the cursor, shows
keystrokes, puts a dot where you click, and — uniquely — can show **command
names**. Configurable via `screencastMode.*` settings (font size, keyboard
overlay timeout, mouse indicator color/size, vertical offset, shortcut format).
Unbeatable *inside VS Code*; useless the moment your demo leaves the editor
(terminal, browser, another app) — which is exactly the gap keycast fills.

### Others
- **screenkey** (Linux, GTK/Python) — long-standing Linux keystroke display;
  X11-centric, limited mouse support.
- **Carnac** (Windows, .NET) — classic Windows keystroke visualizer; lightly
  maintained.
- **NohBoard** (Windows) — on-screen keyboard style, popular with gamers.

If you know of an alternative worth listing here, an issue/PR is welcome.

## When to choose keycast

Choose keycast when you want **one tool that behaves the same across macOS, Linux,
and Windows**, installed and pinned like any other package, with configuration
that lives in a file you can version-control and share with a team — and you're
comfortable with a young project still approaching 1.0. For a single-OS setup
where a mature, GUI-configured tool already covers you, KeyCastr (macOS) or Keyviz
(Win/Mac) may serve you better today.

## Sources

- [KeyCastr — GitHub](https://github.com/keycastr/keycastr) ·
  [TidBITS overview](https://tidbits.com/2025/03/03/appbits-visualize-clicks-and-keystrokes-with-keycastr/)
- [Keyviz — GitHub](https://github.com/mulaRahul/keyviz) ·
  [keyviz.org](https://keyviz.org/)
- [VS Code Screencast Mode — release notes](https://code.visualstudio.com/updates/v1_31) ·
  [command names issue #126713](https://github.com/microsoft/vscode/issues/126713)
