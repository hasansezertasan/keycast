---
priority: high
---

# Package structure

Flat modules under `src/keycast/`, plus one `updates/` subpackage. There is no
`core/` / `utils/` / `cli/` / `gui/` package tree, and no import-linter contract
(the layout predates the template's layered convention).

| Module | Role |
| ------ | ---- |
| `application.py` | `Keycast` composition root — the ONLY place that wires components (settings → logging → window → listeners) |
| `main.py`, `cli.py`, `__main__.py` | Thin entry points. `keycast.cli:app` is the console script; `python -m keycast` runs `main()` |
| `listeners.py` | `KeyListener` / `MouseListener`: pynput threads format each event into one display string and push it to a `TextSink` (`Callable[[str], None]`). They know nothing about the display |
| `display.py` | `DisplayWindow`: the Tk overlay, the production sink (`show_text` marshals onto the Tk loop via `root.after`) |
| `settings.py` | Pydantic settings loaded from JSON ONLY (`~/.keycast/config.json`) — constructor kwargs and env vars are ignored. Never `Settings(display=...)`; patch the JSON source in tests |
| `logging_setup.py` | Rotating-file logging setup (defaults to `~/.keycast/main.log`) |
| `secure_input.py` | macOS secure-input masking probe (best-effort, macOS-only) |
| `updates/` | Install-source-aware update check (notify only): `sources` (how installed), `versions` (GitHub fetch + compare), `state` (once-a-day throttle), `__init__` orchestration |

Design rules that must survive every change:

- **Single-sink event flow.** Mouse position is formatted *into* the string so the
  sink signature stays uniform; tests pass `list.append` as the sink.
- **Threading & shutdown are subtle.** Listeners run on pynput threads; the fade
  timer is a self-rescheduling `root.after(100, ...)` (no separate thread).
  Shutdown is two-phase: `request_stop()` (any thread) schedules `root.quit`;
  `stop()` runs on the main thread after `mainloop` returns and destroys the
  window. Never destroy the window from inside `mainloop` (Tcl errors).
- **Degrade, don't crash.** Input-capture code catches broadly by design
  (`except Exception` + multi-statement `try` blocks are the error policy, see
  the `BLE001`/`PLW0717` per-file-ignores in `pyproject.toml`); a listener
  failure must never take down the overlay. Narrow a handler only when you can
  prove the failure set.
- **Lazy imports are load-bearing.** `tkinter` stays function-local
  (`PLC0415`), and the `cli.py` subcommands import the GUI chain lazily, so
  `--help`, `version`, and `info` never pay for the GUI toolkit. `pynput` is
  the exception, not the rule: `listeners.py` imports it at module scope, so
  anything importing the listener chain (tests, Sphinx autodoc, a bare
  `python -m keycast`) needs a display — CI and the dev container provide
  Xvfb for exactly this. Sphinx autodoc is the other exception: the three
  names it renders (`types`, `DisplaySettings`, `LoggingSettings`) are runtime
  imports with `noqa: TC001/TC003` — moving them back under `TYPE_CHECKING`
  breaks the docs build.
