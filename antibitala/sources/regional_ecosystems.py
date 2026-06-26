from __future__ import annotations

import sqlite3

from antibitala.database.connection import get_connection


MOROCCO_REGIONS = [
    "Tanger-Tetouan-Al Hoceima",
    "Oriental",
    "Fes-Meknes",
    "Rabat-Sale-Kenitra",
    "Beni Mellal-Khenifra",
    "Casablanca-Settat",
    "Marrakech-Safi",
    "Draa-Tafilalet",
    "Souss-Massa",
    "Guelmim-Oued Noun",
    "Laayoune-Sakia El Hamra",
    "Dakhla-Oued Ed-Dahab",
]


def normalize_region_name(value: str | None) -> str:
    """Normalize region names for reliable comparison."""
    if not value:
        return ""

    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "à": "a",
        "â": "a",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ù": "u",
        "û": "u",
        "ç": "c",
        "’": "'",
        "–": "-",
        "—": "-",
    }

    cleaned = value.strip()

    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)

    return " ".join(cleaned.lower().replace("_", "-").split())


def get_regional_sources() -> list[sqlite3.Row]:
    """Return enabled CRI/regional ecosystem sources."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                source_key,
                source_name,
                source_type,
                region,
                city,
                coverage_scope,
                reliability_level,
                access_method,
                base_url,
                enabled,
                notes
            FROM data_sources
            WHERE enabled = 1
              AND (
                    source_key LIKE 'cri_%'
                    OR source_type = 'regional'
                    OR coverage_scope = 'regional'
              )
            ORDER BY region, source_name
            """
        ).fetchall()


def validate_regional_source_coverage() -> dict[str, object]:
    """Validate whether every Moroccan region has at least one enabled regional source."""
    sources = get_regional_sources()

    expected_regions = {
        normalize_region_name(region): region
        for region in MOROCCO_REGIONS
    }

    covered_regions: dict[str, str] = {}

    for source in sources:
        normalized_region = normalize_region_name(source["region"])

        if normalized_region in expected_regions:
            covered_regions[normalized_region] = expected_regions[normalized_region]

    missing_regions = [
        original_name
        for normalized, original_name in expected_regions.items()
        if normalized not in covered_regions
    ]

    return {
        "total_regions": len(MOROCCO_REGIONS),
        "covered_count": len(covered_regions),
        "missing_count": len(missing_regions),
        "missing_regions": missing_regions,
        "sources_count": len(sources),
    }


def get_regional_source_summary() -> list[dict[str, object]]:
    """Return regional source coverage summary by region."""
    sources = get_regional_sources()

    grouped: dict[str, dict[str, object]] = {}

    for region in MOROCCO_REGIONS:
        grouped[region] = {
            "region": region,
            "sources": 0,
            "source_keys": [],
            "reliability_levels": [],
        }

    for source in sources:
        normalized_region = normalize_region_name(source["region"])

        for official_region in MOROCCO_REGIONS:
            if normalize_region_name(official_region) == normalized_region:
                grouped[official_region]["sources"] += 1
                grouped[official_region]["source_keys"].append(source["source_key"])
                grouped[official_region]["reliability_levels"].append(
                    source["reliability_level"]
                )

    return list(grouped.values())
