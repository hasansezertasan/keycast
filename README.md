# keycast

A cross-platform keystroke and mouse click visualizer built in Python.

## Features

- **Cross-platform support**: Works on macOS, Linux, and Windows
- **Keyboard visualization**: Shows keystrokes in real-time with customizable formatting
- **Mouse click visualization**: Displays mouse clicks with optional position information
- **Transparent overlay**: Semi-transparent window that stays on top (when Tkinter is available)
- **Configurable display**: Customize colors, fonts, position, and behavior
- **Key mapping**: Customizable key name mappings for better display
- **Fade effects**: Events fade out after a configurable duration
- **Graceful error handling**: Handles permission issues and missing dependencies gracefully

## Installation

### Desktop app (recommended)

Pre-built, double-click applications are attached to each
[GitHub release](https://github.com/hasansezertasan/keycast/releases/latest):

- **macOS** — download `keycast.dmg`, open it, and drag **keycast** to your
  Applications folder. The build is not yet code-signed or notarized, so the
  first launch is blocked by Gatekeeper: right-click the app and choose **Open**,
  then confirm once. You will also be prompted to grant Accessibility and Input
  Monitoring permission (see [macOS](#macos) below).
- **Windows** — download `keycast-setup.exe` and run it. The installer lets you
  choose a per-user install (no admin) or a per-machine install (all users), adds
  a Start Menu shortcut, and registers an uninstaller in **Settings → Apps**.
  Prefer no install? Download `keycast-windows.zip` instead, extract it anywhere,
  and run `keycast.exe` from the extracted folder. Either build is unsigned, so
  Windows SmartScreen may warn on first run: click **More info → Run anyway**.

### Homebrew

keycast ships through a Homebrew [tap](https://github.com/hasansezertasan/homebrew-tap)
as both a **cask** (the macOS `.app`) and a **formula** (the CLI):

```bash
# macOS app (GUI) — installs keycast.app into /Applications
brew install --cask hasansezertasan/tap/keycast

# CLI (keycast version, keycast info, run from a terminal)
brew install hasansezertasan/tap/keycast
```

The cask is the double-click app; the formula is the terminal tool. On macOS the
cask build is unsigned, so the same Gatekeeper and permission steps as the
[Desktop app](#desktop-app-recommended) apply on first launch. Upgrade later with
`brew upgrade --cask keycast` (cask) or `brew upgrade keycast` (formula).

### Scoop

On Windows, keycast ships through a
[Scoop](https://scoop.sh) bucket ([`hasansezertasan/scoop-bucket`](https://github.com/hasansezertasan/scoop-bucket)).
Mirroring the Homebrew cask/formula split, it carries **two manifests** — Scoop
has no cask/formula namespace, so each is a distinct installable name. Add the
bucket once, then install either:

```powershell
scoop bucket add keycast https://github.com/hasansezertasan/scoop-bucket

# App (GUI) — the keycast.exe bundle, shimmed onto your PATH
scoop install keycast

# CLI — installed through pipx (keycast version, keycast info)
scoop install keycast-pipx
```

`keycast` is the packaged app; `keycast-pipx` is the terminal tool (it installs
*via* pipx, so `keycast info` reports `Install source: pipx`). Upgrade later by
name — `scoop update keycast` for the app or `scoop update keycast-pipx` for the
CLI (add `sudo … -g` for a global `-g` install).

### From PyPI

If you already have Python 3.14+ and [uv](https://docs.astral.sh/uv/):

```bash
uvx keycast
```

## Usage

### Basic Usage

Simply run the application:

```bash
uv run keycast
```

The application will start and display a transparent overlay window that shows your keystrokes and mouse clicks in real-time.

### Stopping the Application

Press `Ctrl+C` in the terminal to stop the application gracefully.

### Platform-Specific Permissions

#### macOS

On macOS, you'll need to grant accessibility permissions to your terminal or IDE:

1. Go to **System Preferences** > **Security & Privacy** > **Privacy** > **Accessibility**
2. Add your terminal application (Terminal.app, iTerm2, etc.) or IDE to the list.
3. Make sure the checkbox is checked.

#### Windows

Windows usually works without an explicit input-permission prompt.

#### Startup input status

On every launch keycast logs a structured `startup_input_status` event, and —
unless `show_startup_status` is `false` or the app starts minimized — briefly
shows a one-line summary on the overlay so you can immediately tell whether
capture is live:

```
Input status — Keyboard: OK, Mouse: Permission needed
```

Each source shows one of: `OK` (capturing), `Off` (disabled in settings),
`Permission needed` (macOS reports the input permission is denied),
`Not capturing` (the listener failed to start for another reason — see the log),
or `Unknown`. On macOS the label is informed by a best-effort permission
precheck; on other platforms it reflects whether the listener started. Suppress
the overlay line with the `show_startup_status` option below.

## Configuration

keycast uses a JSON configuration file with Pydantic-based settings validation. You do not need to manually create this file—the application will automatically create it if it doesn't exist.

- **All platforms**: `~/.keycast/config.json`

### Configuration Options

#### Display Settings

```json
{
  "display": {
    "width": 400,
    "height": 100,
    "x_position": "center",
    "y_position": 50,
    "background_color": "black",
    "text_color": "white",
    "font_family": "Arial",
    "font_size": 16,
    "font_weight": "bold",
    "alpha": 0.8,
    "always_on_top": true,
    "draggable": false,
    "fade_duration_ms": 2000,
    "max_events": 5
  }
}
```

#### Keyboard Settings

```json
{
  "keyboard": {
    "show_modifier_keys": true,
    "show_function_keys": true,
    "show_special_keys": true,
    "key_mappings": {
      "ctrl_l": "Control Left",
      "space": "Space Bar",
      "enter": "Enter"
    }
  }
}
```

#### Mouse Settings

```json
{
  "mouse": {
    "show_mouse_clicks": true,
    "show_mouse_position": false,
    "button_names": {
      "Button.left": "Left Click",
      "Button.right": "Right Click"
    }
  }
}
```

#### Logging Settings

```json
{
  "logging": {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file_path": "/Users/you/.keycast/main.log",
    "max_file_size_mb": 10,
    "backup_count": 5
  }
}
```

> `file_path` **defaults to `~/.keycast/main.log`** (shown above as an absolute
> path; `~` is not expanded in the config). Set it to `null` to log to the
> console only. When a file is used, it rotates at `max_file_size_mb`, keeping
> `backup_count` rotated copies.

#### General Settings

```json
{
  "debug": false,
  "start_minimized": false,
  "auto_start": true,
  "check_for_updates": true,
  "show_startup_status": true
}
```

> These are top-level flags (not sections).

> `check_for_updates` — when `true` (default), keycast checks the GitHub
> Releases API at most once a day and shows a non-blocking notice if a newer
> version exists (see [Updates](#updates)). Set it to `false` to disable all
> automatic update checks (offline and privacy-respecting). The check fails
> silently when offline.

> `show_startup_status` — when `true` (default), keycast shows a short startup
> line on the overlay with keyboard/mouse capture status (`OK`, `Off`,
> `Permission needed`, `Not capturing`, or `Unknown`). The structured
> `startup_input_status` log event is written regardless of this flag; setting
> it to `false` only suppresses the on-overlay line. The line is also skipped on
> a minimized start.

> `debug` — when `true`, keycast surfaces verbose diagnostics regardless of
> `logging.level`; a quick switch for troubleshooting without editing the logging
> block. Defaults to `false`.

> `auto_start` — when `true` (default), the input listeners start on launch. Set
> it to `false` as a master switch to start with the overlay visible but
> capturing nothing, regardless of `keyboard.enabled` / `mouse.enabled`.

> `start_minimized` — when `true`, the overlay starts hidden and appears the
> first time a key or click is captured. Requires `auto_start` to be `true`
> (otherwise nothing is captured and the overlay would never appear, so the
> combination is rejected). If no input source is actually live at startup —
> both listeners disabled, or they fail to start (e.g. missing OS input
> permissions) — keycast keeps the overlay **visible** rather than hiding a
> window it could never restore. Defaults to `false`.

> Enabling/disabling each listener is controlled per-component via
> `keyboard.enabled` and `mouse.enabled` (see the Keyboard/Mouse settings above).

## Updates

> In-place self-update of the downloaded app is a **future phase**; today keycast
> *notifies* and points you at the right update command. See
> [ADR-002](docs/adr/002-update-check.md).

keycast supports several install channels, and the right way to update depends
on how you installed it. keycast detects its install source and recommends the
matching action — it never tries to update something your package manager owns.

| You installed via | keycast will… |
|---|---|
| `pipx` / `uv tool` / `uvx` / `pip` | suggest the matching upgrade command (e.g. `pipx upgrade keycast`) |
| Homebrew **formula** (CLI) | suggest `brew upgrade keycast` |
| Homebrew **cask** (the macOS app) | suggest `brew upgrade --cask keycast` |
| the **Windows installer** (`keycast-setup.exe`) | point you to the latest release to download the new installer |
| **Scoop** (`scoop install keycast`) | suggest `scoop update keycast` — or `sudo scoop update keycast -g` for a global (`-g`) install |
| the **Microsoft Store** | tell you updates are delivered automatically by the Store — nothing to run |
| a manual [GitHub Release](https://github.com/hasansezertasan/keycast/releases/latest) download (the `.zip`) | point you to the latest release (and, in a future phase, update itself in place) |

- **Automatic, in the background:** keycast checks the GitHub Releases API at
  most once per day. The check runs on its own — there is no command to run. A
  newer version shows as a brief, non-blocking overlay notice (GUI) or a single
  stderr line (`keycast version` / `info`). Controlled by `check_for_updates`
  (default `true`); set it to `false` to disable.
- **Install source:** `keycast info` shows how keycast was installed (e.g.
  `Install source: Homebrew cask`), which determines the update advice above.
- **Offline / privacy:** checks only contact GitHub when enabled, time out
  quickly, and fail silently when offline. No telemetry is collected.

## Development

### Running Tests

```bash
# Run all tests
uv run python -m pytest tests/

# Run specific test file
uv run python -m pytest tests/test_display.py

# Run with verbose output
uv run python -m pytest tests/ -v
```

### Project Structure

```
keycast/
├── src/keycast/
│   ├── __init__.py      # Package initialization
│   ├── __main__.py      # `python -m keycast` entry point
│   ├── application.py   # Keycast orchestrator (lifecycle + wiring)
│   ├── cli.py           # Typer CLI entry point (`keycast` command)
│   ├── main.py          # main(): constructs and runs Keycast
│   ├── listeners.py     # Input event listeners + TextSink protocol
│   ├── display.py       # Tkinter display window
│   ├── settings.py      # Pydantic settings configuration
│   └── logging_setup.py # Logging configuration
├── tests/               # One test module per source module
├── docs/                # Comprehensive documentation
│   ├── README.md        # Documentation index
│   ├── ARCHITECTURE.md  # Architecture documentation
│   ├── API.md          # API documentation
│   ├── DESIGN_DECISIONS.md # Design decisions
│   └── PROJECT_OVERVIEW.md # Project overview
├── pyproject.toml       # Project configuration
└── README.md           # This file
```

### Documentation

Comprehensive documentation is available in the `docs/` directory:

- **[Documentation Index](docs/README.md)** - Overview of all documentation
- **[Project Overview](docs/PROJECT_OVERVIEW.md)** - Complete project overview
- **[Architecture Documentation](docs/ARCHITECTURE.md)** - Technical architecture details
- **[API Documentation](docs/API.md)** - Complete API reference
- **[Design Decisions](docs/DESIGN_DECISIONS.md)** - Design rationale and trade-offs

### Adding New Features

1. Create a new branch for your feature
2. Implement the feature with tests
3. Update documentation if needed
4. Submit a pull request

## Troubleshooting

### Common Issues

#### "Permission denied" or "This process is not trusted" errors on macOS

This is the most common issue on macOS. You need to grant accessibility permissions:

1. **Go to System Preferences** (or System Settings on newer macOS versions)
2. **Navigate to Security & Privacy > Privacy > Accessibility**
3. **Click the lock icon** to make changes (enter your password)
4. **Add your terminal application** (Terminal.app, iTerm2, etc.) or IDE to the list
5. **Make sure the checkbox is checked** next to your application
6. **Restart keycast**

If you're still having issues, try:
- Restart your terminal/IDE after granting permissions
- Make sure you're running keycast from the same terminal/IDE that you granted permissions to
- On some systems, you may need to restart your computer after granting permissions

#### Window doesn't appear

- Check if the application is running in the background
- Set `logging.level` to `"DEBUG"` (and optionally `logging.file_path`) in the config to see detailed messages; logs default to `~/.keycast/main.log`
- Ensure your display settings are correct

#### Keys not showing

- Check that `keyboard.enabled: true` in your config
- Verify the key filtering settings (`show_modifier_keys`, `show_function_keys`, etc.)

#### Mouse clicks not showing

- Check that `mouse.enabled: true` in your config
- Verify that `show_mouse_clicks: true` in the mouse settings

### Testing Permissions

The "This process is not trusted!" messages you see are warnings from pynput, but they don't necessarily mean the permissions aren't working. The actual input monitoring should still function properly.

If you want to verify that permissions are working, try running keycast and see if it captures your keystrokes and mouse clicks. If it's not working, follow the accessibility permission steps above.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
