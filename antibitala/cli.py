from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from antibitala.database.connection import DB_PATH, init_sqlite_database
from antibitala.sources.registry import list_data_sources, seed_data_sources

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


@main.command("seed-sources")
def seed_sources() -> None:
    """Seed Morocco data source registry."""
    init_sqlite_database()
    count = seed_data_sources()
    click.echo(f"Seeded {count} data sources.")


@main.command("list-sources")
@click.option("--enabled-only", is_flag=True, help="Show only enabled sources.")
def list_sources(enabled_only: bool) -> None:
    """List configured data sources."""
    init_sqlite_database()
    sources = list_data_sources(enabled_only=enabled_only)

    if not sources:
        click.echo("No data sources found. Run: uv run antibitala seed-sources")
        return

    for source in sources:
        enabled_icon = "✅" if source["enabled"] else "❌"
        click.echo(
            f"{enabled_icon} {source['source_key']} | "
            f"{source['source_name']} | "
            f"{source['coverage_scope']} | "
            f"{source['reliability_level']}"
        )
