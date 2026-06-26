from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from antibitala.database.connection import get_connection


BASE_URL = "https://industrial-estate.gov.ma/"
SEARCH_URL = "https://industrial-estate.gov.ma/search.php"

SOURCE_NAME = "Industrial Estate Morocco"
SOURCE_TYPE = "official_industrial_zone_platform"


@dataclass(frozen=True)
class IndustrialEstateZone:
    zone_name: str
    region: str | None
    city: str | None
    zone_type: str
    operator: str | None
    source_url: str
    area_hectares: float | None = None
    available_lots: int | None = None


def clean_text(value: str | None) -> str | None:
    """Normalize text from HTML."""
    if not value:
        return None

    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned or None


def parse_float(value: str | None) -> float | None:
    if not value:
        return None

    normalized = value.replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)

    if not match:
        return None

    return float(match.group(1))


def parse_int(value: str | None) -> int | None:
    if not value:
        return None

    match = re.search(r"(\d+)", value.replace(" ", ""))

    if not match:
        return None

    return int(match.group(1))


def canonical_region(region: str | None) -> str | None:
    """Normalize official platform region names to our canonical names."""
    if not region:
        return None

    cleaned = clean_text(region)

    mapping = {
        "Tanger-Tétouan-Al Hoceima": "Tanger-Tétouan-Al Hoceïma",
        "Dakhla-Oued Eddahab": "Dakhla-Oued Ed-Dahab",
    }

    return mapping.get(cleaned, cleaned)


def classify_zone_type(zone_name: str) -> str:
    name = zone_name.lower()

    if "agropole" in name:
        return "agropole"

    if "zone d'accélération" in name or "zone d’accélération" in name:
        return "industrial_acceleration_zone"

    if "zae" in name or "zone d'activit" in name or "zone d’activit" in name:
        return "economic_activity_zone"

    if "parc" in name:
        return "industrial_park"

    return "industrial_zone"


def get_search_page(page_number: int) -> str:
    params = {
        "area": "",
        "area_max": "",
        "lang": "fr",
        "nature_offer": "-1",
        "p": str(page_number),
        "proximity": "",
        "q": "",
    }

    headers = {
        "User-Agent": (
            "AntiBitalaBot/0.1 "
            "(local open-source Morocco job discovery project)"
        )
    }

    response = requests.get(
        SEARCH_URL,
        params=params,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()

    return response.text


def parse_zone_cards(html: str) -> list[IndustrialEstateZone]:
    """Parse zone cards from one Industrial Estate search page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    zones: list[IndustrialEstateZone] = []

    for index, line in enumerate(lines):
        if not (
            line.startswith("Zone ")
            or line.startswith("ZAE ")
            or line.startswith("Parc ")
            or line.startswith("Agropole ")
            or line.startswith("Tanger ")
        ):
            continue

        zone_name = clean_text(line)

        if not zone_name:
            continue

        city = None
        region = None
        source_url = BASE_URL

        # Usually the next line contains: City / Region
        for look_ahead in range(index + 1, min(index + 5, len(lines))):
            candidate = lines[look_ahead]

            if " / " in candidate:
                left, right = candidate.split(" / ", 1)
                city = clean_text(left)
                region = canonical_region(right)
                break

        area_hectares = None
        available_lots = None

        for look_ahead in range(index + 1, min(index + 8, len(lines))):
            candidate = lines[look_ahead]

            if "Superficie" in candidate:
                area_hectares = parse_float(candidate)

            if "Lots disponibles" in candidate:
                available_lots = parse_int(candidate)

        zones.append(
            IndustrialEstateZone(
                zone_name=zone_name,
                region=region,
                city=city,
                zone_type=classify_zone_type(zone_name),
                operator=SOURCE_NAME,
                source_url=source_url,
                area_hectares=area_hectares,
                available_lots=available_lots,
            )
        )

    return zones


def fetch_industrial_estate_zones(max_pages: int = 50) -> list[IndustrialEstateZone]:
    """Fetch zones from the official Industrial Estate search pages."""
    zones: list[IndustrialEstateZone] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    for page_number in range(1, max_pages + 1):
        html = get_search_page(page_number)
        page_zones = parse_zone_cards(html)

        if not page_zones:
            break

        for zone in page_zones:
            key = (zone.zone_name, zone.city, zone.region)

            if key in seen:
                continue

            seen.add(key)
            zones.append(zone)

    return zones


def upsert_zone(conn: sqlite3.Connection, zone: IndustrialEstateZone) -> int:
    """Insert or update zone in zones table."""
    existing = conn.execute(
        """
        SELECT zone_id
        FROM zones
        WHERE zone_name = ?
          AND COALESCE(city, '') = COALESCE(?, '')
          AND COALESCE(region, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (zone.zone_name, zone.city, zone.region),
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
                source_url = COALESCE(?, source_url)
            WHERE zone_id = ?
            """,
            (
                zone.region,
                zone.city,
                zone.zone_type,
                zone.operator,
                zone.source_url,
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
            source_url
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            zone.zone_name,
            zone.region,
            zone.city,
            zone.zone_type,
            zone.operator,
            zone.source_url,
        ),
    )

    return int(cursor.lastrowid)


def import_industrial_estate_zones(max_pages: int = 50) -> int:
    """Import official Industrial Estate Morocco zones."""
    zones = fetch_industrial_estate_zones(max_pages=max_pages)

    imported = 0

    with get_connection() as conn:
        for zone in zones:
            upsert_zone(conn, zone)
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
                "industrial_estate_morocco",
                imported,
                f"Imported from {SEARCH_URL}",
            ),
        )

        conn.commit()

    return imported


def inspect_industrial_estate_zones(max_pages: int = 2) -> list[IndustrialEstateZone]:
    """Inspect official zones before importing."""
    return fetch_industrial_estate_zones(max_pages=max_pages)

