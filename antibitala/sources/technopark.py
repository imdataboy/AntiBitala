from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from bs4 import BeautifulSoup

from antibitala.database.connection import get_connection


TECHNOPARK_SOURCE_KEY = "technopark_maroc"
TECHNOPARK_STARTUPS_URL = "https://www.technopark.ma/start-ups-du-mois/#/"
TECHNOPARK_API_URL = "https://www.technopark.ma/wp-json/monapp/v1/entreprises"

CITY_TO_REGION = {
    "casablanca": "Casablanca-Settat",
    "rabat": "Rabat-Sale-Kenitra",
    "tanger": "Tanger-Tetouan-Al Hoceima",
    "agadir": "Souss-Massa",
    "essaouira": "Marrakech-Safi",
}


@dataclass(frozen=True)
class CompanyCandidate:
    company_name: str
    source_url: str
    city: str | None = None
    region: str | None = None
    sector_primary: str | None = "tech_startups"
    sector_secondary: str | None = None
    company_type: str | None = "technopark_member"
    website: str | None = None
    public_email: str | None = None
    phone: str | None = None
    description: str | None = None
    source_external_id: str | None = None


def normalize_name(name: str) -> str:
    """Normalize company name for deduplication."""
    cleaned = name.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\b(sarl|sa|sas|maroc|morocco|ltd|llc)\b", "", cleaned)
    cleaned = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿñæœ\s'.-]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def clean_text(text: str | None) -> str | None:
    """Clean plain text."""
    if not text:
        return None

    cleaned = re.sub(r"\s+", " ", text.strip())
    return cleaned or None


def html_to_text(html: str | None) -> str | None:
    """Convert small HTML description to text."""
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    return clean_text(soup.get_text(" ", strip=True))


def extract_domain(url: str | None) -> str | None:
    """Extract domain from URL safely."""
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    domain = parsed.netloc.lower().replace("www.", "")
    return domain or None

def normalize_website(url: str | None) -> str | None:
    """Normalize website URL safely."""
    cleaned = clean_text(url)

    if not cleaned:
        return None

    lowered = cleaned.lower()

    invalid_values = {
        "#",
        "n/a",
        "na",
        "none",
        "null",
        "-",
        "--",
    }

    if lowered in invalid_values:
        return None

    # Handle multilingual WordPress-like values:
    # [:fr]http://example.com/[:en]www.example.com[:]
    url_match = re.search(r"https?://[^\s\[\]]+|www\.[^\s\[\]]+", cleaned)

    if url_match:
        cleaned = url_match.group(0)
    else:
        cleaned = cleaned.split()[0].strip()

    cleaned = cleaned.strip(".,;:)")

    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None

    if not parsed.netloc:
        return None

    if "[" in parsed.netloc or "]" in parsed.netloc:
        return None

    return cleaned


def get_region_from_city(city: str | None) -> str | None:
    if not city:
        return None

    return CITY_TO_REGION.get(city.strip().lower())


def fetch_technopark_api_records() -> list[dict]:
    """Fetch all Technopark companies from browser-captured JSON API."""
    api_url_part = "/wp-json/monapp/v1/entreprises"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 1600},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
        )

        page = context.new_page()

        api_payload: dict | None = None

        def capture_response(response) -> None:
            nonlocal api_payload

            if api_url_part not in response.url:
                return

            content_type = response.headers.get("content-type", "")

            if "application/json" not in content_type:
                return

            try:
                api_payload = response.json()
            except Exception:
                api_payload = None

        page.on("response", capture_response)

        page.goto(TECHNOPARK_STARTUPS_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector("#root", state="attached", timeout=60_000)

        # Wait for the React app to call the API.
        page.wait_for_selector(
            "button:has-text('Voir Details')",
            state="visible",
            timeout=60_000,
        )

        page.wait_for_timeout(2_000)

        browser.close()

    if not api_payload:
        raise RuntimeError("Technopark API payload was not captured in browser context.")

    if not api_payload.get("success"):
        raise RuntimeError(f"Technopark API returned unsuccessful payload: {api_payload}")

    data = api_payload.get("data", [])

    if not isinstance(data, list):
        raise RuntimeError("Technopark API payload field 'data' is not a list.")

    return data

def record_to_candidate(record: dict) -> CompanyCandidate | None:
    """Map one Technopark API record to internal candidate."""
    company_name = clean_text(record.get("EntrepriseName"))

    if not company_name:
        return None

    city = clean_text(record.get("EntrepriseVille"))
    region = get_region_from_city(city)

    website = normalize_website(record.get("EntrepriseContactSiteWeb"))
    email = clean_text(record.get("EntrepriseContactEmail"))
    phone = clean_text(record.get("EntrepriseContactPhone"))

    sector = clean_text(record.get("EntrepriseSecteurActivite"))
    technologies = clean_text(record.get("EntrepriseTechnologie"))
    description = html_to_text(record.get("Activite"))

    external_id = clean_text(record.get("Id"))

    source_url = TECHNOPARK_API_URL
    if external_id:
        source_url = f"{TECHNOPARK_API_URL}#{external_id}"

    return CompanyCandidate(
        company_name=company_name,
        source_url=source_url,
        city=city,
        region=region,
        sector_primary=sector or "tech_startups",
        sector_secondary=technologies,
        website=website,
        public_email=email,
        phone=phone,
        description=description,
        source_external_id=external_id,
    )


def fetch_technopark_candidates(limit: int | None = None) -> list[CompanyCandidate]:
    """Fetch Technopark companies from API."""
    records = fetch_technopark_api_records()
    candidates: list[CompanyCandidate] = []
    seen_names: set[str] = set()

    for record in records:
        if limit is not None and len(candidates) >= limit:
            break

        candidate = record_to_candidate(record)

        if not candidate:
            continue

        normalized = normalize_name(candidate.company_name)

        if not normalized or normalized in seen_names:
            continue

        seen_names.add(normalized)
        candidates.append(candidate)

    print(f"Fetched {len(candidates)} Technopark candidates from API.")
    return candidates


def get_source_id(conn: sqlite3.Connection) -> int | None:
    """Return data_sources.source_id for Technopark if seeded."""
    row = conn.execute(
        "SELECT source_id FROM data_sources WHERE source_key = ?",
        (TECHNOPARK_SOURCE_KEY,),
    ).fetchone()

    return int(row["source_id"]) if row else None


def upsert_company(conn: sqlite3.Connection, candidate: CompanyCandidate) -> int:
    """Insert or update company and return company_id."""
    normalized_name = normalize_name(candidate.company_name)
    domain = extract_domain(candidate.website)
    now = datetime.now(UTC).date().isoformat()

    if not normalized_name:
        raise ValueError(f"Invalid company name: {candidate.company_name!r}")

    existing = conn.execute(
        """
        SELECT company_id
        FROM companies
        WHERE normalized_name = ?
        LIMIT 1
        """,
        (normalized_name,),
    ).fetchone()

    if existing:
        company_id = int(existing["company_id"])
        conn.execute(
            """
            UPDATE companies
            SET
                website = COALESCE(?, website),
                domain = COALESCE(?, domain),
                public_email = COALESCE(?, public_email),
                phone = COALESCE(?, phone),
                city = COALESCE(?, city),
                region = COALESCE(?, region),
                sector_primary = COALESCE(?, sector_primary),
                sector_secondary = COALESCE(?, sector_secondary),
                company_type = COALESCE(?, company_type),
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
                candidate.city,
                candidate.region,
                candidate.sector_primary,
                candidate.sector_secondary,
                candidate.company_type,
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
            trust_score,
            job_relevance_score,
            source_count,
            first_seen_date,
            last_seen_date,
            last_checked_date,
            status
        )
        VALUES (?, ?, ?, ?, 'Morocco', ?, ?, ?, ?, ?, ?, ?, 85, 80, 1, ?, ?, ?, 'active')
        """,
        (
            candidate.company_name,
            normalized_name,
            candidate.city,
            candidate.region,
            candidate.sector_primary,
            candidate.sector_secondary,
            candidate.company_type,
            candidate.website,
            domain,
            candidate.public_email,
            candidate.phone,
            now,
            now,
            now,
        ),
    )

    return int(cursor.lastrowid)


def link_company_source(
    conn: sqlite3.Connection,
    company_id: int,
    candidate: CompanyCandidate,
) -> None:
    """Attach Technopark source URL to company without duplicating links."""
    existing = conn.execute(
        """
        SELECT source_id
        FROM company_sources
        WHERE company_id = ?
          AND source_name = 'Technopark Maroc'
          AND source_url = ?
        LIMIT 1
        """,
        (company_id, candidate.source_url),
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
        VALUES (
            ?,
            'Technopark Maroc',
            'tech_startup_ecosystem',
            ?,
            'multi_region',
            'multi_city',
            'high'
        )
        """,
        (company_id, candidate.source_url),
    )


def rebuild_company_source_counts(conn: sqlite3.Connection) -> None:
    """Update source_count for all companies."""
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


def fetch_and_store_technopark(limit: int | None = None) -> int:
    """Fetch Technopark startups and store them in SQLite."""
    candidates = fetch_technopark_candidates(limit=limit)

    inserted_or_updated = 0

    with get_connection() as conn:
        source_id = get_source_id(conn)
        if source_id is None:
            raise RuntimeError(
                "Technopark source is not seeded. Run: uv run antibitala seed-sources"
            )

        for candidate in candidates:
            company_id = upsert_company(conn, candidate)
            link_company_source(conn, company_id, candidate)
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
                "technopark_maroc",
                inserted_or_updated,
                f"Fetched from API {TECHNOPARK_API_URL}",
            ),
        )

        conn.commit()

    return inserted_or_updated