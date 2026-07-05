# keycast Design Decisions

## Overview

This document outlines the key design decisions made during the development of keycast, including the rationale behind each choice and alternatives considered.

## Technology Stack Decisions

### Python as the Primary Language

**Decision**: Use Python for the entire application.

**Rationale**:
- Cross-platform compatibility out of the box
- Rich ecosystem for GUI and input handling libraries
- Rapid development and prototyping capabilities
- Strong typing support with modern Python (3.14+)
- Excellent testing and mocking frameworks

**Alternatives Considered**:
- **C++**: Better performance but more complex cross-platform development
- **JavaScript/Electron**: Good for cross-platform but heavier resource usage
- **Go**: Good performance but limited GUI libraries
- **Rust**: Excellent performance but steeper learning curve and limited GUI options

**Trade-offs**:
- ✅ Easy cross-platform deployment
- ✅ Rich library ecosystem
- ✅ Fast development cycle
- ❌ Slightly higher resource usage than native applications
- ❌ Requires Python runtime

### pynput for Input Monitoring

**Decision**: Use the `pynput` library for keyboard and mouse input monitoring.

**Rationale**:
- Cross-platform support (macOS, Linux, Windows)
- Simple, clean API
- Active maintenance and community support
- Handles platform-specific input APIs automatically
- Good error handling for permission issues

**Alternatives Considered**:
- **pygame**: Good for games but overkill for input monitoring
- **keyboard/mouse libraries**: Platform-specific, would require multiple implementations
- **ctypes with platform APIs**: More control but much more complex
- **tkinter events**: Limited to tkinter windows only

**Trade-offs**:
- ✅ Cross-platform compatibility
- ✅ Simple API
- ✅ Good error handling
- ❌ External dependency
- ❌ May require accessibility permissions on some platforms

### Tkinter for Display Window

**Decision**: Use Tkinter for the display window and GUI.

**Rationale**:
- Built into Python standard library
- Cross-platform support
- Good transparency and overlay capabilities
- Lightweight and fast
- No additional dependencies required

**Alternatives Considered**:
- **PyQt/PySide**: More features but heavier and requires separate installation
- **wxPython**: Good cross-platform support but additional dependency
- **Kivy**: Modern but overkill for simple overlay window
- **Web-based (Flask/Django)**: Would require browser and be more complex

**Trade-offs**:
- ✅ No additional dependencies
- ✅ Cross-platform
- ✅ Good transparency support
- ❌ Limited styling options
- ❌ Older API design
- ❌ May not be available in some Python distributions

## Architecture Decisions

### Modular Component Design

**Decision**: Separate the application into distinct, loosely-coupled components.

**Components**:
- `Keycast`: Orchestrates the components and owns the lifecycle
- `DisplayWindow`: Handles visual display (implements the `TextSink` protocol)
- `KeyListener`: Handles keyboard input
- `MouseListener`: Handles mouse input
- `Settings`: Manages configuration with Pydantic validation
- `logging_setup`: Configures logging system
- `main.py`: Orchestrates components

**Rationale**:
- Single Responsibility Principle
- Easy to test individual components
- Easy to modify or replace components
- Clear separation of concerns
- Promotes code reusability

**Alternatives Considered**:
- **Monolithic design**: Everything in one class
- **MVC pattern**: More complex for this simple application
- **Event-driven architecture**: Overkill for current requirements

**Trade-offs**:
- ✅ Easy to understand and maintain
- ✅ Good testability
- ✅ Flexible and extensible
- ❌ Slightly more complex than monolithic approach
- ❌ More files to manage

### TextSink Protocol for Listener → Display Communication

**Decision**: Listeners depend on a `TextSink` protocol — a `Callable[[str], None]`
— rather than on the `DisplayWindow` class. Both `KeyListener` and `MouseListener`
take a `show_text` argument and call it with a fully formatted label.

**Example**:
```python
# DisplayWindow.show_text satisfies the TextSink protocol.
key_listener = KeyListener(show_text=display_window.show_text, settings=keyboard_settings)
mouse_listener = MouseListener(show_text=display_window.show_text, settings=mouse_settings)
```

> **Evolution**: this started as a plain callback pair
> (`on_key_press` / `on_mouse_click`, the latter taking `text, x, y`). It matured
> into a single `TextSink` protocol with one signature, `(text: str) -> None`.
> Two changes drove this:
> 1. **Single sink** — there is one way to show an event (a line of text), so one
>    callback shape suffices for both listeners.
> 2. **Formatting moved upstream** — the mouse listener now formats coordinates
>    into the string itself (`"Left Click (100, 200)"`), so the sink no longer
>    needs `x`/`y` parameters and stays identical to the keyboard sink.

**Rationale**:
- **Decoupling**: listeners know nothing about `DisplayWindow` or tkinter; they
  emit strings to any sink (a logger, queue, or test double)
- **Testability**: tests pass `list.append` (or any `Callable[[str], None]`) as the
  sink and assert on captured strings — no GUI required
- **Explicit threading contract**: the protocol's docstring states the sink is
  invoked on a pynput listener thread, making the marshalling responsibility clear
- Simple and direct; no event system needed; minimal overhead

**Alternatives Considered**:
- **Concrete `DisplayWindow` dependency**: tight coupling; listeners couldn't be
  tested or reused without a real window
- **Two distinct callbacks (key vs. mouse with coordinates)**: the original shape;
  redundant once formatting moved into the listeners
- **Observer pattern / event bus / message queues**: overkill for a single sink

**Trade-offs**:
- ✅ Listeners are display-agnostic and trivially testable
- ✅ One uniform sink signature for all event sources
- ✅ Threading expectations are documented on the protocol
- ❌ Coordinate data is baked into a string, not passed structured (fine for a
  visualizer; a consumer needing raw `x`/`y` would have to parse or be re-extended)

### Pydantic for Settings Management

**Decision**: Use Pydantic for configuration management and validation.

**Rationale**:
- Type safety and validation out of the box
- Excellent IDE support with autocompletion
- Automatic JSON serialization/deserialization
- Clear error messages for invalid configuration
- Modern Python best practices
- Built-in support for complex types (Color, Path, etc.)

**Alternatives Considered**:
- **Manual JSON parsing**: More error-prone and verbose
- **dataclasses**: Less validation capabilities
- **ConfigParser**: Limited to string values
- **YAML with custom validation**: Additional dependency and complexity
- **Environment variables only**: Less user-friendly

**Trade-offs**:
- ✅ Type safety and validation
- ✅ Excellent developer experience
- ✅ Clear error messages
- ✅ Modern Python practices
- ❌ Additional dependency
- ❌ Learning curve for complex validation

### Settings-Based Component Configuration

**Decision**: Pass settings objects to components instead of individual parameters.

**Example**:
```python
display_window = DisplayWindow(settings.display)
key_listener = KeyListener(show_text=display_window.show_text, settings=settings.keyboard)
```

**Rationale**:
- Cleaner component interfaces
- Type-safe configuration
- Easier to extend with new settings
- Consistent configuration pattern
- Better testability with mock settings

**Alternatives Considered**:
- **Individual parameters**: More verbose and error-prone
- **Global configuration**: Harder to test and less flexible
- **Configuration dictionaries**: No type safety
- **Environment variables**: Less user-friendly

**Trade-offs**:
- ✅ Clean interfaces
- ✅ Type safety
- ✅ Easy to extend
- ✅ Better testability
- ❌ More complex initial setup
- ❌ Requires understanding of settings structure

### In-Memory Event Storage

**Decision**: Store events in memory with timestamp-based cleanup.

**Implementation**:
```python
self.events: list[tuple[str, float]] = []  # (event_text, timestamp)
```

**Rationale**:
- Simple and fast
- No external storage dependencies
- Automatic cleanup prevents memory leaks
- Sufficient for the use case
- Easy to implement and debug

**Alternatives Considered**:
- **Database storage**: Overkill for temporary display
- **File-based storage**: Unnecessary persistence
- **Circular buffer**: More complex for minimal benefit
- **External cache**: Additional dependency

**Trade-offs**:
- ✅ Simple and fast
- ✅ No external dependencies
- ✅ Automatic cleanup
- ❌ Limited by available memory
- ❌ Events lost on application restart

## User Experience Decisions

### Transparent Overlay Window

**Decision**: Use a semi-transparent, always-on-top window.

**Rationale**:
- Non-intrusive to user workflow
- Always visible when needed
- Professional appearance
- Standard approach for overlay applications

**Alternatives Considered**:
- **System tray only**: Less visible
- **Separate window**: More intrusive
- **Browser-based**: Requires browser
- **Desktop widget**: Platform-specific

**Trade-offs**:
- ✅ Non-intrusive
- ✅ Always visible
- ✅ Professional look
- ❌ May interfere with some applications
- ❌ Platform-specific behavior differences

### Event Fade-Out Effect

**Decision**: Implement automatic fade-out of events after a configurable duration.

**Rationale**:
- Prevents window from becoming cluttered
- Automatic cleanup without user intervention
- Configurable duration for different use cases
- Smooth visual experience

**Alternatives Considered**:
- **Manual clear button**: Requires user interaction
- **Fixed number of events**: Less flexible
- **No cleanup**: Would fill up the window
- **Scrollable window**: More complex UI

**Trade-offs**:
- ✅ Automatic cleanup
- ✅ Configurable behavior
- ✅ Smooth user experience
- ❌ Events disappear automatically
- ❌ Additional complexity in implementation

### Configurable Key Filtering

**Decision**: Allow users to configure which types of keys to display.

**Options**:
- Show/hide modifier keys (Ctrl, Alt, Shift)
- Show/hide function keys (F1, F2, etc.)
- Show/hide special keys (Enter, Space, etc.)

**Rationale**:
- Reduces visual noise
- Allows customization for different use cases
- Improves performance by filtering unnecessary events
- Better user experience

**Alternatives Considered**:
- **Show all keys**: Too much noise
- **Fixed filtering**: Less flexible
- **Regex-based filtering**: Too complex for users
- **Machine learning filtering**: Overkill

**Trade-offs**:
- ✅ Reduces noise
- ✅ User customizable
- ✅ Better performance
- ❌ More configuration options
- ❌ Users need to understand key types

### Chord Grouping (Modifier + Key)

**Decision**: Optionally combine a key pressed with held modifiers into one chord
label (e.g. `Control Left + S`) via `KeyboardSettings.group_chords`
(default `false`) and `chord_separator` (default `" + "`). The `presenter` preset
turns it on.

**How it works**: `KeyListener` gains a tiny state machine on the pynput listener
thread — an insertion-ordered dict of currently-held modifiers and a
"chord fired this hold" flag. Modifier presses are held silently; a non-modifier
press while modifiers are held emits one joined label; a modifier released without
completing a chord is emitted alone (respecting `show_modifier_keys`). This is the
only place the listener registers pynput's `on_release`, needed purely to know
which modifiers are down.

**Why default off**: an existing, tested contract is that a modifier press emits
its label immediately. Chord grouping deliberately *defers* modifier display, so
turning it on by default would change long-standing behavior. Keeping it opt-in
(and enabling it through the `presenter` preset) preserves the default experience
while making the screencast-style behavior one preset away.

**Why in the listener, not the display**: grouping is a property of the *event
stream* (what was pressed together), not of rendering. Formatting the chord into a
single string upstream keeps the `TextSink` contract unchanged — the display still
receives one line — consistent with how mouse coordinates are already formatted
into the string upstream.

**Alternatives Considered**:
- **Group in the display layer**: the display would need raw key/modifier state and
  timing, breaking the "one formatted string" sink contract for no gain
- **Timing-based sequential chords** (`Ctrl+K` then `Ctrl+S` as one unit, as VS
  Code shows): needs a timeout window and chord-map knowledge; deferred — the
  simultaneous modifier+key case is the common one
- **Default on**: rejected to avoid changing the established default behavior

**Trade-offs**:
- ✅ Cleaner, presentation-friendly output for shortcuts
- ✅ Sink contract and display layer untouched
- ✅ Opt-in; default behavior preserved
- ❌ Adds per-thread state to the previously stateless listener
- ❌ Sequential (multi-stroke) chords are not grouped yet

### Click Ripple (Second Listener Channel)

**Decision**: Optionally paint an expanding, fading ring at the cursor on each
click (`MouseSettings.show_click_ripple`, default `false`). The ripple is fed by a
**second** listener channel — a `ClickSink` (`Callable[[int, int], None]`) —
separate from the `TextSink`, because it needs the raw `(x, y)` a formatted string
cannot carry. `DisplayWindow.show_click` is the production `ClickSink`; the
`presenter` and `debug` presets enable the feature.

**Why a second channel, not a richer TextSink**: the `TextSink` decision above
deliberately settled on one signature, `(text: str) -> None`, and noted the
trade-off that coordinate data is baked into a string — "a consumer needing raw
`x`/`y` would have to parse or be re-extended." The ripple is exactly that
consumer. Rather than overload the text sink (and break every existing sink), a
parallel, optional `ClickSink` is added. `MouseListener` takes it as a
**keyword-only** argument so the documented positional constructor
(`show_text, settings`) — pinned by `test_docs_contract.py` — is unchanged.

**Why the appearance lives in `MouseSettings` but rendering in `DisplayWindow`**:
the ripple is conceptually a mouse-click visualization, so its knobs
(`ripple_color`, `ripple_max_radius`, `ripple_duration_ms`) sit with the other
mouse settings. Rendering, however, needs the Tk main loop the `DisplayWindow`
owns, so the window draws it. The composition root passes the three appearance
values into `DisplayWindow` as keyword-only constructor args (again keeping the
pinned `settings`-only positional signature), so the window stays self-contained
and does not import `MouseSettings`.

**Rendering & platform reality**: the ring is drawn in its own transient,
borderless, always-on-top toplevel that animates via the same self-rescheduling
`root.after` pattern as the fade timer, then destroys itself. The animation math
is factored into a pure `_ripple_frame` helper so it is unit-testable without Tk.

Two distinct concerns, both needing native APIs Tk does not expose:

- **Click-through (input)** — critical: a topmost window at the cursor otherwise
  *catches the click it is visualizing* (an Electron app like the Superset desktop
  app was a real victim). Fixed with `NSWindow.setIgnoresMouseEvents_(True)` on
  macOS (via pyobjc; the new window is found by diffing `NSApplication.windows()`
  before/after creation) and the `WS_EX_TRANSPARENT | WS_EX_LAYERED` extended
  style on Windows. Reliable on macOS/Windows; best-effort elsewhere (X11 input
  shaping is not implemented), where the ring may intercept clicks.
- **Background transparency (visual)** — so only the ring shows, not a filled
  square: `-transparent` on macOS, `-transparentcolor` on Windows. Genuinely
  unreliable from Tk, so best-effort; a failure leaves a brief translucent square.

Every native call is wrapped and routed through the throttler/debug log,
consistent with the display layer's "degrade, don't crash" behavior, and the
feature defaults off.

**Alternatives Considered**:
- **Overload `TextSink` to carry coordinates**: breaks the one-signature decision
  and every existing sink; rejected
- **A fully click-through, pixel-perfect overlay**: needs per-platform native code
  (ctypes/pyobjc) with no headless test path; deferred in favor of a best-effort
  ring that is off by default
- **Draw the ripple inside the main overlay window**: the overlay is a small fixed
  rectangle, not full-screen, so it can't host a ring at an arbitrary cursor
  position; a separate toplevel is required

**Trade-offs**:
- ✅ Screencast-style click feedback anywhere on screen
- ✅ `TextSink` contract and all existing sinks untouched
- ✅ Testable animation math; rendering degrades gracefully
- ❌ Transparency / click-through are best-effort per platform
- ❌ A second, transient window per click (kept short-lived to bound cost)

## Performance Decisions

### Threading Model

**Decision**: Keep threading minimal — run the fade timer on the Tk main loop
(not a separate thread) and let pynput own the input threads.

**Threading Strategy**:
- Main thread: Tkinter UI loop, including the self-rescheduling fade timer (`root.after`)
- pynput threads: Input monitoring (handled by the library), where the `TextSink` is invoked
- Cross-thread updates: `show_text` marshals onto the Tk loop via `after`; `request_stop` asks the loop to exit

**Rationale**:
- Simple threading model
- Minimal thread overhead — the fade timer reuses the Tk event loop instead of spawning a thread
- Thread-safe communication: the sink marshals work onto the UI loop rather than touching widgets directly
- No manual thread lifecycle to manage for the fade timer

**Alternatives Considered**:
- **Single-threaded**: Would block UI during processing
- **Complex thread pool**: Unnecessary for this use case
- **Async/await**: More complex for simple operations
- **Process-based**: Overkill and more complex

**Trade-offs**:
- ✅ Simple and reliable
- ✅ Minimal overhead
- ✅ Easy to debug
- ❌ Limited parallelism
- ❌ Potential UI blocking if not careful

### Event Limiting

**Decision**: Limit the maximum number of displayed events.

**Implementation**:
```python
# DisplaySettings.max_events (default 5, configurable)
recent_events = self.events[-self.settings.max_events:]
```

**Rationale**:
- Prevents memory growth
- Keeps display manageable
- Configurable for different use cases
- Simple implementation

**Alternatives Considered**:
- **Unlimited events**: Would cause memory issues
- **Time-based limiting**: More complex
- **Size-based limiting**: Harder to predict
- **User-controlled limiting**: Requires UI

**Trade-offs**:
- ✅ Prevents memory issues
- ✅ Simple implementation
- ✅ Configurable
- ❌ May lose older events
- ❌ Fixed limit may not suit all users

## Security and Privacy Decisions

### Local-Only Processing

**Decision**: All input processing happens locally with no external communication.

**Rationale**:
- Privacy protection
- No network dependencies
- No data transmission
- Works offline
- No security concerns about data leaks

**Alternatives Considered**:
- **Cloud processing**: Privacy concerns
- **Network logging**: Security risks
- **External services**: Additional complexity and privacy issues

**Trade-offs**:
- ✅ Complete privacy
- ✅ No network dependencies
- ✅ Works offline
- ❌ No remote features
- ❌ No data backup

### No Persistent Storage

**Decision**: Do not persist any input data to disk.

**Rationale**:
- Privacy protection
- No sensitive data on disk
- Simpler implementation
- No cleanup required

**Alternatives Considered**:
- **Log files**: Privacy concerns
- **Database storage**: Unnecessary complexity
- **Configuration persistence**: Only for settings, not input data

**Trade-offs**:
- ✅ Complete privacy
- ✅ No disk usage
- ✅ Simple implementation
- ❌ No data persistence
- ❌ No playback capabilities

## Testing Decisions

### Comprehensive Mocking Strategy

**Decision**: Use extensive mocking for external dependencies in tests.

**Mocking Strategy**:
- Mock Tkinter components completely
- Mock pynput input events
- Mock platform-specific functionality
- Use dependency injection where possible

**Rationale**:
- Enables headless testing
- Fast test execution
- Reliable test results
- No external dependencies in tests
- Cross-platform test compatibility

**Alternatives Considered**:
- **Integration tests only**: Slower and less reliable
- **Minimal mocking**: Would require GUI environment
- **End-to-end tests**: Too slow for development

**Trade-offs**:
- ✅ Fast and reliable tests
- ✅ No external dependencies
- ✅ Cross-platform compatibility
- ❌ May not catch integration issues
- ❌ More complex test setup

### Unit Test Focus

**Decision**: Focus primarily on unit tests with comprehensive coverage.

**Rationale**:
- Fast feedback during development
- Easy to debug failures
- Good coverage of individual components
- Reliable and repeatable

**Alternatives Considered**:
- **Integration tests**: Slower and more complex
- **End-to-end tests**: Very slow and flaky
- **Manual testing only**: Not scalable

**Trade-offs**:
- ✅ Fast execution
- ✅ Reliable results
- ✅ Easy debugging
- ❌ May miss integration issues
- ❌ Requires good mocking

## Configuration Decisions

### JSON Configuration Format with Pydantic Validation

**Decision**: Use JSON for configuration files with Pydantic validation.

**Rationale**:
- Human-readable format
- Widely supported
- Easy to parse and validate with Pydantic
- Good tooling support
- Standard format
- Type safety and validation
- Clear error messages for invalid configuration

**Alternatives Considered**:
- **YAML**: More readable but additional dependency
- **TOML**: Good but less common
- **INI files**: Limited data types
- **Python files**: Security concerns
- **JSON without validation**: Error-prone

**Trade-offs**:
- ✅ Standard format
- ✅ Good tooling
- ✅ Human readable
- ✅ Type safety and validation
- ✅ Clear error messages
- ❌ No comments support
- ❌ Verbose syntax

### Single Authoritative Configuration Source

**Decision**: Load settings from the JSON config file only, layered over the
Pydantic model defaults. Constructor kwargs, environment variables, dotenv, and
file-secret sources are intentionally **not** consulted.

**How it works**:
1. Default values (defined in the Pydantic models) fill any unset field.
2. The JSON configuration file (`~/.keycast/config.json`) is the sole source of
   overrides; it is validated on load.

`Settings.settings_customise_sources` enforces this by returning only
`JsonConfigSettingsSource` — so `Settings(display=...)` constructor kwargs and
environment variables have no effect on loaded settings. Tests that need
overrides patch the JSON source.

**Rationale**:
- One obvious place to look when configuration "doesn't take" — no precedence
  puzzles between env vars, kwargs, and file
- Reproducible: the running config is exactly what is on disk
- Sensible defaults still apply for every unspecified field

**Alternatives Considered**:
- **Full Pydantic source stack** (init + env + dotenv + file): more flexible but
  reintroduces the precedence ambiguity this decision exists to remove
- **Environment variables**: less discoverable for a desktop overlay app
- **Command-line only**: limited and not persistent

**Trade-offs**:
- ✅ Single, predictable source of truth
- ✅ Good defaults
- ✅ Easy to reason about and test
- ❌ No per-invocation overrides without editing the file (or patching the source)

### Named Setting Presets ("Modes")

**Decision**: Ship a small set of built-in presets — `custom` (default),
`presenter`, `minimal`, and `debug` — selected via a top-level `preset` field.
A non-`custom` preset layers a fixed bundle of overrides over the loaded config;
`custom` uses the file verbatim.

**How it works**:
1. `Settings.create_settings_file()` loads and (on first run) persists the config
   exactly as before — the on-disk file always records the user's raw values plus
   their chosen `preset` name, never the resolved overlay.
2. `Settings.resolve_preset()` then returns a **new** `Settings`: for each
   overridden section it dumps the current values with `model_dump(mode="json")`,
   merges the preset's fields on top, and rebuilds the section with that section
   model's `model_validate(...)`; `model_copy(update=...)` then swaps the rebuilt
   sections (and any top-level scalar flag) into a new `Settings`.
   `Keycast.__init__` calls this immediately after loading, so every downstream
   component sees the resolved settings.

**Precedence**: a preset **wins over the file** for the fields it names, and only
those fields — everything else keeps its configured/default value. `custom`
applies nothing, so existing configs behave identically. Users who want a preset
as a *starting point they can edit* should copy its values into `custom` instead.

**Why re-validate each section instead of `model_copy(update=...)` alone**:
`model_copy` rebinds fields without running validators, so an internally
inconsistent bundle (e.g. a mouse override that trips
`_validate_position_requires_clicks`) would pass silently. Rebuilding each
overridden section through its `model_validate` re-runs that section's field
bounds and cross-field validators, exactly as loading the config does; the
`model_copy` step then only assembles already-validated sections. Note the
sub-models (`DisplaySettings`, `MouseSettings`, …) are plain `BaseModel`, where
`model_validate` honours the data passed to it — the top-level `Settings` is a
`BaseSettings` whose `model_validate` re-runs the configured JSON *source* instead
of the passed fields, so it deliberately is **not** used to re-assemble here (and
the preset's Literal is enforced only on the real load path, through that source).

**Rationale**:
- One-word switch for common scenarios (a screencast, an unobtrusive corner
  overlay, a troubleshooting session) without hand-editing several fields
- Layers cleanly on the single-source model above — the file stays authoritative,
  the preset is a deterministic transform applied after load
- `custom` default is a no-op, so the feature is additive and backwards-compatible

**Alternatives Considered**:
- **A `presets` settings source in `settings_customise_sources`**: would reopen
  the precedence ambiguity the single-source decision exists to remove, and
  presets are built-in constants, not another external input
- **Preset-as-defaults (file always wins, preset fills only unset fields)**: more
  intuitive for power users but needs `model_fields_set` tracking threaded through
  the JSON source; deferred in favor of the simpler, fully-documented "preset wins
  for named fields" rule
- **Free-form user-defined presets in the config**: more flexible but adds a
  nested schema and validation surface; the built-in set covers the common cases

**Trade-offs**:
- ✅ Common setups are one field away
- ✅ File remains the single source of truth; resolution is a pure transform
- ✅ Re-validation guarantees a preset can never produce invalid settings
- ❌ A preset's fields can't be partially overridden from the file (use `custom`)
- ❌ The preset catalog is code, not config (adding one is a code change)

## Error Handling Decisions

### Graceful Degradation

**Decision**: Handle errors gracefully and continue operation when possible.

**Strategy**:
- Log errors but continue running
- Provide fallback behavior
- Handle permission errors gracefully
- Clean shutdown on critical errors

**Rationale**:
- Better user experience
- More robust application
- Handles platform differences
- Continues working despite issues

**Alternatives Considered**:
- **Fail fast**: Less user-friendly
- **Silent failures**: Hard to debug
- **Complex error recovery**: Overkill

**Trade-offs**:
- ✅ Better user experience
- ✅ More robust
- ✅ Handles edge cases
- ❌ May hide real issues
- ❌ More complex error handling

### Comprehensive Logging with Settings Integration

**Decision**: Implement comprehensive logging throughout the application with settings-based configuration.

**Logging Strategy**:
- Different log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Structured log messages with configurable format
- Configurable log level via settings
- Optional file logging with rotation
- Error context and stack traces

**Rationale**:
- Easier debugging
- Better monitoring
- User feedback
- Development support
- Configurable via settings
- Professional logging setup

**Alternatives Considered**:
- **Minimal logging**: Harder to debug
- **Print statements**: Not configurable
- **External logging**: Additional complexity
- **Fixed logging configuration**: Less flexible

**Trade-offs**:
- ✅ Better debugging
- ✅ Configurable output
- ✅ Professional approach
- ✅ Settings integration
- ✅ File rotation support
- ❌ Additional complexity
- ❌ More code to maintain

## Future Considerations

### Install-Source-Aware Update Check

**Decision**: Notify users of new releases in a way that matches their install
channel, rather than blindly self-updating. Self-update is reserved for the one
channel no package manager owns (manually-downloaded GitHub Release builds) and
is deferred to a second phase.

**Status**: Phase 1 (notify) implemented in `keycast.updates`; Phase 2 (in-place
self-update of a downloaded Release build) is a deferred follow-up. Full design
and rationale in [ADR-002](adr/002-update-check.md) (covers source detection, the
`check_for_updates` opt-out, GitHub Releases API check via stdlib `urllib`,
24 h throttle in a separate state file, and the Phase 1 / Phase 2 split).

### Extensibility Design

**Decision**: Design components to be easily extensible.

**Extensibility Features**:
- Plugin-like architecture
- Configurable behavior
- Clean interfaces
- Modular design

**Rationale**:
- Future feature additions
- Community contributions
- Custom use cases
- Long-term maintainability

### Performance Optimization

**Decision**: Design for performance but prioritize simplicity.

**Performance Considerations**:
- Efficient event processing
- Minimal memory usage
- Fast UI updates
- Lightweight dependencies

**Rationale**:
- Good user experience
- Low resource usage
- Responsive interface
- Battery friendly

### Cross-Platform Compatibility

**Decision**: Prioritize cross-platform compatibility in all decisions.

**Compatibility Strategy**:
- Use cross-platform libraries
- Handle platform differences
- Test on multiple platforms
- Document platform-specific requirements

**Rationale**:
- Broader user base
- Consistent experience
- Easier maintenance
- Future platform support
