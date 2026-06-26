from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from antibitala.database.connection import DB_PATH, init_sqlite_database
from antibitala.sources.registry import list_data_sources, seed_data_sources
from antibitala.sources.technopark import fetch_and_store_technopark
from antibitala.exporters import export_companies
from antibitala.sources.geofabrik_osm import fetch_and_store_osm, load_osm_candidates

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


@main.command("fetch-technopark")
@click.option("--limit", type=int, default=None, help="Maximum records to fetch.")
def fetch_technopark(limit: int | None) -> None:
    """Fetch companies from Technopark Maroc."""
    init_sqlite_database()
    count = fetch_and_store_technopark(limit=limit)
    click.echo(f"Fetched and stored {count} Technopark records.")


@main.command("list-companies")
@click.option("--limit", type=int, default=20, help="Maximum companies to show.")
def list_companies(limit: int) -> None:
    """List companies stored in the local database."""
    from antibitala.database.connection import get_connection

    init_sqlite_database()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                company_id,
                company_name,
                city,
                region,
                sector_primary,
                trust_score,
                job_relevance_score,
                source_count
            FROM companies
            ORDER BY company_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        click.echo("No companies found yet.")
        return

    for row in rows:
        click.echo(
            f"{row['company_id']} | {row['company_name']} | "
            f"{row['city'] or '-'} | {row['sector_primary'] or '-'} | "
            f"trust={row['trust_score']} | relevance={row['job_relevance_score']} | "
            f"sources={row['source_count']}"
        )

@main.command("reset-source-data")
@click.argument("source_name")
def reset_source_data(source_name: str) -> None:
    """Delete companies and source links collected from one source."""
    from antibitala.database.connection import get_connection

    init_sqlite_database()

    with get_connection() as conn:
        company_ids = [
            row["company_id"]
            for row in conn.execute(
                """
                SELECT DISTINCT company_id
                FROM company_sources
                WHERE source_name = ?
                """,
                (source_name,),
            ).fetchall()
        ]

        if not company_ids:
            click.echo(f"No companies found for source: {source_name}")
            return

        placeholders = ",".join("?" for _ in company_ids)

        conn.execute(
            f"DELETE FROM company_sources WHERE company_id IN ({placeholders})",
            company_ids,
        )
        conn.execute(
            f"DELETE FROM companies WHERE company_id IN ({placeholders})",
            company_ids,
        )
        conn.commit()

    click.echo(f"Deleted {len(company_ids)} companies from source: {source_name}")

@main.command("export")
@click.option(
    "--format",
    "export_format",
    type=click.Choice(["csv", "excel", "xlsx"]),
    default="csv",
    show_default=True,
    help="Export format.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional output file path.",
)
def export_data(export_format: str, output_path: Path | None) -> None:
    """Export companies to CSV or Excel."""
    path = export_companies(
        export_format=export_format,
        output_path=output_path,
    )

    click.echo(f"Exported companies to: {path}")

@main.command("inspect-osm")
@click.option("--limit", type=int, default=20, show_default=True)
def inspect_osm(limit: int) -> None:
    """Inspect filtered OSM employer candidates before import."""
    candidates = load_osm_candidates(limit=limit)

    click.echo(f"Loaded {len(candidates)} OSM candidates.")

    for candidate in candidates:
        click.echo(
            " | ".join(
                [
                    candidate.company_name,
                    candidate.city or "",
                    candidate.sector_primary or "",
                    candidate.sector_secondary or "",
                    candidate.website or "",
                    candidate.public_email or "",
                    candidate.source_url,
                ]
            )
        )


@main.command("fetch-osm")
@click.option("--limit", type=int, default=None, help="Maximum OSM candidates to import.")
def fetch_osm(limit: int | None) -> None:
    """Import OSM employer candidates into the local database."""
    count = fetch_and_store_osm(limit=limit)
    click.echo(f"Fetched and stored {count} OSM employer candidates.")
