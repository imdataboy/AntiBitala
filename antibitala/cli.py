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
from antibitala.sources.industrial_zones import (
    import_industrial_zones,
    list_zones,
    migrate_zone_schema,
    validate_zone_coverage,
)
from antibitala.sources.industrial_estate import (
    import_industrial_estate_zones,
    inspect_industrial_estate_zones,
)


from antibitala.sources.company_zone_linker import (
    get_company_zone_link_stats,
    link_companies_to_zones,
    migrate_company_zone_schema,
    sample_company_zone_links,
)




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



@main.command("import-zones")
def import_zones() -> None:
    """Import national industrial/economic zones."""
    count = import_industrial_zones()
    click.echo(f"Imported {count} industrial/economic zones.")


@main.command("list-zones")
def list_zones_command() -> None:
    """List industrial/economic zones."""
    rows = list_zones()

    if not rows:
        click.echo("No zones found.")
        return

    for row in rows:
        click.echo(
            " | ".join(
                [
                    str(row["zone_id"]),
                    row["zone_name"],
                    row["region"] or "",
                    row["city"] or "",
                    row["zone_type"] or "",
                    row["operator"] or "",
                    row["verification_status"] or "",
                    row["source_url"] or "",
                ]
            )
        )

@main.command("validate-zone-coverage")
def validate_zone_coverage_command() -> None:
    """Validate zone coverage across Moroccan regions."""
    coverage = validate_zone_coverage()

    click.echo(
        f"Covered regions: {coverage['covered_count']}/{coverage['total_regions']}"
    )

    click.echo("\nCoverage by region:")
    coverage_by_region = coverage["coverage_by_region"]

    for region in coverage["covered_regions"]:
        click.echo(f"- {region}: {coverage_by_region.get(region, 0)}")

    missing_regions = coverage["missing_regions"]

    if missing_regions:
        click.echo("\nMissing regions:")
        for region in missing_regions:
            click.echo(f"- {region}")
    else:
        click.echo("\nNo missing regions.")

    extra_regions = coverage["extra_regions"]

    if extra_regions:
        click.echo("\nNon-canonical region names found:")
        for region in extra_regions:
            click.echo(f"- {region}")

@main.command("inspect-industrial-estate")
@click.option("--pages", type=int, default=2, show_default=True)
def inspect_industrial_estate(pages: int) -> None:
    """Inspect Industrial Estate Morocco zones before import."""
    zones = inspect_industrial_estate_zones(max_pages=pages)

    click.echo(f"Loaded {len(zones)} Industrial Estate zones.")

    for zone in zones:
        click.echo(
            " | ".join(
                [
                    zone.zone_name,
                    zone.region or "",
                    zone.city or "",
                    zone.zone_type,
                    zone.operator or "",
                    zone.source_url,
                ]
            )
        )


@main.command("import-industrial-estate")
@click.option("--pages", type=int, default=50, show_default=True)
def import_industrial_estate(pages: int) -> None:
    """Import official Industrial Estate Morocco zones."""
    count = import_industrial_estate_zones(max_pages=pages)
    click.echo(f"Imported {count} Industrial Estate zones.")

@main.command("migrate-zones")
def migrate_zones() -> None:
    """Add missing metadata columns to the zones table."""
    added_columns = migrate_zone_schema()

    if not added_columns:
        click.echo("Zones table already has all metadata columns.")
        return

    click.echo("Added zone metadata columns:")
    for column in added_columns:
        click.echo(f"- {column}")
        
        
        
@main.command("migrate-company-zones")
def migrate_company_zones() -> None:
    """Add missing metadata columns to the company_zones table."""
    added_columns = migrate_company_zone_schema()

    if not added_columns:
        click.echo("company_zones table already has all metadata columns.")
        return

    click.echo("Added company_zones metadata columns:")
    for column in added_columns:
        click.echo(f"- {column}")


@main.command("link-company-zones")
@click.option("--no-reset", is_flag=True, help="Do not delete old inferred links first.")
@click.option("--max-links-per-company", type=int, default=3, show_default=True)
@click.option("--limit", type=int, default=None, help="Limit companies for test runs.")
def link_company_zones(
    no_reset: bool,
    max_links_per_company: int,
    limit: int | None,
) -> None:
    """Infer company-zone links from city/region matching."""
    count = link_companies_to_zones(
        reset=not no_reset,
        max_links_per_company=max_links_per_company,
        limit=limit,
    )

    stats = get_company_zone_link_stats()

    click.echo(f"Inserted {count} company-zone links.")
    click.echo(f"Total company-zone links: {stats['total']}")

    for key, value in stats.items():
        if key == "total":
            continue

        click.echo(f"{key}: {value}")


@main.command("inspect-company-zone-links")
@click.option("--limit", type=int, default=30, show_default=True)
def inspect_company_zone_links(limit: int) -> None:
    """Inspect sample company-zone links."""
    rows = sample_company_zone_links(limit=limit)

    if not rows:
        click.echo("No company-zone links found.")
        return

    for row in rows:
        click.echo(
            " | ".join(
                [
                    row["company_name"],
                    row["company_city"] or "",
                    row["company_region"] or "",
                    row["sector_primary"] or "",
                    row["zone_name"],
                    row["zone_city"] or "",
                    row["zone_region"] or "",
                    str(row["confidence_score"]),
                    row["link_type"] or "",
                ]
            )
        )