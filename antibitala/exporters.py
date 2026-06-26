from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from antibitala.database.connection import DB_PATH, get_connection


EXPORTS_DIR = Path("data/exports")


def get_export_dataframe() -> pd.DataFrame:
    """Return the main company export dataframe."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}. Run: uv run antibitala init-db"
        )

    sql = """
        SELECT
            company_id,
            company_name,
            city,
            region,
            country,
            sector_primary,
            sector_secondary,
            company_type,
            website,
            domain,
            career_page,
            contact_page,
            public_email,
            phone,
            address,
            trust_score,
            job_relevance_score,
            source_count,
            first_seen_date,
            last_seen_date,
            last_checked_date,
            status
        FROM companies
        ORDER BY region, city, company_name
    """

    with get_connection(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn)


def export_companies(export_format: str = "csv", output_path: Path | None = None) -> Path:
    """Export companies to CSV or Excel."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    df = get_export_dataframe()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if export_format == "csv":
        path = output_path or EXPORTS_DIR / f"antibitala_companies_{timestamp}.csv"
        df.to_csv(path, index=False)
        return path

    if export_format in {"excel", "xlsx"}:
        path = output_path or EXPORTS_DIR / f"antibitala_companies_{timestamp}.xlsx"
        df.to_excel(path, index=False, sheet_name="companies")
        return path

    raise ValueError("Unsupported export format. Use: csv or excel.")
