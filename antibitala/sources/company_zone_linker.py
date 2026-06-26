from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from antibitala.database.connection import get_connection


COMPANY_ZONE_METADATA_COLUMNS = {
    "link_type": "TEXT DEFAULT 'unknown'",
    "evidence": "TEXT",
    "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT",
}


INVALID_CITY_KEYWORDS = {
    "rue",
    "avenue",
    "av",
    "boulevard",
    "bd",
    "lot",
    "residence",
    "résidence",
    "immeuble",
    "quartier",
    "hay",
    "route",
    "km",
    "bloc",
    "appartement",
    "etage",
    "étage",
    "magasin",
    "local",
}


@dataclass(frozen=True)
class CompanyZoneCandidate:
    company_id: int
    zone_id: int
    source_url: str | None
    confidence_score: int
    link_type: str
    evidence: str


def normalize_text(value: str | None) -> str:
    """Normalize text for matching city, region, and names."""
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9\s'-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()


def split_city_values(value: str | None) -> list[str]:
    """Split multi-city values such as Casablanca;Agadir."""
    if not value:
        return []

    parts = re.split(r"[;,|/]", str(value))
    return [part.strip() for part in parts if part.strip()]


def is_valid_city(value: str | None) -> bool:
    """Reject addresses, numbers, and noisy city values."""
    if not value:
        return False

    cleaned = str(value).strip()
    normalized = normalize_text(cleaned)

    if len(cleaned) < 2 or len(cleaned) > 45:
        return False

    if any(char.isdigit() for char in cleaned):
        return False

    words = re.findall(r"\b[\w'-]+\b", normalized)

    if len(words) > 4:
        return False

    if any(word in INVALID_CITY_KEYWORDS for word in words):
        return False

    return True


def ensure_company_zone_metadata_columns(conn: sqlite3.Connection) -> list[str]:
    """Add company_zones metadata columns if missing."""
    existing_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(company_zones)").fetchall()
    }

    added_columns: list[str] = []

    for column_name, column_definition in COMPANY_ZONE_METADATA_COLUMNS.items():
        if column_name in existing_columns:
            continue

        conn.execute(
            f"ALTER TABLE company_zones ADD COLUMN {column_name} {column_definition}"
        )
        added_columns.append(column_name)

    return added_columns


def migrate_company_zone_schema() -> list[str]:
    """Migrate company_zones table for metadata fields."""
    with get_connection() as conn:
        added_columns = ensure_company_zone_metadata_columns(conn)
        conn.commit()

    return added_columns


def sector_matches_zone(company: sqlite3.Row, zone: sqlite3.Row) -> bool:
    """Return whether company sector/type looks compatible with zone type."""
    combined = normalize_text(
        " ".join(
            [
                company["company_name"] or "",
                company["sector_primary"] or "",
                company["sector_secondary"] or "",
                company["company_type"] or "",
            ]
        )
    )

    zone_type = normalize_text(zone["zone_type"])

    if "technology" in zone_type or "offshoring" in zone_type:
        return any(
            keyword in combined
            for keyword in [
                "informatique",
                "data",
                "web",
                "mobile",
                "cloud",
                "cyber",
                "software",
                "technologie",
                "marketing digital",
            ]
        )

    if "financial" in zone_type:
        return any(
            keyword in combined
            for keyword in ["finance", "fintech", "bank", "banque", "assurance"]
        )

    if "automotive" in zone_type:
        return any(
            keyword in combined
            for keyword in ["auto", "automotive", "industrie", "manufacturing"]
        )

    if "aerospace" in zone_type:
        return any(
            keyword in combined
            for keyword in ["aero", "aerospace", "industrie", "manufacturing"]
        )

    if "agri" in zone_type or "seafood" in zone_type:
        return any(
            keyword in combined
            for keyword in ["agri", "food", "alimentaire", "peche", "seafood"]
        )

    if "industrial" in zone_type:
        return any(
            keyword in combined
            for keyword in ["industry", "industrie", "manufacturing", "factory"]
        )

    return False


def build_link_candidates(
    company: sqlite3.Row,
    zones: list[sqlite3.Row],
    max_links_per_company: int,
) -> list[CompanyZoneCandidate]:
    """Build candidate links for one company."""
    company_region = normalize_text(company["region"])
    company_city_values = [
        normalize_text(city)
        for city in split_city_values(company["city"])
        if is_valid_city(city)
    ]

    if not company_region or not company_city_values:
        return []

    company_text = normalize_text(
        " ".join(
            [
                company["company_name"] or "",
                company["address"] or "",
            ]
        )
    )

    candidates: list[CompanyZoneCandidate] = []

    for zone in zones:
        zone_region = normalize_text(zone["region"])
        zone_city = normalize_text(zone["city"])
        zone_name = normalize_text(zone["zone_name"])

        if not zone_region or not zone_city:
            continue

        if company_region != zone_region:
            continue

        if zone_city not in company_city_values:
            continue

        confidence = 35
        link_type = "same_city_region_candidate"
        evidence_parts = [
            "Company and zone have the same city and region.",
            "This is an inferred candidate link, not proof that the company is inside the zone.",
        ]

        if sector_matches_zone(company, zone):
            confidence += 10
            link_type = "same_city_region_sector_candidate"
            evidence_parts.append("Company sector/type is compatible with zone type.")

        if zone_name and zone_name in company_text:
            confidence += 30
            link_type = "name_or_address_zone_match"
            evidence_parts.append("Zone name appears in company name or address.")

        confidence = min(confidence, 80)

        candidates.append(
            CompanyZoneCandidate(
                company_id=int(company["company_id"]),
                zone_id=int(zone["zone_id"]),
                source_url=zone["source_url"],
                confidence_score=confidence,
                link_type=link_type,
                evidence=" ".join(evidence_parts),
            )
        )

    candidates.sort(
        key=lambda candidate: (
            candidate.confidence_score,
            candidate.link_type,
        ),
        reverse=True,
    )

    return candidates[:max_links_per_company]


def link_companies_to_zones(
    reset: bool = True,
    max_links_per_company: int = 3,
    limit: int | None = None,
) -> int:
    """Infer company-zone links using conservative city/region matching."""
    with get_connection() as conn:
        ensure_company_zone_metadata_columns(conn)

        if reset:
            conn.execute(
                """
                DELETE FROM company_zones
                WHERE link_type IN (
                    'same_city_region_candidate',
                    'same_city_region_sector_candidate',
                    'name_or_address_zone_match'
                )
                """
            )

        zone_rows = conn.execute(
            """
            SELECT
                zone_id,
                zone_name,
                region,
                city,
                zone_type,
                source_url
            FROM zones
            WHERE city IS NOT NULL
              AND TRIM(city) != ''
              AND region IS NOT NULL
              AND TRIM(region) != ''
            """
        ).fetchall()

        company_query = """
            SELECT
                company_id,
                company_name,
                city,
                region,
                sector_primary,
                sector_secondary,
                company_type,
                address
            FROM companies
            WHERE city IS NOT NULL
              AND TRIM(city) != ''
              AND region IS NOT NULL
              AND TRIM(region) != ''
        """

        params: list[int] = []

        if limit is not None:
            company_query += " LIMIT ?"
            params.append(limit)

        company_rows = conn.execute(company_query, params).fetchall()

        inserted = 0

        for company in company_rows:
            candidates = build_link_candidates(
                company=company,
                zones=zone_rows,
                max_links_per_company=max_links_per_company,
            )

            for candidate in candidates:
                exists = conn.execute(
                    """
                    SELECT 1
                    FROM company_zones
                    WHERE company_id = ?
                      AND zone_id = ?
                      AND link_type = ?
                    LIMIT 1
                    """,
                    (
                        candidate.company_id,
                        candidate.zone_id,
                        candidate.link_type,
                    ),
                ).fetchone()

                if exists:
                    continue

                conn.execute(
                    """
                    INSERT INTO company_zones (
                        company_id,
                        zone_id,
                        source_url,
                        confidence_score,
                        link_type,
                        evidence,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        candidate.company_id,
                        candidate.zone_id,
                        candidate.source_url,
                        candidate.confidence_score,
                        candidate.link_type,
                        candidate.evidence,
                    ),
                )

                inserted += 1

        conn.commit()

    return inserted


def get_company_zone_link_stats() -> dict[str, int]:
    """Return company-zone link counts."""
    with get_connection() as conn:
        ensure_company_zone_metadata_columns(conn)

        total = conn.execute("SELECT COUNT(*) FROM company_zones").fetchone()[0]

        rows = conn.execute(
            """
            SELECT link_type, COUNT(*) AS total
            FROM company_zones
            GROUP BY link_type
            ORDER BY total DESC
            """
        ).fetchall()

    stats = {"total": int(total)}
    stats.update({row["link_type"] or "unknown": int(row["total"]) for row in rows})

    return stats


def sample_company_zone_links(limit: int = 30) -> list[sqlite3.Row]:
    """Return sample company-zone links for inspection."""
    with get_connection() as conn:
        ensure_company_zone_metadata_columns(conn)

        return conn.execute(
            """
            SELECT
                c.company_name,
                c.city AS company_city,
                c.region AS company_region,
                c.sector_primary,
                z.zone_name,
                z.city AS zone_city,
                z.region AS zone_region,
                cz.confidence_score,
                cz.link_type,
                cz.evidence
            FROM company_zones cz
            JOIN companies c ON c.company_id = cz.company_id
            JOIN zones z ON z.zone_id = cz.zone_id
            ORDER BY cz.confidence_score DESC, c.company_name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
