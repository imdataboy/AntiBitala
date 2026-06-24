from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml

from antibitala.database.connection import get_connection


SOURCE_REGISTRY_PATH = Path(__file__).resolve().parent / "morocco_sources.yaml"


def load_source_registry(path: Path | None = None) -> list[dict[str, Any]]:
    """Load Morocco source registry from YAML."""
    registry_path = path or SOURCE_REGISTRY_PATH

    with registry_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    sources = data.get("sources", [])

    if not isinstance(sources, list):
        raise ValueError("Invalid source registry format: 'sources' must be a list.")

    return sources


def seed_data_sources() -> int:
    """Insert or update configured data sources in SQLite."""
    sources = load_source_registry()

    sql = """
    INSERT INTO data_sources (
        source_key,
        source_name,
        source_type,
        country,
        region,
        city,
        sector,
        coverage_scope,
        reliability_level,
        access_method,
        base_url,
        enabled,
        update_frequency,
        notes,
        updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(source_key) DO UPDATE SET
        source_name = excluded.source_name,
        source_type = excluded.source_type,
        country = excluded.country,
        region = excluded.region,
        city = excluded.city,
        sector = excluded.sector,
        coverage_scope = excluded.coverage_scope,
        reliability_level = excluded.reliability_level,
        access_method = excluded.access_method,
        base_url = excluded.base_url,
        enabled = excluded.enabled,
        update_frequency = excluded.update_frequency,
        notes = excluded.notes,
        updated_at = CURRENT_TIMESTAMP;
    """

    with get_connection() as conn:
        for source in sources:
            conn.execute(
                sql,
                (
                    source["source_key"],
                    source["source_name"],
                    source["source_type"],
                    source.get("country", "Morocco"),
                    source.get("region"),
                    source.get("city"),
                    source.get("sector"),
                    source["coverage_scope"],
                    source["reliability_level"],
                    source.get("access_method"),
                    source.get("base_url"),
                    int(bool(source.get("enabled", True))),
                    source.get("update_frequency", "quarterly"),
                    source.get("notes"),
                ),
            )

        conn.commit()

    return len(sources)


def list_data_sources(enabled_only: bool = False) -> list[sqlite3.Row]:
    """List configured data sources."""
    query = """
        SELECT
            source_key,
            source_name,
            source_type,
            region,
            city,
            sector,
            coverage_scope,
            reliability_level,
            enabled
        FROM data_sources
    """

    if enabled_only:
        query += " WHERE enabled = 1"

    query += " ORDER BY coverage_scope, source_name"

    with get_connection() as conn:
        return conn.execute(query).fetchall()
