# ADR-015: Mask keystrokes typed into secure (password) fields

## Status

**Accepted.** Implemented for macOS; on by default
(`KeyboardSettings.mask_secure_input`). Windows and Linux are documented as
out of scope for now (no reliable signal). Raised as
[issue #44](https://github.com/hasansezertasan/keycast/issues/44) during PR #38
review, while comparing `presenter` mode to VS Code's Screencast Mode.

## Context

keycast renders *every* captured keystroke to the overlay. For a system-wide
presenter/screencast tool that means anything typed into a password field during
a live demo is shown on screen — and recorded. This is a **privacy/security
gap**, not a cosmetic one: the failure mode is leaking a credential on camera.
[COMPARISON.md](../COMPARISON.md) listed this as "❌ (not yet)" while both
**KeyCastr** and **Keyviz** ship secret masking.

The natural interception point is the single-sink boundary in
[`listeners.py`](../../src/keycast/listeners.py): `KeyListener._on_press` formats
each event before pushing it to the `TextSink`. Masking belongs there, so the
display layer stays unaware — consistent with the single-sink architecture (see
[ARCHITECTURE.md](../ARCHITECTURE.md)).

### Detecting "am I in a secure field" is platform-specific and uneven

- **macOS** — `IsSecureEventInputEnabled()` (Carbon/HIToolbox) reports when
  secure input mode is active, which is exactly what password fields (and Touch
  ID prompts) trigger. It needs no prompt or entitlement. This is the *same* OS
  mechanism that causes pynput to miss release events in those windows — the
  reason `listeners.py` already has stale-modifier eviction
  (`_evict_stale_modifiers`, `_MODIFIER_STALE_SECONDS`). keycast already contends
  with secure input; masking is its intentional use. Cleanest of the three.
- **Windows** — no direct global "secure field" flag; would need
  focused-window/control-class heuristics or accept partial coverage.
- **Linux/X11** — no reliable global signal; out of scope initially.

## Decision

Add `KeyboardSettings.mask_secure_input` (default **`true`**). When set,
`KeyListener._on_press` drops the keystroke while the OS reports secure input is
active, **before** the key is formatted, held as a chord modifier, or handed to
the sink. Detection lives in a new dependency-light module,
[`secure_input.py`](../../src/keycast/secure_input.py), whose
`is_secure_input_active()` loads `IsSecureEventInputEnabled` via `ctypes`,
mirroring the existing macOS permission probe in `application.py`
(`_read_macos_permission`): resolve the symbol once (cached), pin
`restype`/`argtypes`, and degrade to `False` on any failure.

### Decisions within the decision

1. **Full suppression, not a `••••` glyph.** Emitting a mask glyph still leaks
   password *length* and typing *cadence* (a minor side channel) and adds display
   complexity for no real gain. Emitting nothing leaks strictly less and is
   simpler. The overlay simply shows no new event while typing is masked.
2. **On by default.** A leaked password is worse than a missed keystroke, so the
   safe default is masking. Users who genuinely want to demo typing into a
   password field set `mask_secure_input: false`.
3. **Fail open, not closed.** When the signal cannot be read — every non-macOS
   host, or a framework/symbol failure on macOS — capture continues normally
   rather than blanking the overlay. Failing *closed* would suppress everything
   and read as a broken app. The cost is that masking is **best-effort, not a
   guarantee**, which is documented honestly.
4. **Check ahead of chord state.** A modifier pressed inside a secure field must
   not be stashed in `_held_modifiers`, or the next visible key (after secure
   input clears) would be fabricated into a phantom `Control + x` chord. The mask
   short-circuits before chord handling.
5. **Injectable probe.** `KeyListener` takes a keyword-only `is_secure_input`
   argument (defaults to the real macOS probe) so tests drive masking
   deterministically without a real secure field — matching the existing
   sink-injection testing pattern.

## Alternatives considered

- **Cross-platform coverage now.** Deferred: Windows would need brittle
  focused-window heuristics and Linux/X11 has no reliable signal. Shipping macOS
  well beats shipping all three half-working (cf. the
  remove-plus-ADR precedent in [ADR-012](012-click-ripple.md)).
- **Manual "pause capture" hotkey** as a cross-platform floor. Considered as a
  companion escape hatch for platforms without auto-detection, and explicitly
  **deferred** to a separate change to keep this one focused. It remains the
  obvious follow-up for Windows/Linux coverage.
- **Mask glyph instead of suppression.** Rejected — see decision 1.

## Consequences

- **New module + setting:** `keycast.secure_input` and
  `KeyboardSettings.mask_secure_input`. `KeyListener.__init__` gains a
  keyword-only `is_secure_input` seam; its positional signature
  (`show_text`, `settings`) is unchanged, so the docs-contract stays intact.
- **macOS users** get password masking by default; **Windows/Linux users** get a
  no-op flag today (documented), with the manual-pause hotkey as the future floor.
- **Docs updated** (DDD contract): README, API, ARCHITECTURE, DESIGN_DECISIONS,
  and the COMPARISON row flip from "❌ (not yet)" to "~ (✅ macOS · ❌ Win/Linux)".
- **Best-effort, not a guarantee.** If macOS ever changes the API, or on any
  platform without the signal, credentials could still be shown — the feature
  reduces risk, it does not eliminate it.
