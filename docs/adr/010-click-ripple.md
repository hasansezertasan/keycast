# ADR-010: Mouse click ripple — prototyped, then removed pending redesign

## Status

**Reverted — deferred pending a redesign.** The click ripple was implemented as
part of the "Screencast Mode" work, shipped nowhere, and **removed before
release** because the current implementation has an **unresolved performance bug
that prevents proper usage** (input lag on macOS; see Context). This ADR records
what was built, why it was pulled, and the redesign that would be needed to bring
it back. The sibling features from the same work — **named presets** and
**chord grouping** — are unaffected and remain.

## Context

The goal was a *system-wide* equivalent of the click highlight found in VS Code's
Screencast Mode (a dot at the cursor) and in KeyCastr/Keyviz (a ring), aimed at
screencasters. See [COMPARISON.md](../COMPARISON.md).

### What was built

- A **second listener channel**, `ClickSink` (`Callable[[int, int], None]`),
  alongside the existing `TextSink`, because a click highlight needs the raw
  `(x, y)` a formatted string cannot carry. `MouseListener` gained a keyword-only
  `on_click_position` sink; `DisplayWindow.show_click` was the production sink.
- Per click, `DisplayWindow` created a **transient, borderless, always-on-top
  `Toplevel`** at the cursor and animated an expanding, fading ring on a `Canvas`
  via a self-rescheduling `after(16, …)` loop (~60 fps for ~400 ms), then
  destroyed it.
- `MouseSettings` gained `show_click_ripple`, `ripple_color`, `ripple_max_radius`,
  `ripple_duration_ms`; the `presenter` and `debug` presets enabled it.

### What went wrong

1. **Click-blocking (fixed).** The topmost ripple window intercepted the very
   click it was visualizing (Electron apps such as the Superset desktop app were
   victims). This *was* fixed by making the window click-through with native APIs
   Tk does not expose: `NSWindow.setIgnoresMouseEvents_(True)` on macOS (via
   pyobjc, finding the new window by diffing `NSApplication.windows()`) and the
   `WS_EX_TRANSPARENT | WS_EX_LAYERED` extended style on Windows.

2. **Input lag (UNRESOLVED — the reason for removal).** Even with click-through,
   the overlay felt laggy on macOS. The likely dominant cost is **creating and
   destroying a native window (`NSWindow`) on every click**, compounded by a
   synchronous `update_idletasks`, enumerating `NSApplication.windows()` twice per
   click, and ~25 frames of per-frame `attributes("-alpha")` (window-server
   compositing) — all on the Tk main loop, competing with keystroke rendering.
   This was *not* fully root-caused by profiling; regardless of which cost
   dominates, it is **inherent to the per-click-window architecture** and cannot
   be tuned away without a redesign.

3. **Background transparency (best-effort).** Getting only the ring to show
   (not a filled square) via `-transparent` / `-transparentcolor` is unreliable
   from Tk; separate from the lag but another rough edge.

## Decision

**Remove the click ripple entirely for now** rather than ship a feature whose
current implementation prevents expected use. Concretely: drop `show_click`, the
ripple animation/rendering, the `ClickSink` protocol, `MouseListener`'s
`on_click_position`, the four `MouseSettings.ripple*` fields, and the preset
enablement. Prefer removal + this ADR over shipping a known-broken, off-by-default
feature that invites bug reports.

Kept from the same work because they are independent and correct:

- **Named presets** and **chord grouping** (see [DESIGN_DECISIONS.md](../DESIGN_DECISIONS.md)).
- The `show_text`/`request_stop` **Tk-deadlock fix** (schedule `after` outside the
  lock) — unrelated to the ripple and a genuine bug fix.
- **Rounding fractional click coordinates** in `MouseListener._on_click` — added
  for the ripple but also fixes `show_mouse_position` rendering floats
  (`"(210.89453125, …)"`) on high-DPI displays.

## Root cause and path forward

The architecture is wrong: **one native window per click** is too expensive on
macOS for a 60 fps animation on the UI thread. A revival should:

- Use a **single persistent overlay** (created once, kept hidden/click-through and
  transparent) and *draw* ripples onto it, instead of creating a window per click
  — eliminating per-click window creation and the repeated `setIgnoresMouseEvents_`
  / window-enumeration work. A full-screen transparent click-through canvas is the
  usual shape (this is broadly how KeyCastr/Keyviz avoid the cost).
- Or step outside Tk for this one surface (a native/GPU-composited overlay), since
  Tk's `Canvas` + per-frame `-alpha` is a poor fit for smooth cursor-follow FX.
- Additionally: cap concurrent ripples, lower the frame rate, and profile to
  confirm the dominant cost before committing to an approach.

Until one of those is built and verified on macOS (where the lag was observed),
the ripple stays out.

## Consequences

- **API surface shrinks back:** `MouseListener(show_text, settings)` (no
  `on_click_position`), `DisplayWindow(settings)` (no ripple params), no
  `ClickSink`, no `show_click`. The `TextSink` single-channel design is restored.
- **Settings:** `MouseSettings` loses the four `ripple*`/`show_click_ripple`
  fields; existing configs that set them are ignored (`extra="ignore"`), so no
  breakage. Presets no longer reference them.
- **Docs updated:** README, API, DESIGN_DECISIONS, and COMPARISON reflect the
  removal and point here.
- **No user-facing loss** — the feature never shipped in a release.
