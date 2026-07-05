# keycast API Documentation

## Overview

This document provides detailed API documentation for the keycast application, including all public classes, methods, and their usage.

## Package Structure

```
src/keycast/
├── __init__.py          # Package initialization
├── __main__.py          # `python -m keycast` entry point (internal)
├── application.py       # Keycast application orchestrator
├── cli.py               # Typer CLI entry point (internal)
├── main.py              # Application entry point (main())
├── display.py           # Tkinter overlay window (DisplayWindow)
├── listeners.py         # Input event listeners + TextSink protocol
├── settings.py          # Pydantic settings configuration
└── logging_setup.py     # Logging configuration
```

> `cli.py` and `__main__.py` are entry points, not a stable public API. They
> wire the package up for the `keycast` console script and `python -m keycast`
> respectively, and may change without notice. Program against `Keycast`,
> `DisplayWindow`, the listeners, and the settings classes instead.

## Architecture at a Glance

Input events flow through a single text sink:

```
KeyListener  ─┐
              ├─►  show_text(text: str)   ─►  DisplayWindow  (Tk overlay)
MouseListener ┤        (TextSink)
              └─►  show_click(x, y)       ─►  DisplayWindow  (click ripple)
                       (ClickSink, optional)
```

Each listener formats an event into a single display string and hands it to a
`TextSink` callable. `DisplayWindow.show_text` is the production sink; it
marshals the update onto the Tk main loop because listeners invoke the sink
from pynput listener threads. The mouse listener additionally has an optional
second channel — a `ClickSink` (`DisplayWindow.show_click`) carrying the raw
`(x, y)` — used only when the click ripple is enabled. The `Keycast` class in
`application.py` wires these components together and owns the application
lifecycle.

## Core Classes

### Keycast

**Location**: `keycast.application.Keycast`

**Purpose**: Application orchestrator. Loads settings, configures logging, and
wires the display window and listeners together, then owns their lifecycle.

#### Constructor

```python
def __init__(self) -> None
```

Takes no arguments. It loads settings via `Settings.create_settings_file()`,
calls `setup_logging`, and constructs the `DisplayWindow`, `MouseListener`, and
`KeyListener`, connecting each listener's `show_text` to the window.

#### Methods

##### start() -> None

Starts the mouse and keyboard listeners, then starts the display window last
(its `start()` blocks on the Tk main loop). Prefer `run()` for normal use.

##### stop() -> None

Stops all components. Idempotent and best-effort: a failure stopping one
component is logged and does not prevent the others from being stopped. Safe to
call from a signal handler and again from `run()`'s `finally` block.

##### run() -> None

Installs `SIGINT`/`SIGTERM` handlers, calls `start()`, and guarantees `stop()`
runs on exit. This is the normal entry point for embedding keycast.

**Example**:
```python
from keycast.application import Keycast

app = Keycast()
app.run()  # Blocks until the window closes or a shutdown signal arrives
```

### DisplayWindow

**Location**: `keycast.display.DisplayWindow`

**Purpose**: Manages the transparent overlay window that displays keystrokes and
mouse clicks. Implements the `TextSink` protocol via its `show_text` method.

#### Constructor

```python
def __init__(
    self,
    settings: DisplaySettings,
    *,
    ripple_color: Color | str = "yellow",
    ripple_max_radius: int = 40,
    ripple_duration_ms: int = 400,
) -> None
```

**Parameters**:
- `settings` (DisplaySettings): Display configuration settings object
- `ripple_color` / `ripple_max_radius` / `ripple_duration_ms` (keyword-only): Appearance of the click ripple drawn by `show_click`. The `Keycast` orchestrator sources these from `MouseSettings` (`ripple_color`, `ripple_max_radius`, `ripple_duration_ms`) so the ripple's look is configured in the mouse section. They are ignored unless something calls `show_click`.

**DisplaySettings Properties**:
- `width` (int): Window width in pixels (default: 400, range: 100-2000)
- `height` (int): Window height in pixels (default: 100, range: 50-1000)
- `x_position` (Literal["center"] | int): X position in pixels, or "center" to center horizontally (default: "center")
- `y_position` (int): Y position from top (default: 50)
- `background_color` (Color): Background color (default: "black")
- `text_color` (Color): Text color (default: "white")
- `font_family` (str): Font family name (default: "Arial")
- `font_size` (int): Font size in points (default: 16, range: 8-72)
- `font_weight` (Literal["normal", "bold"]): Font weight (default: "bold")
- `alpha` (float): Window transparency (default: 0.8, range: 0.1-1.0)
- `always_on_top` (bool): Whether window stays on top (default: True)
- `draggable` (bool): Allow repositioning the overlay by dragging it with the mouse (default: False). The window has no title bar, so dragging is bound directly on the overlay surface.
- `fade_duration_ms` (int): How long events stay visible in milliseconds (default: 2000, range: 500-10000)
- `max_events` (int): Maximum number of events to display (default: 5, range: 1-20)

#### Methods

##### show_text(text: str) -> None

Displays a single line of text in the overlay window. This is the `TextSink`
implementation the listeners call. It is **thread-safe**: it may be called from
a pynput listener thread and marshals the actual widget update onto the Tk main
loop via `root.after`.

**Parameters**:
- `text` (str): The text to display (already formatted by the caller)

**Example**:
```python
from keycast.settings import DisplaySettings

settings = DisplaySettings()
window = DisplayWindow(settings)
window.show_text("A")
window.show_text("Left Click (100, 200)")
```

##### show_click(x: int, y: int) -> None

Paints a short expanding, fading ring centered at screen position `(x, y)` — the
production `ClickSink`. Like `show_text`, it is **thread-safe**: it may be called
from a pynput listener thread and marshals the actual rendering onto the Tk main
loop via `root.after`. The ripple is drawn in its own transient, always-on-top,
borderless window that tears itself down when the animation completes. The window
is made **click-through** so it never intercepts the click it visualizes
(`NSWindow.setIgnoresMouseEvents_` on macOS via pyobjc, `WS_EX_TRANSPARENT` on
Windows; best-effort elsewhere). Background transparency is separately best-effort
per platform, and any rendering error is logged (throttled) rather than raised.

**Parameters**:
- `x` (int): Click x-coordinate (screen pixels)
- `y` (int): Click y-coordinate (screen pixels)

##### start() -> None

Starts the Tk main loop. This method **blocks** until the window is closed and
must be called on the main thread.

##### request_stop() -> None

Asks the main loop to exit. Safe to call from any thread (including a signal
handler); it schedules `root.quit` on the Tk event loop so `start()` returns.
The actual teardown happens later in `stop()`.

##### stop() -> None

Destroys the window and releases resources. Must run on the main thread after
`start()` has returned.

#### Properties

- `settings` (DisplaySettings): Display configuration settings
- `root` (tk.Tk | None): Tkinter root window
- `label` (tk.Label | None): Tkinter label for displaying events
- `events` (list[tuple[str, float]]): List of (event_text, timestamp) tuples

### TextSink

**Location**: `keycast.listeners.TextSink`

**Purpose**: A `typing.Protocol` describing any callable that displays a single
line of text. Listeners depend on this protocol rather than on `DisplayWindow`,
which decouples input capture from rendering.

```python
class TextSink(Protocol):
    def __call__(self, text: str) -> None: ...
```

Any `Callable[[str], None]` satisfies it — `DisplayWindow.show_text`, a `print`
wrapper, a test double, etc.

> **Threading contract**: listeners invoke the sink on a **pynput listener
> thread**, not the main thread. A sink that touches a GUI toolkit must marshal
> the work onto its own UI thread (as `DisplayWindow.show_text` does).

### ClickSink

**Location**: `keycast.listeners.ClickSink`

**Purpose**: A `typing.Protocol` describing a callable that receives the raw
`(x, y)` position of a mouse click. This is the second, optional listener channel
(alongside `TextSink`), used to drive the click ripple with real coordinates that
a formatted string can't carry. `DisplayWindow.show_click` is the production
implementation.

```python
class ClickSink(Protocol):
    def __call__(self, x: int, y: int) -> None: ...
```

Any `Callable[[int, int], None]` satisfies it. The same pynput-thread threading
contract as `TextSink` applies: a GUI implementation must marshal onto its own UI
thread (as `DisplayWindow.show_click` does).

### KeyListener

**Location**: `keycast.listeners.KeyListener`

**Purpose**: Captures keyboard input, formats each key into a display string,
and passes it to a `TextSink`.

#### Constructor

```python
def __init__(self, show_text: TextSink, settings: KeyboardSettings) -> None
```

**Parameters**:
- `show_text` (TextSink): Sink invoked with the formatted label each time a key is pressed
- `settings` (KeyboardSettings): Keyboard configuration settings object

**KeyboardSettings Properties**:
- `enabled` (bool): Whether the keyboard listener runs (default: True)
- `show_modifier_keys` (bool): Whether to show modifier keys (Ctrl, Alt, etc.) (default: True)
- `show_function_keys` (bool): Whether to show function keys (F1, F2, etc.) (default: True)
- `show_special_keys` (bool): Whether to show special keys (Enter, Space, etc.) (default: True)
- `group_chords` (bool): Whether to combine a key pressed with held modifiers into one chord label, e.g. `"Control Left + S"` (default: False). See Chord Grouping below.
- `chord_separator` (str): String joining the parts of a grouped chord (default: `" + "`, min length 1).
- `key_mappings` (dict[str, str]): Custom key name mappings. Keys are pynput key names with the "Key." prefix removed (e.g. "ctrl_l", "space"). Ships cross-platform defaults for the modifier, space and enter keys.

**Example**:
```python
from keycast.listeners import KeyListener
from keycast.settings import KeyboardSettings

def on_key(text: str) -> None:
    print(f"Key pressed: {text}")

settings = KeyboardSettings(
    show_modifier_keys=True,
    show_function_keys=False,
    key_mappings={"ctrl_l": "Left Ctrl"},
)
listener = KeyListener(show_text=on_key, settings=settings)
```

#### Methods

##### start() -> None

Starts the keyboard listener (non-blocking; pynput runs it on its own thread).

##### stop() -> None

Stops the keyboard listener.

```python
from keycast.listeners import KeyListener
from keycast.settings import KeyboardSettings

listener = KeyListener(show_text=print, settings=KeyboardSettings())
listener.start()
# ... later ...
listener.stop()
```

#### Key Formatting

The KeyListener formats each key, then applies any `key_mappings` override. The
default labels (from `_default_key_mappings`) are:

- **Character Keys**: shown exactly as typed — the character itself, e.g. `"a"`,
  `"B"` (only uppercase when Shift produced an uppercase char), `"1"`. They are
  **not** force-uppercased.
- **Modifier Keys**: `"Control Left"` / `"Control Right"`, `"Alt Left"` /
  `"Alt Right"`, `"Shift Left"` / `"Shift Right"`
- **Super / Command / Windows Key**: labeled per platform — `"Command Left/Right"`
  on macOS, `"Windows Left/Right"` on Windows, `"Super Left/Right"` elsewhere
- **Space / Enter**: `"Space Bar"` and `"Enter"`
- **Other Special Keys** (no default mapping): the capitalized pynput name, e.g.
  `"Tab"`, `"Backspace"`, `"Delete"`, `"Esc"`
- **Function Keys**: `"F1"`, `"F2"`, … (capitalized pynput name)
- **Arrow Keys**: `"Up"`, `"Down"`, `"Left"`, `"Right"`

Any of these can be overridden via `KeyboardSettings.key_mappings` (keyed by the
pynput key name with the `Key.` prefix removed).

#### Custom Key Mappings

You can provide custom key name mappings:

```python
from keycast.listeners import KeyListener
from keycast.settings import KeyboardSettings

key_mappings = {
    "ctrl_l": "Left Ctrl",
    "ctrl_r": "Right Ctrl",
    "alt_l": "Left Alt",
    "alt_r": "Right Alt",
    "space": "Space Bar",
}

settings = KeyboardSettings(key_mappings=key_mappings)
listener = KeyListener(show_text=print, settings=settings)
```

Keys must be bare pynput key names — lowercase, with no `Key.` prefix (e.g.
`ctrl_l`, `space`, `f1`). A key that carries the prefix or is capitalized can
never match and is rejected at config load rather than silently doing nothing.

#### Chord Grouping

When `group_chords` is `true`, `KeyListener` combines a key pressed while one or
more modifiers are held into a **single** chord label rather than emitting the
modifier and the key as separate events:

- Modifier presses are **held silently** while `group_chords` is on.
- Pressing a non-modifier key while modifiers are held emits one label joining the
  held modifier labels and the key, in press order, using `chord_separator`
  (default `" + "`) — e.g. `"Control Left + Shift Left + S"`. The chord always
  includes its modifiers, even if `show_modifier_keys` is `false` (a chord without
  its modifiers would be meaningless).
- A modifier **pressed and released on its own** (no other key during the hold) is
  emitted alone on release, subject to `show_modifier_keys`. When several modifiers
  are held and released without completing a chord, each is emitted on its own
  release.

`group_chords` defaults to `false` (each key is emitted as its own event, the
original behavior). The `presenter` preset enables it. Implementation note: this
is the one place `KeyListener` registers pynput's `on_release` — it needs release
events to track which modifiers are currently held.

### MouseListener

**Location**: `keycast.listeners.MouseListener`

**Purpose**: Captures mouse clicks, formats each into a display string, and
passes it to a `TextSink`.

#### Constructor

```python
def __init__(
    self,
    show_text: TextSink,
    settings: MouseSettings,
    *,
    on_click_position: ClickSink | None = None,
) -> None
```

**Parameters**:
- `show_text` (TextSink): Sink invoked with the formatted label each time the mouse is clicked
- `settings` (MouseSettings): Mouse configuration settings object
- `on_click_position` (ClickSink | None, keyword-only): Optional second sink invoked with the raw `(x, y)` of each click, used to drive the click ripple. Only wired up when `settings.show_click_ripple` is true. `DisplayWindow.show_click` is the production `ClickSink`.

> The text sink receives a **single string**. When `show_mouse_position` is
> enabled, the coordinates are formatted directly into that string (e.g.
> `"Left Click (100, 200)"`) — the text sink is not passed separate `x`/`y`
> arguments. The raw coordinates instead flow through the separate, optional
> `on_click_position` (`ClickSink`) channel.

**MouseSettings Properties**:
- `enabled` (bool): Whether the mouse listener runs (default: True)
- `show_mouse_clicks` (bool): Whether to show mouse clicks (default: True)
- `show_mouse_position` (bool): Whether to append the click position to the label (default: False)
- `show_click_ripple` (bool): Whether each click paints an expanding, fading ring at the cursor (default: False). Independent of `show_mouse_clicks`.
- `ripple_color` (Color): Ring color (default: "yellow")
- `ripple_max_radius` (int): Final ring radius in pixels (default: 40, range: 5-200)
- `ripple_duration_ms` (int): How long the ring animates in milliseconds (default: 400, range: 100-2000)
- `button_names` (dict[str, str]): Custom button name mappings (default: {})

> `show_mouse_position` only takes effect alongside `show_mouse_clicks` (the
> position is appended to the click label). Setting `show_mouse_position=True`
> with `show_mouse_clicks=False` is rejected at load time rather than silently
> doing nothing.

**Example**:
```python
from keycast.listeners import MouseListener
from keycast.settings import MouseSettings

def on_click(text: str) -> None:
    print(f"Mouse click: {text}")

settings = MouseSettings(show_mouse_clicks=True, show_mouse_position=True)
listener = MouseListener(show_text=on_click, settings=settings)
```

#### Methods

##### start() -> None

Starts the mouse listener (non-blocking; pynput runs it on its own thread).

##### stop() -> None

Stops the mouse listener.

#### Button Formatting

The MouseListener automatically formats mouse buttons:

- **Left Click**: "Left Click"
- **Right Click**: "Right Click"
- **Middle Click**: "Middle Click"
- **Other Buttons**: "Button_name Click"

When `show_mouse_position` is true, ` (x, y)` is appended to the label.

#### Custom Button Mappings

You can provide custom button name mappings (keyed by pynput's `Button.<name>`
string):

```python
from keycast.listeners import MouseListener
from keycast.settings import MouseSettings

button_names = {
    "Button.left": "LMB",
    "Button.right": "RMB",
    "Button.middle": "MMB",
}

settings = MouseSettings(button_names=button_names)
listener = MouseListener(show_text=print, settings=settings)
```

Keys must be full pynput button strings starting with `Button.` (e.g.
`Button.left`). A key without that prefix can never match and is rejected at
config load.

## Settings Classes

### Settings

**Location**: `keycast.settings.Settings`

**Purpose**: Main settings class for the keycast application using Pydantic for validation.

#### Construction

Settings are normally loaded via the `create_settings_file` classmethod rather
than constructed directly, so the on-disk config file is created/validated:

```python
def create_settings_file(cls) -> Settings
```

**Properties**:
- `display` (DisplaySettings): Display window settings
- `keyboard` (KeyboardSettings): Keyboard listener settings (use `keyboard.enabled` to toggle the keyboard listener)
- `mouse` (MouseSettings): Mouse listener settings (use `mouse.enabled` to toggle the mouse listener)
- `logging` (LoggingSettings): Logging settings
- `debug` (bool): Enable debug mode for verbose diagnostics (default: `false`). A top-level flag, not a section; see `effective_logging` for how it combines with `logging.level`.
- `start_minimized` (bool): Start with the overlay hidden; it appears the first time a key or click is captured (default: `false`). Requires `auto_start` (rejected with it off, since nothing would ever re-show the overlay). If no listener is live at startup (all disabled, or all fail to start), the overlay is kept visible instead of hidden.
- `auto_start` (bool): Start the input listeners on launch (default: `true`). When `false`, no listeners start regardless of `keyboard.enabled` / `mouse.enabled` — an app-level master switch.
- `check_for_updates` (bool): Gate the automatic update check (default: `true`). When `true`, keycast queries the GitHub Releases API at most once per day and shows a non-blocking notice if a newer version exists; `false` disables all automatic checks. Throttle state lives in `~/.keycast/update-check.json`, not on `Settings`. See `keycast.updates` and [ADR-002](adr/002-update-check.md).
- `preset` (Literal["custom", "presenter", "minimal", "debug"]): Named settings bundle layered over the config on load (default: `"custom"`). `"custom"` uses the file verbatim; the other presets override a handful of fields for common scenarios (see `resolve_preset` and the table below). A preset wins over the file **only for the fields it names**; everything else keeps its configured value.

> The application version is exposed as `keycast.__version__`, generated at
> build time from the git tag by hatch-vcs (into `src/keycast/_version.py`),
> not stored on `Settings`.

#### Methods

##### create_settings_file() -> Settings

Loads settings, creating the settings file from defaults if it doesn't exist.
A malformed config file is backed up to a timestamped `config.json.<epoch>.bak`
(never overwriting a previous backup) and defaults are used.
This is a classmethod that returns the loaded `Settings` instance.

**Example**:
```python
from keycast.settings import Settings

settings = Settings.create_settings_file()  # Creates ~/.keycast/config.json on first run
```

##### effective_logging() -> LoggingSettings

Returns the `LoggingSettings` actually applied at startup, resolving the `debug`
flag against `logging.level`. `Keycast.__init__` passes the result to
`setup_logging`. When `debug` is off, the configured `logging` is used unchanged.

##### resolve_preset() -> Settings

Returns the `Settings` to actually apply, with the selected `preset`'s overrides
layered on top of the loaded config. `Keycast.__init__` calls this right after
`create_settings_file()`, so every component sees the resolved settings; the
on-disk config file is unaffected (it keeps the raw values plus the `preset`
name). When `preset` is `"custom"` the settings are returned unchanged.

Each overridden section is rebuilt through its own `model_validate` (with the
preset's fields merged over the current values) and the results are assembled with
`model_copy`, so the merged sections are re-validated against every field bound and
cross-field validator — a preset can never yield invalid settings. The built-in
presets:

| Preset | Overrides |
| --- | --- |
| `custom` | none — the config file is used verbatim (default) |
| `presenter` | `display.font_size=28`, `display.fade_duration_ms=3000`, `display.max_events=3`, `display.alpha=0.9`, `mouse.show_mouse_clicks=true` |
| `minimal` | `display.font_size=12`, `display.fade_duration_ms=1000`, `display.max_events=1`, `display.alpha=0.6` |
| `debug` | `debug=true`, `display.max_events=10`, `display.fade_duration_ms=5000`, `mouse.show_mouse_clicks=true`, `mouse.show_mouse_position=true` |

```python
from keycast.settings import Settings

settings = Settings.create_settings_file().resolve_preset()
```

### DisplaySettings

**Location**: `keycast.settings.DisplaySettings`

**Purpose**: Display window configuration settings with validation.

**Properties**:
- `width` (int): Window width in pixels (default: 400, range: 100-2000)
- `height` (int): Window height in pixels (default: 100, range: 50-1000)
- `x_position` (Literal["center"] | int): X position in pixels, or "center" to center horizontally (default: "center")
- `y_position` (int): Y position from top (default: 50)
- `background_color` (Color): Background color (default: "black")
- `text_color` (Color): Text color (default: "white")
- `font_family` (str): Font family name (default: "Arial")
- `font_size` (int): Font size in points (default: 16, range: 8-72)
- `font_weight` (Literal["normal", "bold"]): Font weight (default: "bold")
- `alpha` (float): Window transparency (default: 0.8, range: 0.1-1.0)
- `always_on_top` (bool): Whether window stays on top (default: True)
- `draggable` (bool): Allow repositioning the overlay by dragging it with the mouse (default: False). The window has no title bar, so dragging is bound directly on the overlay surface.
- `fade_duration_ms` (int): How long events stay visible in milliseconds (default: 2000, range: 500-10000)
- `max_events` (int): Maximum number of events to display (default: 5, range: 1-20)

### KeyboardSettings

**Location**: `keycast.settings.KeyboardSettings`

**Purpose**: Keyboard listener configuration settings.

**Properties**:
- `enabled` (bool): Whether the keyboard listener runs (default: True)
- `show_modifier_keys` (bool): Whether to show modifier keys (Ctrl, Alt, etc.) (default: True)
- `show_function_keys` (bool): Whether to show function keys (F1, F2, etc.) (default: True)
- `show_special_keys` (bool): Whether to show special keys (Enter, Space, etc.) (default: True)
- `group_chords` (bool): Combine a key pressed with held modifiers into one chord label (default: False). See Chord Grouping under `KeyListener`.
- `chord_separator` (str): String joining the parts of a grouped chord (default: `" + "`, min length 1).
- `key_mappings` (dict[str, str]): Custom key name mappings. Keys are pynput key names with the "Key." prefix removed (e.g. "ctrl_l", "space"). Ships cross-platform defaults for the modifier, space and enter keys.

### MouseSettings

**Location**: `keycast.settings.MouseSettings`

**Purpose**: Mouse listener configuration settings.

**Properties**:
- `enabled` (bool): Whether the mouse listener runs (default: True)
- `show_mouse_clicks` (bool): Whether to show mouse clicks (default: True)
- `show_mouse_position` (bool): Whether to append the click position coordinates to the label (default: False). Requires `show_mouse_clicks`; the combination `show_mouse_position=True, show_mouse_clicks=False` is rejected at load time (it would otherwise render nothing).
- `show_click_ripple` (bool): Whether each click paints an expanding, fading ring at the cursor (default: False). Independent of `show_mouse_clicks` — the ripple is a separate visual channel via `on_click_position`.
- `ripple_color` (Color): Ring color (default: "yellow")
- `ripple_max_radius` (int): Final ring radius in pixels (default: 40, range: 5-200)
- `ripple_duration_ms` (int): How long the ring animates in milliseconds (default: 400, range: 100-2000)
- `button_names` (dict[str, str]): Custom button name mappings (default: {})

### LoggingSettings

**Location**: `keycast.settings.LoggingSettings`

**Purpose**: Logging configuration settings.

**Properties**:
- `level` (Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]): Logging level (default: "INFO")
- `format` (str): Log message format (default: "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
- `file_path` (Path | None): Log file path; `None` disables file logging (console only). **Default: `~/.keycast/main.log`** (file logging is on by default, with size-based rotation)
- `max_file_size_mb` (int): Maximum log file size in MB before rotation (default: 10, range: 1-100)
- `backup_count` (int): Number of rotated log files to keep (default: 5, range: 0-20)

## Module Functions

### setup_logging(settings: LoggingSettings) -> None

**Location**: `keycast.logging_setup.setup_logging`

**Purpose**: Sets up logging configuration for the application.

**Parameters**:
- `settings` (LoggingSettings): Logging configuration settings object

**Example**:
```python
from keycast.logging_setup import setup_logging
from keycast.settings import LoggingSettings

settings = LoggingSettings(level="DEBUG")
setup_logging(settings)  # Enable debug logging
```

### main() -> None

**Location**: `keycast.main.main`

**Purpose**: Application entry point. Constructs a `Keycast` instance and calls
`run()`. The orchestration logic lives in `Keycast`, not here.

**Example**:
```python
from keycast.main import main

if __name__ == "__main__":
    main()
```

## Usage Examples

### Basic Usage (recommended)

Let the `Keycast` orchestrator load settings and own the lifecycle:

```python
from keycast.application import Keycast

Keycast().run()  # Blocks until the window closes or a shutdown signal arrives
```

### Manual Wiring

Wire the components yourself when you need a custom composition root. Note the
start order — listeners first, the blocking window last — and that every
listener shares the window's `show_text` sink:

```python
from keycast.display import DisplayWindow
from keycast.listeners import KeyListener, MouseListener
from keycast.settings import Settings

# resolve_preset() applies the selected preset ("modes"); it is a no-op for the
# default "custom" preset. The Keycast orchestrator does this for you.
settings = Settings.create_settings_file().resolve_preset()

window = DisplayWindow(settings.display)
key_listener = KeyListener(show_text=window.show_text, settings=settings.keyboard)
mouse_listener = MouseListener(show_text=window.show_text, settings=settings.mouse)

key_listener.start()
mouse_listener.start()
window.start()  # Blocks until the window is closed
```

### Custom Sink

Any `Callable[[str], None]` is a valid `TextSink`, so you can route events
anywhere — a logger, a queue, or a test double:

```python
from keycast.listeners import KeyListener, MouseListener
from keycast.settings import KeyboardSettings, MouseSettings

def sink(text: str) -> None:
    # Filter, transform, or forward events however you like. Labels match what
    # the listener emits (e.g. "Control Left", "Space Bar"); see Key Formatting.
    if not text.endswith(("Left", "Right")):  # skip modifier keys
        print(f"event: {text}")

key_listener = KeyListener(show_text=sink, settings=KeyboardSettings())
mouse_listener = MouseListener(show_text=sink, settings=MouseSettings())
```

### Advanced Configuration

```python
from keycast.display import DisplayWindow
from keycast.settings import DisplaySettings

display_settings = DisplaySettings(
    width=600,
    height=200,
    x_position=100,
    y_position=100,
    background_color="darkgray",
    text_color="white",
    font_family="Consolas",
    font_size=18,
    font_weight="normal",
    alpha=0.9,
    always_on_top=True,
    fade_duration_ms=3000,
    max_events=10,
)
window = DisplayWindow(display_settings)
```

## Error Handling

### Common Exceptions

#### Permission Errors

On macOS, you may encounter permission errors when starting a listener:

```python
from keycast.listeners import KeyListener
from keycast.settings import KeyboardSettings

try:
    listener = KeyListener(show_text=print, settings=KeyboardSettings())
    listener.start()
except Exception as e:
    print(f"Permission error: {e}")
    print("Please grant accessibility permissions in System Settings")
```

Per-keystroke and per-click callback errors are caught inside the listeners and
logged through a throttler, so a misbehaving sink will not spam the logs or
crash the listener thread.

#### Display Errors

Tkinter may fail to initialize in some environments:

```python
from keycast.display import DisplayWindow
from keycast.settings import DisplaySettings

try:
    window = DisplayWindow(DisplaySettings())
except Exception as e:
    print(f"Display error: {e}")
    print("Tkinter may not be available in this environment")
```

### Graceful Shutdown

`Keycast.run()` already installs `SIGINT`/`SIGTERM` handlers and guarantees
`stop()` runs on exit, so prefer it for lifecycle management. If you wire
components manually, request the loop to exit from your handler and tear down
after `start()` returns:

```python
import signal

# `window`, `key_listener`, `mouse_listener` created as in "Manual Wiring".
def handler(signum, frame):
    # request_stop is thread/handler-safe; it only asks the loop to exit.
    window.request_stop()

signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)

try:
    key_listener.start()
    mouse_listener.start()
    window.start()  # Returns once request_stop() fires.
finally:
    key_listener.stop()
    mouse_listener.stop()
    window.stop()  # Main-thread teardown, after the loop has returned.
```

## Threading Considerations

### Thread Safety

- **Listeners run on their own threads**: pynput delivers key/click events on
  background threads, so the `TextSink` is always invoked off the main thread.
- **Display updates are marshalled**: `DisplayWindow.show_text` enqueues the
  widget update via `root.after`, so it is safe to call from listener threads.
- **Loop exit is thread-safe**: use `request_stop()` (any thread) to ask the Tk
  loop to exit; call `stop()` only on the main thread after `start()` returns.

### Implementing Your Own Sink

If your sink touches a GUI toolkit, marshal the work onto that toolkit's thread
yourself — the `TextSink` contract guarantees only that it receives a string,
not that it runs on any particular thread.

## Platform-Specific Notes

### macOS

- Requires accessibility permissions
- May show "This process is not trusted!" warnings (can be ignored)

### Linux

- May require additional packages: `python3-tk`
- Works with both X11 and Wayland

### Windows

- Generally works out of the box
- No additional permissions required

## Performance Tips

1. **Limit Events**: Use `max_events` to prevent memory growth
2. **Filter Keys**: Use the keyboard `show_*` flags to reduce noise
3. **Fade Duration**: Adjust `fade_duration_ms` for performance vs. visibility
4. **Disable Unused Listeners**: Set `keyboard.enabled` / `mouse.enabled` to False

## Debugging

### Enable Debug Logging

```python
import logging

from keycast.logging_setup import setup_logging
from keycast.settings import LoggingSettings

setup_logging(LoggingSettings(level="DEBUG"))
logger = logging.getLogger(__name__)
logger.debug("Debug message")
```

### Test Individual Components

```python
from keycast.listeners import KeyListener
from keycast.settings import KeyboardSettings

# Capture events into a list instead of rendering them.
captured: list[str] = []
listener = KeyListener(show_text=captured.append, settings=KeyboardSettings())
listener.start()
# Press some keys, then inspect `captured`.
```
