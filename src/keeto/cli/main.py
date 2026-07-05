"""Keeto CLI — implemented in Milestone 6 (issues #91–#99)."""

from __future__ import annotations

try:
    import typer
except ImportError as exc:
    raise ImportError("CLI requires typer. Install with: pip install keeto[dev]") from exc

app = typer.Typer(
    name="keeto",
    help="Keeto — AI observability for Python.",
    no_args_is_help=True,
)


@app.command()
def traces() -> None:
    """List recent captured traces."""
    typer.echo("keeto traces — coming in v1.0 (issue #92)")


@app.command()
def dashboard(mode: str = "tui") -> None:
    """Launch the Keeto dashboard."""
    typer.echo(f"keeto dashboard ({mode}) — coming in v1.0 (issue #93)")


@app.command()
def version() -> None:
    """Show the Keeto version."""
    from keeto._version import __version__
    typer.echo(f"keeto {__version__}")


if __name__ == "__main__":
    app()
