from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from antibitala.database.connection import get_connection


ZONES_YAML_PATH = Path("antibitala/sources/morocco_industrial_zones.yaml")
MOROCCO_REGIONS = [
    "Casablanca-Settat",
    "Rabat-Salé-Kénitra",
    "Tanger-Tétouan-Al Hoceïma",
    "Marrakech-Safi",
    "Souss-Massa",
    "Fès-Meknès",
    "Oriental",
    "Béni Mellal-Khénifra",
    "Drâa-Tafilalet",
    "Guelmim-Oued Noun",
    "Laâyoune-Sakia El Hamra",
    "Dakhla-Oued Ed-Dahab",
]

ZONE_METADATA_COLUMNS = {
    "verification_status": "TEXT DEFAULT 'seed'",
    "last_verified_date": "TEXT",
    "notes": "TEXT",
    "updated_at": "TEXT",
}

@dataclass(frozen=True)
class ZoneCandidate:
    zone_name: str
    region: str | None
    city: str | None
    zone_type: str
    operator: str | None
    source_url: str
    latitude: float | None = None
    longitude: float | None = None
    verification_status: str = "seed"
    last_verified_date: str | None = None
    notes: str | None = None

def ensure_zone_metadata_columns(conn: sqlite3.Connection) -> list[str]:
    """Add zone metadata columns if the local database is older."""
    existing_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(zones)").fetchall()
    }

    added_columns: list[str] = []

    for column_name, column_definition in ZONE_METADATA_COLUMNS.items():
        if column_name in existing_columns:
            continue

        conn.execute(
            f"ALTER TABLE zones ADD COLUMN {column_name} {column_definition}"
        )
        added_columns.append(column_name)

    return added_columns


def migrate_zone_schema() -> list[str]:
    """Migrate the zones table for metadata/verification fields."""
    with get_connection() as conn:
        added_columns = ensure_zone_metadata_columns(conn)
        conn.commit()

    return added_columns

def load_zone_candidates(path: Path = ZONES_YAML_PATH) -> list[ZoneCandidate]:
    """Load industrial/economic zone candidates from YAML."""
    if not path.exists():
        raise FileNotFoundError(f"Zone seed file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}

    zones = payload.get("zones", [])

    candidates: list[ZoneCandidate] = []

    for zone in zones:
        zone_name = str(zone["zone_name"]).strip()
        source_url = str(zone["source_url"]).strip()

        if not zone_name or not source_url:
            continue

        candidates.append(
            ZoneCandidate(
                zone_name=zone_name,
                region=zone.get("region"),
                city=zone.get("city"),
                zone_type=zone.get("zone_type", "economic_zone"),
                operator=zone.get("operator"),
                source_url=source_url,
                latitude=zone.get("latitude"),
                longitude=zone.get("longitude"),
                verification_status=zone.get("verification_status", "seed"),
                last_verified_date=zone.get("last_verified_date"),
                notes=zone.get("notes"),
            )
        )

    return candidates


def upsert_zone(conn: sqlite3.Connection, candidate: ZoneCandidate) -> int:
    """Insert or update one zone and return zone_id."""
    existing = conn.execute(
        """
        SELECT zone_id
        FROM zones
        WHERE zone_name = ?
          AND COALESCE(city, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (candidate.zone_name, candidate.city),
    ).fetchone()

    if existing:
        zone_id = int(existing["zone_id"])

        conn.execute(
            """
            UPDATE zones
            SET
                region = COALESCE(?, region),
                city = COALESCE(?, city),
                zone_type = COALESCE(?, zone_type),
                operator = COALESCE(?, operator),
                source_url = COALESCE(?, source_url),
                latitude = COALESCE(?, latitude),
                longitude = COALESCE(?, longitude),
                verification_status = COALESCE(?, verification_status),
                last_verified_date = COALESCE(?, last_verified_date),
                notes = COALESCE(?, notes),
                updated_at = CURRENT_TIMESTAMP
            WHERE zone_id = ?
            """,
            (
                candidate.region,
                candidate.city,
                candidate.zone_type,
                candidate.operator,
                candidate.source_url,
                candidate.latitude,
                candidate.longitude,
                candidate.verification_status,
                candidate.last_verified_date,
                candidate.notes,
                zone_id,
            ),
        )

        return zone_id

    cursor = conn.execute(
        """
        INSERT INTO zones (
            zone_name,
            region,
            city,
            zone_type,
            operator,
            source_url,
            latitude,
            longitude,
            verification_status,
            last_verified_date,
            notes,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            candidate.zone_name,
            candidate.region,
            candidate.city,
            candidate.zone_type,
            candidate.operator,
            candidate.source_url,
            candidate.latitude,
            candidate.longitude,
            candidate.verification_status,
            candidate.last_verified_date,
            candidate.notes,
        ),
    )

    return int(cursor.lastrowid)


def import_industrial_zones() -> int:
    """Import national industrial/economic zones."""
    candidates = load_zone_candidates()

    imported = 0

    with get_connection() as conn:
        ensure_zone_metadata_columns(conn)
        for candidate in candidates:
            upsert_zone(conn, candidate)
            imported += 1

        conn.execute(
            """
            INSERT INTO update_log (
                source_name,
                records_added,
                records_updated,
                notes
            )
            VALUES (?, ?, 0, ?)
            """,
            (
                "morocco_industrial_zones_seed",
                imported,
                f"Imported zones from {ZONES_YAML_PATH}",
            ),
        )

        conn.commit()

    return imported


def list_zones() -> list[sqlite3.Row]:
    """Return zones ordered by region/city/name."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                zone_id,
                zone_name,
                region,
                city,
                zone_type,
                operator,
                source_url,
                verification_status,
                last_verified_date,
                notes
            FROM zones
            ORDER BY region, city, zone_name
            """
        ).fetchall()


def validate_zone_coverage() -> dict[str, object]:
    """Validate industrial/economic zone coverage across Moroccan regions."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT region, COUNT(*) AS total
            FROM zones
            WHERE region IS NOT NULL AND TRIM(region) != ''
            GROUP BY region
            ORDER BY region
            """
        ).fetchall()

    coverage_by_region = {row["region"]: int(row["total"]) for row in rows}

    covered_regions = [
        region for region in MOROCCO_REGIONS if coverage_by_region.get(region, 0) > 0
    ]

    missing_regions = [
        region for region in MOROCCO_REGIONS if coverage_by_region.get(region, 0) == 0
    ]

    extra_regions = [
        region for region in coverage_by_region if region not in MOROCCO_REGIONS
    ]

    return {
        "total_regions": len(MOROCCO_REGIONS),
        "covered_count": len(covered_regions),
        "covered_regions": covered_regions,
        "missing_regions": missing_regions,
        "extra_regions": extra_regions,
        "coverage_by_region": coverage_by_region,
    }
    
    
    
def get_zone_status_counts() -> dict[str, int]:
    """Return zone counts by verification status."""
    with get_connection() as conn:
        ensure_zone_metadata_columns(conn)

        rows = conn.execute(
            """
            SELECT
                COALESCE(verification_status, 'unknown') AS status,
                COUNT(*) AS total
            FROM zones
            GROUP BY COALESCE(verification_status, 'unknown')
            ORDER BY total DESC
            """
        ).fetchall()

    return {row["status"]: int(row["total"]) for row in rows}


def get_zone_region_summary() -> list[dict[str, object]]:
    """Return zone coverage summary for all Moroccan regions."""
    with get_connection() as conn:
        ensure_zone_metadata_columns(conn)

        rows = conn.execute(
            """
            SELECT
                region,
                COUNT(*) AS total_zones,
                SUM(
                    CASE
                        WHEN verification_status = 'seed' THEN 1
                        ELSE 0
                    END
                ) AS seed_zones,
                SUM(
                    CASE
                        WHEN verification_status = 'provisional_seed' THEN 1
                        ELSE 0
                    END
                ) AS provisional_seed_zones,
                SUM(
                    CASE
                        WHEN verification_status = 'verified' THEN 1
                        ELSE 0
                    END
                ) AS verified_zones,
                SUM(
                    CASE
                        WHEN verification_status = 'needs_review' THEN 1
                        ELSE 0
                    END
                ) AS needs_review_zones
            FROM zones
            WHERE region IS NOT NULL AND TRIM(region) != ''
            GROUP BY region
            """
        ).fetchall()

    by_region = {
        row["region"]: {
            "total_zones": int(row["total_zones"] or 0),
            "seed_zones": int(row["seed_zones"] or 0),
            "provisional_seed_zones": int(row["provisional_seed_zones"] or 0),
            "verified_zones": int(row["verified_zones"] or 0),
            "needs_review_zones": int(row["needs_review_zones"] or 0),
        }
        for row in rows
    }

    summary: list[dict[str, object]] = []

    for region in MOROCCO_REGIONS:
        values = by_region.get(
            region,
            {
                "total_zones": 0,
                "seed_zones": 0,
                "provisional_seed_zones": 0,
                "verified_zones": 0,
                "needs_review_zones": 0,
            },
        )

        summary.append(
            {
                "region": region,
                **values,
                "covered": values["total_zones"] > 0,
            }
        )

    return summary