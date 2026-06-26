"""keycast CLI application."""

import platform

import typer

from keycast import __version__

app = typer.Typer(
    name="keycast",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch the keycast overlay when no subcommand is given.

    Run the visualizer:
        keycast

    Subcommands (``version``, ``info``) still run as usual.
    """
    if ctx.invoked_subcommand is not None:
        # A subcommand (version/info) is running: surface a cached "update
        # available" notice on stderr so it never corrupts the parseable stdout
        # of `version`/`info`. The GUI launch path notifies via the overlay
        # instead (see Keycast.start), so it is handled there, not here.
        # Note: the notice is read from cache (no network here). The background
        # refresh that *populates* that cache is a daemon thread, so a short-lived
        # CLI process usually exits before it finishes — the cache is realistically
        # refreshed by a long-lived GUI run instead. This is the deliberate
        # npm-style tradeoff from ADR-002 (keeps `version`/`info` instant).
        from keycast.updates import notify_pending_update

        notify_pending_update(notify=lambda message: typer.echo(message, err=True))
        return
    # Import lazily: pulls in tkinter/pynput, which the lightweight `version`
    # and `info` subcommands should not pay for.
    from keycast.main import main as run_app

    run_app()


@app.command(name="version")
def show_version() -> None:
    """Show the current version number of keycast.

    Show the version number:
        keycast version

    Example output:
        0.1.0
    """
    typer.echo(__version__)


@app.command()
def info() -> None:
    """Display information about the keycast application.

    Show application information:
        keycast info

    Output format (actual values reflect the host):
        Application Version: <version>
        Python Version: <python-version> (<implementation>)
        Platform: <system>
        Install source: <how keycast was installed>
    """
    from keycast.updates import detect_install_source, install_source_label

    python_version = platform.python_version()
    python_implementation = platform.python_implementation()
    typer.echo(f"Application Version: {__version__}")
    typer.echo(f"Python Version: {python_version} ({python_implementation})")
    typer.echo(f"Platform: {platform.system()}")
    typer.echo(f"Install source: {install_source_label(detect_install_source())}")
