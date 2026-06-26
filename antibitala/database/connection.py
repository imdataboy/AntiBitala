from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
FINAL_DIR = DATA_DIR / "final"
DB_PATH = FINAL_DIR / "antibitala_morocco.sqlite"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_sqlite.sql"


def ensure_data_dirs() -> None:
    """Create required data directories."""
    (DATA_DIR / "raw").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "staging").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "final").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with useful defaults."""
    path = db_path or DB_PATH
    ensure_data_dirs()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_sqlite_database(db_path: Path | None = None) -> Path:
    """Initialize the final local SQLite database from schema_sqlite.sql."""
    path = db_path or DB_PATH
    ensure_data_dirs()

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with get_connection(path) as conn:
        conn.executescript(schema_sql)
        conn.commit()

    return path


def get_database_stats(db_path: Path | None = None) -> dict[str, int]:
    """Return simple database statistics for the app dashboard."""
    path = db_path or DB_PATH

    if not path.exists():
        return {
            "companies": 0,
            "company_sources": 0,
            "configured_sources": 0,
            "contacts": 0,
            "zones": 0,
        }

    with get_connection(path) as conn:
        stats = {
            "companies": conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
            "company_sources": conn.execute(
                "SELECT COUNT(*) FROM company_sources"
            ).fetchone()[0],
            "configured_sources": conn.execute(
                "SELECT COUNT(*) FROM data_sources"
            ).fetchone()[0],
            "contacts": conn.execute("SELECT COUNT(*) FROM company_contacts").fetchone()[0],
            "zones": conn.execute("SELECT COUNT(*) FROM zones").fetchone()[0],
        }

    return stats


def get_company_filter_options(db_path: Path | None = None) -> dict[str, list[str]]:
    """Return filter options for the app."""
    path = db_path or DB_PATH

    if not path.exists():
        return {
            "cities": [],
            "regions": [],
            "sectors": [],
        }

    with get_connection(path) as conn:
        cities = conn.execute(
            """
            SELECT DISTINCT city
            FROM companies
            WHERE city IS NOT NULL AND TRIM(city) != ''
            ORDER BY city
            """
        ).fetchall()

        regions = conn.execute(
            """
            SELECT DISTINCT region
            FROM companies
            WHERE region IS NOT NULL AND TRIM(region) != ''
            ORDER BY region
            """
        ).fetchall()

        sectors = conn.execute(
            """
            SELECT DISTINCT sector_primary
            FROM companies
            WHERE sector_primary IS NOT NULL AND TRIM(sector_primary) != ''
            ORDER BY sector_primary
            """
        ).fetchall()

    return {
        "cities": [row["city"] for row in cities],
        "regions": [row["region"] for row in regions],
        "sectors": [row["sector_primary"] for row in sectors],
    }


def search_companies(
    query: str | None = None,
    city: str | None = None,
    region: str | None = None,
    sector: str | None = None,
    has_website: bool = False,
    has_email: bool = False,
    has_phone: bool = False,
    has_zone_link: bool = False,
    limit: int = 200,
    db_path: Path | None = None,
) -> list[sqlite3.Row]:
    """Search companies with optional filters."""
    sql = """
        SELECT
            c.company_id,
            c.company_name,
            c.city,
            c.region,
            c.country,
            c.sector_primary,
            c.sector_secondary,
            c.company_type,
            c.website,
            c.domain,
            c.career_page,
            c.contact_page,
            c.public_email,
            c.phone,
            c.address,
            c.trust_score,
            c.job_relevance_score,
            c.source_count,
            c.last_checked_date,
            zone_links.linked_zones,
            zone_links.max_zone_confidence,
            zone_links.zone_link_types
        FROM companies c
        LEFT JOIN (
            SELECT
                cz.company_id,
                GROUP_CONCAT(z.zone_name, '; ') AS linked_zones,
                MAX(cz.confidence_score) AS max_zone_confidence,
                GROUP_CONCAT(DISTINCT cz.link_type) AS zone_link_types
            FROM company_zones cz
            JOIN zones z ON z.zone_id = cz.zone_id
            GROUP BY cz.company_id
        ) zone_links ON zone_links.company_id = c.company_id
        WHERE 1 = 1
    """

    params: list[object] = []

    if query:
        like_query = f"%{query.strip()}%"
        sql += """
            AND (
                c.company_name LIKE ?
                OR c.city LIKE ?
                OR c.region LIKE ?
                OR c.sector_primary LIKE ?
                OR c.sector_secondary LIKE ?
                OR c.company_type LIKE ?
                OR c.website LIKE ?
                OR c.public_email LIKE ?
                OR c.address LIKE ?
                OR zone_links.linked_zones LIKE ?
            )
        """
        params.extend([like_query] * 10)

    if city and city != "All":
        sql += """
            AND (
                c.city = ?
                OR c.city LIKE ?
                OR c.city LIKE ?
                OR c.city LIKE ?
            )
        """
        params.extend(
            [
                city,
                f"{city};%",
                f"%;{city};%",
                f"%;{city}",
            ]
        )

    if region and region != "All":
        sql += " AND c.region = ?"
        params.append(region)

    if sector and sector != "All":
        sql += " AND c.sector_primary LIKE ?"
        params.append(f"%{sector}%")

    if has_website:
        sql += " AND c.website IS NOT NULL AND TRIM(c.website) != ''"

    if has_email:
        sql += " AND c.public_email IS NOT NULL AND TRIM(c.public_email) != ''"

    if has_phone:
        sql += " AND c.phone IS NOT NULL AND TRIM(c.phone) != ''"

    if has_zone_link:
        sql += " AND zone_links.linked_zones IS NOT NULL"

    sql += """
        ORDER BY
            CASE WHEN zone_links.linked_zones IS NOT NULL THEN 1 ELSE 0 END DESC,
            c.job_relevance_score DESC,
            c.trust_score DESC,
            c.source_count DESC,
            c.company_name
        LIMIT ?
    """
    params.append(limit)

    with get_connection(db_path) as conn:
        return conn.execute(sql, params).fetchall()