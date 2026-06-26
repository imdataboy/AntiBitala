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
    limit: int = 200,
    db_path: Path | None = None,
) -> list[sqlite3.Row]:
    """Search companies with simple filters."""
    path = db_path or DB_PATH

    if not path.exists():
        return []

    where_clauses = []
    params: list[object] = []

    if query:
        where_clauses.append(
            """
            (
                company_name LIKE ?
                OR normalized_name LIKE ?
                OR sector_primary LIKE ?
                OR sector_secondary LIKE ?
                OR city LIKE ?
                OR region LIKE ?
            )
            """
        )
        search_value = f"%{query.strip()}%"
        params.extend(
            [
                search_value,
                search_value,
                search_value,
                search_value,
                search_value,
                search_value,
            ]
        )

    if city and city != "All":
        where_clauses.append("city = ?")
        params.append(city)

    if region and region != "All":
        where_clauses.append("region = ?")
        params.append(region)

    if sector and sector != "All":
        where_clauses.append("sector_primary = ?")
        params.append(sector)

    if has_website:
        where_clauses.append("website IS NOT NULL AND TRIM(website) != ''")

    if has_email:
        where_clauses.append("public_email IS NOT NULL AND TRIM(public_email) != ''")

    if has_phone:
        where_clauses.append("phone IS NOT NULL AND TRIM(phone) != ''")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        SELECT
            company_id,
            company_name,
            city,
            region,
            sector_primary,
            sector_secondary,
            company_type,
            website,
            public_email,
            phone,
            trust_score,
            job_relevance_score,
            source_count,
            last_checked_date
        FROM companies
        {where_sql}
        ORDER BY job_relevance_score DESC, trust_score DESC, company_name ASC
        LIMIT ?
    """

    params.append(limit)

    with get_connection(path) as conn:
        return conn.execute(sql, params).fetchall()