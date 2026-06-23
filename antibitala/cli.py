from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from antibitala.database.connection import DB_PATH, init_sqlite_database


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """AntiBitala command line interface."""
    if ctx.invoked_subcommand is None:
        run_app()


@main.command("app")
def run_app() -> None:
    """Run the local Streamlit app."""
    app_path = Path(__file__).parent / "app.py"

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)],
        check=True,
    )


@main.command("init-db")
def init_db() -> None:
    """Initialize the local Morocco SQLite database."""
    db_path = init_sqlite_database()
    click.echo(f"Database initialized: {db_path}")


@main.command("db-path")
def db_path() -> None:
    """Print the local database path."""
    click.echo(DB_PATH)
