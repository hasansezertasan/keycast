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
    """
    python_version = platform.python_version()
    python_implementation = platform.python_implementation()
    typer.echo(f"Application Version: {__version__}")
    typer.echo(f"Python Version: {python_version} ({python_implementation})")
    typer.echo(f"Platform: {platform.system()}")
