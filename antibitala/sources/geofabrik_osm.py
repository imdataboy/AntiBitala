from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from antibitala.database.connection import get_connection


OSM_SOURCE_NAME = "Geofabrik Morocco OSM"
OSM_SOURCE_TYPE = "national_osm_business_base"
OSM_GEOJSON_PATH = Path("data/staging/osm/morocco_osm_employer_candidates.geojson")

EXCLUDED_CITY_NAMES = {
    "ceuta",
    "melilla",
}

EXCLUDED_OFFICES = {
    "government",
    "administrative",
    "diplomatic",
    "political_party",
}


ELIGIBLE_AMENITIES = {
    "bank",
    "clinic",
    "hospital",
    "doctors",
    "pharmacy",
    "school",
    "college",
    "university",
    "fuel",
}


ELIGIBLE_TOURISM = {
    "hotel",
    "guest_house",
    "hostel",
}


ELIGIBLE_LANDUSE = {
    "industrial",
    "commercial",
    "retail",
}


ELIGIBLE_BUILDINGS = {
    "industrial",
    "commercial",
    "office",
    "retail",
    "warehouse",
}


@dataclass(frozen=True)
class OSMCandidate:
    company_name: str
    normalized_name: str
    source_url: str
    city: str | None
    region: str | None
    sector_primary: str | None
    sector_secondary: str | None
    company_type: str
    website: str | None
    public_email: str | None
    phone: str | None
    address: str | None
    latitude: float | None
    longitude: float | None


def clean_text(value: object) -> str | None:
    if value is None:
        return None

    cleaned = re.sub(r"\s+", " ", str(value).strip())
    return cleaned or None


def normalize_name(name: str) -> str:
    cleaned = name.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\b(sarl|sa|sas|maroc|morocco|ltd|llc)\b", "", cleaned)
    cleaned = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿñæœ\s'.-]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def normalize_url(url: str | None) -> str | None:
    cleaned = clean_text(url)

    if not cleaned:
        return None

    cleaned = cleaned.split()[0].strip()

    if cleaned.lower() in {"#", "n/a", "na", "none", "null", "-", "--"}:
        return None

    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None

    if not parsed.netloc:
        return None

    return cleaned

def normalize_simple(value: str | None) -> str:
    if not value:
        return ""

    value = value.lower()
    value = re.sub(r"[^a-zàâçéèêëîïôûùüÿñæœ\s-]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_excluded_city(city: str | None) -> bool:
    normalized = normalize_simple(city)
    return any(excluded in normalized for excluded in EXCLUDED_CITY_NAMES)


def is_excluded_enclave(latitude: float | None, longitude: float | None) -> bool:
    """Exclude Ceuta and Melilla approximate bounding boxes."""
    if latitude is None or longitude is None:
        return False

    is_ceuta = 35.84 <= latitude <= 35.93 and -5.45 <= longitude <= -5.25
    is_melilla = 35.25 <= latitude <= 35.35 and -3.05 <= longitude <= -2.85

    return is_ceuta or is_melilla


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    domain = parsed.netloc.lower().replace("www.", "")
    return domain or None


def get_osm_object_id(feature: dict) -> str | None:
    raw_id = feature.get("id")

    if raw_id:
        return str(raw_id)

    props = feature.get("properties", {})
    raw_id = props.get("@id") or props.get("id")

    return str(raw_id) if raw_id else None


def build_osm_url(osm_id: str | None) -> str:
    """Build a clickable OpenStreetMap object URL."""
    if not osm_id:
        return "https://www.openstreetmap.org/"

    osm_id = str(osm_id).strip()

    if "/" in osm_id:
        object_type, object_number = osm_id.split("/", 1)
        return f"https://www.openstreetmap.org/{object_type}/{object_number}"

    prefix = osm_id[0]
    object_number = osm_id[1:]

    prefix_map = {
        "n": "node",
        "w": "way",
        "r": "relation",
    }

    object_type = prefix_map.get(prefix)

    if object_type and object_number.isdigit():
        return f"https://www.openstreetmap.org/{object_type}/{object_number}"

    return "https://www.openstreetmap.org/"



def collect_coordinates(coords: object) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []

    if not isinstance(coords, list):
        return points

    if (
        len(coords) >= 2
        and isinstance(coords[0], int | float)
        and isinstance(coords[1], int | float)
    ):
        points.append((float(coords[0]), float(coords[1])))
        return points

    for item in coords:
        points.extend(collect_coordinates(item))

    return points


def geometry_center(feature: dict) -> tuple[float | None, float | None]:
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates")
    points = collect_coordinates(coords)

    if not points:
        return None, None

    lon = sum(point[0] for point in points) / len(points)
    lat = sum(point[1] for point in points) / len(points)

    return lat, lon


def get_address(props: dict) -> str | None:
    parts = [
        props.get("addr:housenumber"),
        props.get("addr:street"),
        props.get("addr:neighbourhood"),
        props.get("addr:suburb"),
        props.get("addr:city"),
        props.get("addr:postcode"),
    ]

    cleaned_parts = [clean_text(part) for part in parts if clean_text(part)]
    return ", ".join(cleaned_parts) if cleaned_parts else None


def get_city(props: dict) -> str | None:
    return (
        clean_text(props.get("addr:city"))
        or clean_text(props.get("addr:town"))
        or clean_text(props.get("addr:village"))
    )


def is_employer_like(props: dict) -> bool:
    office = clean_text(props.get("office"))
    amenity = clean_text(props.get("amenity"))
    tourism = clean_text(props.get("tourism"))
    landuse = clean_text(props.get("landuse"))
    building = clean_text(props.get("building"))

    if office and office not in EXCLUDED_OFFICES:
        return True

    if props.get("shop"):
        return True

    if props.get("craft"):
        return True

    if props.get("industrial"):
        return True

    if props.get("man_made") == "works":
        return True

    if amenity in ELIGIBLE_AMENITIES:
        return True

    if tourism in ELIGIBLE_TOURISM:
        return True

    if landuse in ELIGIBLE_LANDUSE:
        return True

    if building in ELIGIBLE_BUILDINGS:
        return True

    if props.get("healthcare"):
        return True

    return False


def classify_sector(props: dict) -> tuple[str, str | None, str]:
    office = clean_text(props.get("office"))
    shop = clean_text(props.get("shop"))
    amenity = clean_text(props.get("amenity"))
    tourism = clean_text(props.get("tourism"))
    craft = clean_text(props.get("craft"))
    industrial = clean_text(props.get("industrial"))
    landuse = clean_text(props.get("landuse"))
    building = clean_text(props.get("building"))
    healthcare = clean_text(props.get("healthcare"))

    if office:
        return "office_services", office, "osm_office"

    if industrial or landuse == "industrial" or building in {"industrial", "warehouse"}:
        return "industry_manufacturing", industrial or landuse or building, "osm_industrial"

    if amenity == "bank":
        return "finance_banking", amenity, "osm_bank"

    if amenity in {"clinic", "hospital", "doctors", "pharmacy"} or healthcare:
        return "healthcare", amenity or healthcare, "osm_healthcare"

    if amenity in {"school", "college", "university"}:
        return "education_training", amenity, "osm_education"

    if tourism:
        return "hospitality_tourism", tourism, "osm_tourism"

    if shop:
        return "retail_commerce", shop, "osm_shop"

    if craft:
        return "craft_local_services", craft, "osm_craft"

    if landuse in {"commercial", "retail"} or building in {"commercial", "office", "retail"}:
        return "commercial_area", landuse or building, "osm_commercial"

    if amenity == "fuel":
        return "energy_fuel", amenity, "osm_fuel"

    return "other_employer_candidate", None, "osm_candidate"


def feature_to_candidate(feature: dict) -> OSMCandidate | None:
    props = feature.get("properties", {})
    name = clean_text(props.get("name"))

    if not name:
        return None

    if not is_employer_like(props):
        return None

    normalized = normalize_name(name)

    if not normalized or len(normalized) < 2:
        return None

    sector_primary, sector_secondary, company_type = classify_sector(props)

    website = normalize_url(props.get("website") or props.get("contact:website"))
    email = clean_text(props.get("email") or props.get("contact:email"))
    phone = clean_text(props.get("phone") or props.get("contact:phone"))

    osm_id = get_osm_object_id(feature)
    source_url = build_osm_url(osm_id)

    latitude, longitude = geometry_center(feature)
    
    city = get_city(props)

    if is_excluded_city(city) or is_excluded_enclave(latitude, longitude):
        return None

    return OSMCandidate(
        company_name=name,
        normalized_name=normalized,
        source_url=source_url,
        city=city,
        region=None,
        sector_primary=sector_primary,
        sector_secondary=sector_secondary,
        company_type=company_type,
        website=website,
        public_email=email,
        phone=phone,
        address=get_address(props),
        latitude=latitude,
        longitude=longitude,
    )


def load_osm_candidates(limit: int | None = None) -> list[OSMCandidate]:
    if not OSM_GEOJSON_PATH.exists():
        raise FileNotFoundError(
            f"OSM GeoJSON not found at {OSM_GEOJSON_PATH}. "
            "Create it from the Geofabrik extract first."
        )

    with OSM_GEOJSON_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    candidates: list[OSMCandidate] = []
    seen_keys: set[tuple[str, str | None]] = set()

    for feature in data.get("features", []):
        if limit is not None and len(candidates) >= limit:
            break

        candidate = feature_to_candidate(feature)

        if not candidate:
            continue

        domain = extract_domain(candidate.website)
        key = (candidate.normalized_name, domain)

        if key in seen_keys:
            continue

        seen_keys.add(key)
        candidates.append(candidate)

    return candidates


def upsert_osm_company(conn: sqlite3.Connection, candidate: OSMCandidate) -> int:
    domain = extract_domain(candidate.website)
    now = datetime.now(UTC).date().isoformat()

    existing = None

    if domain:
        existing = conn.execute(
            """
            SELECT company_id
            FROM companies
            WHERE domain = ?
            LIMIT 1
            """,
            (domain,),
        ).fetchone()

    if not existing:
        existing = conn.execute(
            """
            SELECT company_id
            FROM companies
            WHERE normalized_name = ?
              AND COALESCE(city, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (candidate.normalized_name, candidate.city),
        ).fetchone()

    if existing:
        company_id = int(existing["company_id"])

        conn.execute(
            """
            UPDATE companies
            SET
                website = COALESCE(website, ?),
                domain = COALESCE(domain, ?),
                public_email = COALESCE(public_email, ?),
                phone = COALESCE(phone, ?),
                address = COALESCE(address, ?),
                latitude = COALESCE(latitude, ?),
                longitude = COALESCE(longitude, ?),
                last_seen_date = ?,
                last_checked_date = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE company_id = ?
            """,
            (
                candidate.website,
                domain,
                candidate.public_email,
                candidate.phone,
                candidate.address,
                candidate.latitude,
                candidate.longitude,
                now,
                now,
                company_id,
            ),
        )

        return company_id

    cursor = conn.execute(
        """
        INSERT INTO companies (
            company_name,
            normalized_name,
            city,
            region,
            country,
            sector_primary,
            sector_secondary,
            company_type,
            website,
            domain,
            public_email,
            phone,
            address,
            latitude,
            longitude,
            trust_score,
            job_relevance_score,
            source_count,
            first_seen_date,
            last_seen_date,
            last_checked_date,
            status
        )
        VALUES (?, ?, ?, ?, 'Morocco', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 55, 45, 1, ?, ?, ?, 'active')
        """,
        (
            candidate.company_name,
            candidate.normalized_name,
            candidate.city,
            candidate.region,
            candidate.sector_primary,
            candidate.sector_secondary,
            candidate.company_type,
            candidate.website,
            domain,
            candidate.public_email,
            candidate.phone,
            candidate.address,
            candidate.latitude,
            candidate.longitude,
            now,
            now,
            now,
        ),
    )

    return int(cursor.lastrowid)


def link_osm_source(conn: sqlite3.Connection, company_id: int, candidate: OSMCandidate) -> None:
    existing = conn.execute(
        """
        SELECT source_id
        FROM company_sources
        WHERE company_id = ?
          AND source_name = ?
          AND source_url = ?
        LIMIT 1
        """,
        (company_id, OSM_SOURCE_NAME, candidate.source_url),
    ).fetchone()

    if existing:
        return

    conn.execute(
        """
        INSERT INTO company_sources (
            company_id,
            source_name,
            source_type,
            source_url,
            source_region,
            coverage_scope,
            source_reliability
        )
        VALUES (?, ?, ?, ?, 'national', 'national', 'medium')
        """,
        (
            company_id,
            OSM_SOURCE_NAME,
            OSM_SOURCE_TYPE,
            candidate.source_url,
        ),
    )


def rebuild_company_source_counts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE companies
        SET source_count = (
            SELECT COUNT(*)
            FROM company_sources
            WHERE company_sources.company_id = companies.company_id
        )
        """
    )


def fetch_and_store_osm(limit: int | None = None) -> int:
    candidates = load_osm_candidates(limit=limit)

    inserted_or_updated = 0

    with get_connection() as conn:
        for candidate in candidates:
            company_id = upsert_osm_company(conn, candidate)
            link_osm_source(conn, company_id, candidate)
            inserted_or_updated += 1

        rebuild_company_source_counts(conn)

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
                "geofabrik_morocco_osm",
                inserted_or_updated,
                f"Imported from {OSM_GEOJSON_PATH}",
            ),
        )

        conn.commit()

    return inserted_or_updated
