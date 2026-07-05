# keycast Architecture Documentation

## Overview

keycast is a cross-platform keystroke and mouse click visualizer built in Python. It provides a real-time overlay window that displays user input events in a transparent, always-on-top window.

## Project Structure

```
keycast/
├── src/keycast/           # Main source code
│   ├── __init__.py       # Package initialization
│   ├── __main__.py       # `python -m keycast` entry point
│   ├── application.py    # Keycast orchestrator (lifecycle + wiring)
│   ├── cli.py            # Typer CLI entry point
│   ├── main.py           # main(): constructs and runs Keycast
│   ├── display.py        # Tkinter overlay window (DisplayWindow)
│   ├── listeners.py      # Input event listeners + TextSink protocol
│   ├── secure_input.py   # macOS secure-input probe (password-field masking)
│   ├── settings.py       # Pydantic settings configuration
│   └── logging_setup.py  # Logging configuration
├── tests/                # Test suite
│   ├── test_application.py    # Orchestrator lifecycle tests
│   ├── test_cli.py            # CLI command tests
│   ├── test_main.py           # Entry point tests
│   ├── test_display.py        # Display window tests
│   ├── test_listeners.py      # Listener tests
│   ├── test_secure_input.py   # Secure-input probe tests
│   ├── test_settings.py       # Settings/validation tests
│   └── test_logging_setup.py  # Logging configuration tests
├── docs/                 # Documentation
│   └── ARCHITECTURE.md   # This file
├── pyproject.toml        # Project configuration
├── README.md            # User documentation
└── uv.lock              # Dependency lock file
```

## Architecture Overview

keycast follows a modular architecture with clear separation of concerns:

Listeners push formatted strings into a single `TextSink` (implemented by
`DisplayWindow.show_text`); `Keycast` wires the components together and owns the
lifecycle.

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   KeyListener   │    │  MouseListener  │    │  DisplayWindow  │
│                 │    │                 │    │                 │
│ - Captures keys │    │ - Captures      │    │ - show_text()   │
│ - Formats keys  │    │   mouse clicks  │    │   (TextSink)    │
│ - Filters keys  │    │ - Formats       │    │ - Manages UI    │
└─────────┬───────┘    │   click+pos     │    │ - Handles fade  │
          │            └─────────┬───────┘    └─────────▲───────┘
          │ show_text(str)       │ show_text(str)       │
          └──────────────────────┴──────────────────────┘
                                 │ (constructs & connects)
                    ┌─────────────▼─────────────┐
                    │   application.py (Keycast)│
                    │                           │
                    │ - Orchestrates components │
                    │ - Handles signals         │
                    │ - Manages lifecycle       │
                    │ - Loads settings          │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │       settings.py         │
                    │                           │
                    │ - Pydantic configuration  │
                    │ - Settings validation     │
                    │ - JSON file management    │
                    └───────────────────────────┘

main.py / cli.py / __main__.py are thin entry points that call Keycast().run().
```

## Core Components

### 1. Orchestrator (`application.py`) and Entry Points

**Purpose**: `application.Keycast` is the orchestration layer. The entry points
(`main.py`, `cli.py`, `__main__.py`) are thin wrappers that construct a
`Keycast` and call `run()`.

**Responsibilities (`Keycast`)**:
- Load and validate settings using Pydantic (`Settings.create_settings_file()`)
- Initialize logging system with settings, then log a startup line stamping the
  keycast version and `sys.platform` (so a user-submitted `main.log` identifies
  the build and OS that produced it)
- Create and connect all components (each listener's `show_text` → the window)
- Derive a per-source startup input status (active / disabled / no-access /
  failed / unknown) from each listener's start outcome and, on macOS, a
  best-effort permission precheck; render it as a one-line overlay summary
  (gated by `show_startup_status`) and always emit it as a structured
  `startup_input_status` log event
- Set up signal handlers for graceful shutdown
- Coordinate component lifecycle
- Handle application-level errors

**Key Members**:
- `Keycast.run()`: Installs SIGINT/SIGTERM handlers, starts, and guarantees `stop()`
- `Keycast.start()` / `Keycast.stop()`: Lifecycle (`stop()` is idempotent and best-effort)
- `Keycast.signal_handler()`: Requests the display loop to exit on a signal
- `main()` (`main.py`): Constructs `Keycast` and calls `run()`

**Entry points**:
- `keycast` console script → `keycast.cli:app` (Typer; also exposes `version` / `info`)
- `python -m keycast` → `keycast.__main__` → `main()`

**Design Decisions**:
- **Orchestrator Class**: Lifecycle and wiring live in `Keycast`, keeping entry points thin and testable
- **Settings Integration**: Uses Pydantic for type-safe configuration
- **Signal Handling**: The handler only *requests* loop exit; teardown happens after `mainloop` returns (destroying a window mid-loop raises Tcl errors)
- **Error Handling**: `run()` logs exceptions and ensures `stop()` runs in a `finally` block
- **Component Lifecycle**: Explicit, idempotent start/stop management for all components

### 2. Display Window (`display.py`)

**Purpose**: Manages the visual overlay window using Tkinter.

**Responsibilities**:
- Create and manage transparent overlay window
- Display keystroke and mouse click events
- Handle window positioning and styling
- Manage event fade-out effects
- Limit displayed events to prevent overflow

**Key Classes**:
- `DisplayWindow`: Overlay window class; implements `TextSink` via `show_text`

**Key Features**:
- **Settings Integration**: Uses DisplaySettings for configuration
- **Transparency**: Semi-transparent window with configurable alpha
- **Always on Top**: Window stays above other applications
- **Event Management**: Stores events with timestamps for fade effects
- **Thread-safe sink**: `show_text` marshals updates onto the Tk loop via `root.after`
- **Customizable**: Colors, fonts, position, and behavior

**Design Decisions**:
- **Settings-based Configuration**: Uses Pydantic models for type-safe settings
- **Tkinter Choice**: Cross-platform GUI framework with good transparency support
- **Single-loop fade timer**: `_fade_timer` re-schedules itself with `root.after(100, ...)` on the Tk main loop — no separate thread
- **Two-phase shutdown**: `request_stop()` (any thread) asks the loop to exit; `stop()` (main thread) destroys the window after `mainloop` returns
- **Event Storage**: In-memory storage with timestamp-based cleanup, guarded by a lock
- **Window Decorations**: Removed for clean overlay appearance

### 3. Input Listeners (`listeners.py`)

**Purpose**: Capture keyboard and mouse input events using pynput.

**Responsibilities**:
- Monitor global keyboard events
- Monitor global mouse click events
- Format events for display
- Filter events based on configuration
- Handle platform-specific input handling

**Key Classes**:
- `KeyListener`: Handles keyboard input events
- `MouseListener`: Handles mouse click events

**Key Features**:
- **Settings Integration**: Uses KeyboardSettings and MouseSettings for configuration
- **Cross-platform**: Uses pynput for consistent behavior across platforms
- **Configurable Filtering**: Show/hide different types of keys and mouse events
- **Custom Mappings**: User-defined key and button name mappings
- **Secure-input masking**: On macOS, `KeyListener` drops keystrokes while the OS
  reports secure input (password/authentication fields) so credentials never
  reach the sink; the check sits at the single-sink boundary ahead of chord
  state, via the `secure_input` probe (best-effort, macOS-only)
- **Error Handling**: Graceful handling of permission issues and errors

**Design Decisions**:
- **Settings-based Configuration**: Uses Pydantic models for type-safe settings
- **pynput Library**: Chosen for cross-platform input monitoring
- **TextSink Protocol**: Listeners depend on the `TextSink` protocol (a `Callable[[str], None]`), not on `DisplayWindow`, decoupling capture from rendering
- **Formatting upstream**: Listeners format the full label (including mouse position) into one string before calling the sink
- **Filtering System**: Configurable filtering to reduce noise
- **Error Resilience**: Per-event callback errors are caught and throttled, so a failing sink can't crash the listener thread

### 4. Settings System (`settings.py`)

**Purpose**: Manages application configuration using Pydantic for validation and type safety.

**Responsibilities**:
- Define configuration models with validation
- Load settings from JSON configuration files
- Provide default values for all settings
- Validate settings at runtime
- Create configuration files if they don't exist

**Key Classes**:
- `Settings`: Main settings class with all configuration sections
- `DisplaySettings`: Display window configuration
- `KeyboardSettings`: Keyboard listener configuration
- `MouseSettings`: Mouse listener configuration
- `LoggingSettings`: Logging configuration

**Key Features**:
- **Type Safety**: Pydantic models ensure type safety and validation
- **Default Values**: Sensible defaults for all configuration options
- **Validation**: Automatic validation of configuration values
- **File Management**: Automatic creation of configuration files
- **Hierarchical Structure**: Organized settings by component

**Design Decisions**:
- **Pydantic Choice**: Provides excellent validation and type safety
- **JSON Configuration**: Human-readable configuration format
- **Automatic File Creation**: Creates config files with defaults if missing
- **Validation**: Ensures configuration values are within valid ranges
- **Modular Design**: Separate settings classes for different components

### 5. Logging System (`logging_setup.py`)

**Purpose**: Configures logging for the application with flexible output options.

**Responsibilities**:
- Set up logging configuration based on settings
- Configure log levels and formatting
- Set up file logging with rotation if specified
- Provide consistent logging across the application

**Key Functions**:
- `setup_logging()`: Configures logging based on LoggingSettings
- `format_event()`: Renders a log message as `event key=value ...` for
  structured, greppable text logs

**Message Convention**:
- Log messages use a snake_case `event` name followed by `key=value` fields
  (e.g. `keyboard_listener_started`, `keycast_starting version=0.1.0
  platform=darwin`). Build them with `format_event()` so context stays
  greppable.
- Context is embedded in the message string, **not** passed via `logging`'s
  `extra=`: the default text formatter does not render `extra` fields, so they
  would be silently dropped. `format_event()` repr-quotes any value that would
  otherwise break a token — one containing whitespace or `=`, or an empty value
  — so each field stays a single greppable token.

**Key Features**:
- **Settings Integration**: Uses LoggingSettings for configuration
- **Flexible Output**: Console and/or file logging
- **Log Rotation**: Automatic log file rotation with size limits
- **Configurable Format**: Customizable log message format
- **Level Control**: Configurable logging levels
- **Structured Messages**: `event key=value` style via `format_event()`

**Design Decisions**:
- **Settings-based Configuration**: Uses LoggingSettings for configuration
- **File Rotation**: Prevents log files from growing too large
- **Flexible Output**: Supports both console and file logging
- **Standard Library**: Uses Python's built-in logging system
- **Structure in the message, not `extra`**: keycast logs to a human-readable
  text file, so structured context is embedded in the message rather than
  relying on `extra` fields the default formatter ignores

## Data Flow

```
User Input → pynput → Listeners → Formatting → Display Window → Tkinter → Screen
     ↑                                                              ↓
     └─────────────────── Event Storage ←──────────────────────────┘
```

### Detailed Flow:

1. **Settings Loading**: Application loads and validates settings using Pydantic
2. **Logging Setup**: Logging system configured based on settings
3. **Component Initialization**: All components created with their respective settings
4. **Input Capture**: pynput captures global keyboard/mouse events
5. **Event Processing**: Listeners format and filter events based on settings
6. **Display Update**: Formatted events sent to display window
7. **Visual Rendering**: Tkinter renders events in overlay window
8. **Fade Management**: A self-rescheduling `root.after` callback on the Tk loop fades out old events

## Configuration System

keycast loads configuration from a single authoritative source, layered over
the model defaults:

1. **Default Values**: Sensible defaults defined in Pydantic models
2. **Configuration File**: User-customizable JSON configuration (`~/.keycast/config.json`), validated on load

`Settings.settings_customise_sources` returns only `JsonConfigSettingsSource`, so
constructor kwargs and environment variables are intentionally ignored — the JSON
file is the only override source.

### Configuration Categories:

- **Display Settings**: Window appearance, position, colors, fonts, behavior
- **Keyboard Settings**: Enable toggle, key filtering, custom mappings
- **Mouse Settings**: Enable toggle, click display, position tracking, button mappings
- **Logging Settings**: Log levels, formatting, file output, rotation

## Error Handling Strategy

### Multi-layered Error Handling:

1. **Component Level**: Each component handles its own errors gracefully
2. **Application Level**: Main module catches and logs all exceptions
3. **Signal Handling**: Graceful shutdown on interruption
4. **Resource Cleanup**: Finally blocks ensure proper cleanup

### Error Types Handled:

- **Permission Errors**: A listener that cannot start (e.g. missing
  Accessibility / Input Monitoring permission on macOS) is logged with an
  actionable hint and skipped; the overlay and any other listener keep running
  rather than aborting startup ("degrade, don't crash"). The failure is also
  reflected in the startup input status. On macOS this is subtle: a listener's
  `start()` succeeds even when permission is denied (the event tap fails
  asynchronously), so the status resolver believes an explicit *denied*
  permission precheck over an apparently-successful start rather than reporting
  "OK" for a source that will never capture. The best-effort ctypes precheck is
  itself wrapped so it can never abort startup.
- **Platform Differences**: Cross-platform compatibility issues
- **Input Errors**: Malformed or unexpected input events
- **Display Errors**: Tkinter initialization and rendering issues
- **Threading Errors**: Per-event callback failures on pynput listener threads (caught and throttled)

## Threading Model

keycast uses a simple threading model:

- **Main Thread**: UI thread running the Tkinter mainloop; also runs the
  self-rescheduling fade timer (`root.after`, not a separate thread)
- **Listener Threads**: pynput background threads for input monitoring, on which
  the `TextSink` is invoked

### Thread Safety:

- **Event Storage**: Event list guarded by a lock, with timestamp-based cleanup
- **Display Updates**: `show_text` enqueues work via Tkinter's `after()` so it is
  safe to call from listener threads
- **Loop Exit**: `request_stop()` is safe from any thread (including the signal
  handler); `stop()` runs only on the main thread after `mainloop` returns
- **Component Communication**: `TextSink`-based, decoupling listeners from the display

## Testing Strategy

### Test Coverage:

- **Unit Tests**: Individual component testing with mocks
- **Integration Tests**: Component interaction testing
- **Mock Strategy**: Comprehensive mocking of external dependencies

### Test Categories:

1. **Display Tests**: Tkinter window behavior and event display
2. **Listener Tests**: Input event capture and formatting
3. **Application Tests**: Orchestrator wiring, lifecycle, and shutdown
4. **CLI Tests**: Console commands (`version`, `info`) and launch path
5. **Settings Tests**: Validation, defaults, and config recovery
6. **Logging Tests**: Logging configuration
7. **Main Tests**: Entry-point delegation

### Mocking Strategy:

- **Tkinter Mocking**: Complete mock of Tkinter components for headless testing
- **pynput Mocking**: Mock input events for predictable testing
- **Platform Mocking**: Cross-platform behavior testing

## Performance Considerations

### Optimizations:

- **Event Limiting**: Maximum number of displayed events to prevent memory growth
- **Fade Timer**: Efficient background cleanup of old events
- **Minimal UI Updates**: Only update display when necessary
- **Lightweight Dependencies**: Minimal external dependencies

### Resource Management:

- **Memory**: Bounded event storage with automatic cleanup
- **CPU**: Efficient event processing and display updates
- **Threading**: Minimal thread overhead with daemon threads

## Security Considerations

### Input Monitoring:

- **Local Only**: All input monitoring happens locally
- **No Network**: No data transmission or external communication
- **Permission Based**: Respects platform permission systems

### Privacy:

- **No Storage**: Events not persisted to disk
- **Memory Only**: Temporary in-memory storage only
- **User Control**: User controls what events are displayed
- **Secure-input masking**: On macOS, keystrokes typed into password/authentication
  fields are suppressed by default (`keyboard.mask_secure_input`) so credentials
  never appear on the overlay or in a recording — best-effort, macOS-only (see
  [ADR-015](adr/015-secure-input-masking.md))

## Platform Compatibility

### Supported Platforms:

- **macOS**: Full support with accessibility permissions
- **Linux**: Full support with X11/Wayland
- **Windows**: Full support with Windows API

### Platform-Specific Considerations:

- **macOS**: Requires accessibility permissions in System Preferences
- **Linux**: May require additional packages for Tkinter
- **Windows**: Generally works out of the box

## Future Architecture Considerations

### Potential Improvements:

1. **Plugin System**: Extensible architecture for custom event handlers
2. **Configuration UI**: GUI-based configuration management
3. **Multiple Displays**: Support for multiple monitor setups
4. **Event Recording**: Optional event logging and playback
5. **Custom Themes**: Advanced theming and styling options

### Scalability:

- **Modular Design**: Easy to add new input types or display methods
- **Configuration Driven**: Behavior controlled by configuration
- **Clean Interfaces**: Well-defined component interfaces

## Dependencies

### Core Dependencies:

- **pynput**: Cross-platform input monitoring
- **pydantic**: Data validation and settings management
- **pydantic-settings**: Settings management for Pydantic
- **pydantic-extra-types**: Additional types for Pydantic (Color)
- **tkinter**: GUI framework (built into Python)

### Development Dependencies:

- **pytest**: Testing framework
- **uv**: Package management and build system

### Version Requirements:

- **Python**: >=3.14 (for modern type hints and features)
- **pynput**: >=1.8.1 (for reliable cross-platform support)
- **pydantic**: >=2.0 (for modern validation features)

## Build and Distribution

### Build System:

- **uv**: Modern Python package manager
- **pyproject.toml**: Standard Python project configuration
- **Entry Points**: Console script for easy execution

### Distribution:

- **Source Distribution**: Standard Python package
- **Console Script**: `keycast` command for easy execution
- **Cross-platform**: Works on all supported platforms
