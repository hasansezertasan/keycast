# keycast Project Overview

## Project Summary

keycast is a cross-platform keystroke and mouse click visualizer that displays user input events in real-time through a transparent overlay window. Built in Python, it provides a clean, non-intrusive way to visualize keyboard and mouse interactions for presentations, tutorials, or debugging purposes.

## Key Features

### Core Functionality
- **Real-time Input Visualization**: Displays keystrokes and mouse clicks as they occur
- **Transparent Overlay**: Semi-transparent window that stays on top of other applications
- **Cross-platform Support**: Works on macOS, Linux, and Windows
- **Configurable Display**: Customizable colors, fonts, position, and behavior
- **Event Filtering**: Show/hide different types of keys and mouse events
- **Fade Effects**: Events automatically fade out after a configurable duration

### Technical Features
- **Modular Architecture**: Clean separation of concerns with distinct components
- **Thread-safe Design**: Proper threading for UI and background tasks
- **Comprehensive Testing**: Full test coverage with mocking strategy
- **Error Handling**: Graceful handling of platform-specific issues
- **Configuration System**: Flexible JSON-based configuration
- **Logging**: Comprehensive logging for debugging and monitoring

## Target Use Cases

### Primary Use Cases
1. **Screen Recording and Presentations**: Show keystrokes during screen recordings or live presentations
2. **Educational Content**: Demonstrate keyboard shortcuts and mouse interactions in tutorials
3. **Accessibility**: Help users with visual feedback for their input actions
4. **Debugging**: Visualize input events during application development or testing

### Secondary Use Cases
1. **Gaming Streams**: Show controller inputs during gaming streams
2. **Training Materials**: Create interactive training content
3. **Accessibility Testing**: Test applications for keyboard navigation
4. **User Research**: Observe user interaction patterns

## Technical Architecture

### High-Level Architecture
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   KeyListener   │    │  MouseListener  │    │  DisplayWindow  │
│                 │    │                 │    │                 │
│ - Captures keys │    │ - Captures      │    │ - show_text()   │
│ - Formats keys  │    │   mouse clicks  │    │   (TextSink)    │
│ - Filters keys  │    │ - Formats       │    │ - Manages UI    │
└─────────┬───────┘    │   click+pos     │    │ - Handles fade  │
          │ show_text   └─────────┬───────┘    └─────────▲───────┘
          │                       │ show_text            │
          └───────────────────────┴──────────────────────┘
                                 │ (constructs & connects)
                    ┌─────────────▼─────────────┐
                    │ application.py (Keycast)  │
                    │                           │
                    │ - Orchestrates components │
                    │ - Handles signals         │
                    │ - Manages lifecycle       │
                    └───────────────────────────┘
```
> `main.py`, `cli.py`, and `__main__.py` are thin entry points that call `Keycast().run()`.

### Component Responsibilities

#### DisplayWindow
- Manages the Tkinter overlay window
- Implements the `TextSink` protocol (`show_text`), marshalling updates onto the Tk loop
- Manages fade-out effects (via `root.after`) and event limiting
- Provides customizable styling options

#### KeyListener
- Captures global keyboard events using pynput
- Formats key names for display
- Filters keys based on user configuration
- Handles platform-specific key mappings

#### MouseListener
- Captures global mouse click events using pynput
- Formats mouse button names
- Optionally captures click positions
- Filters mouse events based on configuration

#### Keycast (`application.py`)
- Orchestrates all components and connects each listener's `show_text` to the window
- Handles application lifecycle (`start` / `stop` / `run`; `stop` is idempotent)
- Manages signal handling for graceful shutdown
- Loads settings and configures logging
- Reached through thin entry points: `main.py`, `cli.py`, `__main__.py`

## Technology Stack

### Core Technologies
- **Python 3.14+**: Primary programming language
- **pynput**: Cross-platform input monitoring library
- **Tkinter**: GUI framework for display window
- **Pydantic**: Settings validation and configuration management
- **uv**: Modern Python package management

### Development Tools
- **pytest**: Testing framework
- **unittest.mock**: Mocking framework for tests
- **logging**: Built-in logging system

### Platform Support
- **macOS**: Full support with accessibility permissions
- **Linux**: Full support with X11/Wayland
- **Windows**: Full support with Windows API

## Project Structure

```
keycast/
├── src/keycast/              # Main source code
│   ├── __init__.py          # Package initialization
│   ├── __main__.py          # `python -m keycast` entry point
│   ├── application.py       # Keycast orchestrator (lifecycle + wiring)
│   ├── cli.py               # Typer CLI entry point
│   ├── main.py              # main(): constructs and runs Keycast
│   ├── display.py           # Display window implementation
│   ├── listeners.py         # Input event listeners + TextSink protocol
│   ├── settings.py          # Pydantic settings configuration
│   └── logging_setup.py     # Logging configuration
├── tests/                   # Test suite (one module per source module)
├── docs/                    # Documentation
│   ├── ARCHITECTURE.md      # Architecture documentation
│   ├── API.md              # API documentation
│   ├── DESIGN_DECISIONS.md  # Design decisions
│   └── PROJECT_OVERVIEW.md  # This file
├── pyproject.toml           # Project configuration
├── README.md               # User documentation
└── uv.lock                 # Dependency lock file
```

## Development Workflow

### Getting Started
1. Clone the repository
2. Install dependencies with `uv sync`
3. Install development dependencies with `uv sync --extra dev`
4. Run tests with `uv run pytest`
5. Run the application with `uv run keycast`

### Development Process
1. **Feature Development**: Create feature branches for new functionality
2. **Testing**: Write tests for all new features
3. **Documentation**: Update documentation for new features
4. **Code Review**: Submit pull requests for review
5. **Integration**: Merge after review and testing

### Quality Assurance
- **Test Coverage**: Comprehensive unit tests with mocking
- **Code Quality**: Type hints, docstrings, and clean code practices
- **Documentation**: Comprehensive documentation for all components
- **Cross-platform Testing**: Test on multiple platforms

## Configuration System

### Configuration Hierarchy
1. **Default Values**: Sensible defaults defined in Pydantic models
2. **Configuration File**: User-customizable JSON configuration with validation (`~/.keycast/config.json`)

The JSON file is the only override source; constructor kwargs and environment
variables are intentionally ignored (`Settings.settings_customise_sources`).

### Configuration Categories
- **Display Settings**: Window appearance, position, colors, fonts, behavior
- **Keyboard Settings**: Enable toggle, key filtering, custom mappings
- **Mouse Settings**: Enable toggle, click display, position tracking, button mappings
- **Logging Settings**: Log levels, formatting, file output, rotation

## Performance Characteristics

### Resource Usage
- **Memory**: Bounded by event storage (configurable limit)
- **CPU**: Minimal overhead for event processing
- **Display**: Efficient Tkinter rendering with transparency

### Optimization Strategies
- **Event Limiting**: Maximum number of displayed events
- **Efficient Filtering**: Early filtering of unwanted events
- **Loop-driven fade**: Fade cleanup runs on the Tk event loop (`root.after`), no extra thread
- **Minimal Dependencies**: Lightweight library choices

## Security and Privacy

### Privacy Protection
- **Local Processing**: All input processing happens locally
- **No Input Telemetry**: Captured keystrokes and clicks never leave the machine
- **Single, Optional Network Call**: The only outbound request is the update
  check against the GitHub Releases API (≤ once/day, no input data sent); it is
  opt-out via `check_for_updates` and fails silently offline. See
  [ADR-002](adr/002-update-check.md).
- **No Persistent Storage**: Events not saved to disk
- **User Control**: User controls what events are displayed

### Security Considerations
- **Permission-based**: Respects platform permission systems
- **No External Dependencies**: Minimal attack surface
- **Input Validation**: Proper validation of all inputs
- **Error Handling**: Secure error handling without information leakage

## Testing Strategy

### Test Coverage
- **Unit Tests**: Individual component testing with comprehensive mocking
- **Integration Tests**: Component interaction testing
- **Mock Strategy**: Complete mocking of external dependencies

### Test Categories
1. **Display Tests**: Tkinter window behavior and event display
2. **Listener Tests**: Input event capture and formatting
3. **Application Tests**: Orchestrator wiring, lifecycle, and shutdown
4. **CLI Tests**: Console commands (`version`, `info`) and launch path
5. **Settings Tests**: Validation, defaults, and config recovery
6. **Logging Tests**: Logging configuration
7. **Main Tests**: Entry-point delegation

### Testing Tools
- **pytest**: Primary testing framework
- **unittest.mock**: Mocking framework for external dependencies
- **Coverage**: Test coverage analysis

## Deployment and Distribution

### Distribution Method
- **PyPI**: Standard Python package (`uvx keycast`, `pipx install keycast`), exposing the `keycast` console script
- **Pre-built apps**: signed-less `.dmg` / `keycast-windows.zip` bundles and a `keycast-setup.exe` installer attached to each GitHub release
- **Homebrew**: a [tap](https://github.com/hasansezertasan/homebrew-tap) shipping a cask (macOS app) and a formula (CLI)
- **Scoop**: a [bucket](https://github.com/hasansezertasan/scoop-bucket) shipping `keycast` (app) and `keycast-pipx` (CLI) manifests
- **Cross-platform**: Works on all supported platforms

### Installation Requirements
- **Python 3.14+**: Modern Python with type hints
- **Platform Permissions**: Accessibility permissions on macOS
- **Core Dependencies**: pynput, pydantic, pydantic-settings, pydantic-extra-types
- **Optional Dependencies**: Tkinter for GUI (usually included with Python)

## Future Roadmap

### Planned Features
1. **Configuration UI**: GUI-based configuration management
2. **Plugin System**: Extensible architecture for custom event handlers
3. **Multiple Displays**: Support for multiple monitor setups
4. **Event Recording**: Optional event logging and playback
5. **Custom Themes**: Advanced theming and styling options

### Potential Enhancements
1. **Web Interface**: Browser-based configuration and monitoring
2. **Mobile Support**: Companion mobile app for remote monitoring
3. **Cloud Integration**: Optional cloud-based configuration sync
4. **Advanced Analytics**: Usage statistics and patterns
5. **Integration APIs**: APIs for integration with other tools

## Community and Contribution

### Contribution Guidelines
1. **Code Style**: Follow Python best practices and type hints
2. **Testing**: Write tests for all new functionality
3. **Documentation**: Update documentation for changes
4. **Platform Testing**: Test on multiple platforms when possible

### Development Environment
- **Python 3.14+**: Required for development
- **uv**: Package management and build system
- **pytest**: Testing framework
- **IDE Support**: Works with any Python IDE or editor

## License and Legal

### License
- **MIT License**: Open source with permissive licensing
- **Commercial Use**: Allowed for commercial and personal use
- **Modification**: Allowed with attribution

### Dependencies
- **pynput**: MIT License
- **pydantic**: MIT License
- **pydantic-settings**: MIT License
- **pydantic-extra-types**: MIT License
- **Tkinter**: Part of Python standard library
- **pytest**: MIT License (development dependency)

## Support and Maintenance

### Support Channels
- **GitHub Issues**: Bug reports and feature requests
- **Documentation**: Comprehensive documentation in the docs/ folder
- **Community**: Open source community support

### Maintenance Strategy
- **Regular Updates**: Regular dependency updates and security patches
- **Platform Support**: Maintain cross-platform compatibility
- **Documentation**: Keep documentation up to date
- **Testing**: Maintain comprehensive test coverage

## Metrics and Analytics

### Key Metrics
- **Test Coverage**: Maintain high test coverage
- **Performance**: Monitor resource usage and response times
- **Cross-platform Compatibility**: Test on all supported platforms
- **User Feedback**: Monitor GitHub issues and community feedback

### Quality Indicators
- **Code Quality**: Type hints, docstrings, clean code
- **Documentation Quality**: Comprehensive and up-to-date documentation
- **Test Quality**: Reliable and comprehensive tests
- **User Experience**: Intuitive and responsive interface
