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
            "sources": 0,
            "contacts": 0,
            "zones": 0,
        }

    with get_connection(path) as conn:
        stats = {
            "companies": conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM company_sources").fetchone()[0],
            "contacts": conn.execute("SELECT COUNT(*) FROM company_contacts").fetchone()[0],
            "zones": conn.execute("SELECT COUNT(*) FROM zones").fetchone()[0],
        }

    return stats
