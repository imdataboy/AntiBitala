from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from antibitala.database.connection import get_connection


TECHNOPARK_SOURCE_KEY = "technopark_maroc"
TECHNOPARK_STARTUPS_URL = "https://www.technopark.ma/start-ups-du-mois/#/"

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
    company_type: str | None = "startup"
    website: str | None = None
    public_email: str | None = None
    phone: str | None = None


def normalize_name(name: str) -> str:
    """Normalize company name for deduplication."""
    cleaned = name.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\b(sarl|sa|sas|maroc|morocco|ltd|llc)\b", "", cleaned)
    cleaned = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿñæœ\s'-]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_domain(url: str | None) -> str | None:
    """Extract domain from URL."""
    if not url:
        return None

    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")
    return domain or None


def clean_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def get_region_from_city(city: str | None) -> str | None:
    if not city:
        return None

    return CITY_TO_REGION.get(city.strip().lower())


def is_valid_company_name(text: str) -> bool:
    """Avoid menu/footer labels and section titles."""
    text = clean_line(text)

    if len(text) < 2 or len(text) > 80:
        return False

    lowered = text.lower()

    blocked = {
        "accueil",
        "technopark",
        "services",
        "startups",
        "startup",
        "media",
        "média",
        "se connecter",
        "réseau technopark",
        "reseau technopark",
        "découvrez nos startups",
        "decouvrez nos startups",
        "secteur d'activite",
        "secteur d’activité",
        "technologies",
        "site",
        "description",
        "voir details",
        "voir détails",
    }

    if lowered in blocked:
        return False

    if "@" in lowered:
        return False

    if any(word in lowered for word in ["contact", "presse", "photothèque", "phototheque"]):
        return False

    return True


def extract_field(lines: list[str], label_variants: set[str]) -> str | None:
    """Extract value after a label line."""
    lowered_lines = [line.lower() for line in lines]

    for index, line in enumerate(lowered_lines):
        if line in label_variants:
            for value in lines[index + 1 :]:
                lowered_value = value.lower()
                if lowered_value in {
                    "secteur d'activite",
                    "secteur d’activité",
                    "technologies",
                    "site",
                    "description",
                }:
                    return None
                return value

    return None


def extract_contact_links(page: Page) -> tuple[str | None, str | None, str | None]:
    """Extract website, email, and phone from rendered detail page."""
    website = None
    email = None
    phone = None

    links = page.locator("a").evaluate_all(
        """
        elements => elements.map(a => ({
            href: a.href || "",
            text: a.innerText || ""
        }))
        """
    )

    for link in links:
        href = link["href"].strip()

        if href.startswith("mailto:") and email is None:
            email = href.replace("mailto:", "").strip()

        elif href.startswith("tel:") and phone is None:
            phone = href.replace("tel:", "").strip()

        elif href.startswith("http") and website is None:
            domain = extract_domain(href)

            blocked_domains = {
                "facebook.com",
                "linkedin.com",
                "instagram.com",
                "youtube.com",
                "twitter.com",
                "x.com",
            }

            if (
                domain
                and "technopark.ma" not in domain
                and not any(blocked in domain for blocked in blocked_domains)
            ):
                website = href

    return website, email, phone


def parse_detail_page(page: Page) -> CompanyCandidate | None:
    """Parse one rendered Technopark startup detail page."""
    company_name = clean_line(
        page.locator(".companyDetailsWrapper h2").first.inner_text(timeout=10_000)
    )

    if not is_valid_company_name(company_name):
        return None

    details = page.locator(".companyDetailsWrapper > div")
    detail_count = details.count()

    founder = None
    sector = None
    technologies = None
    city = None

    for index in range(detail_count):
        block = details.nth(index)
        block_text = clean_line(block.inner_text())

        if index == 0:
            labels = block.locator("label")
            if labels.count() > 0:
                founder = clean_line(labels.first.inner_text())

        lowered = block_text.lower()

        if "secteur" in lowered:
            paragraphs = block.locator("p")
            if paragraphs.count() > 0:
                sector = clean_line(paragraphs.first.inner_text())

        elif "technologies" in lowered:
            paragraphs = block.locator("p")
            if paragraphs.count() > 0:
                technologies = clean_line(paragraphs.first.inner_text())

        elif lowered.startswith("site") or "\nsite" in lowered:
            paragraphs = block.locator("p")
            if paragraphs.count() > 0:
                city = clean_line(paragraphs.first.inner_text())

    region = get_region_from_city(city)
    website, email, phone = extract_contact_links(page)

    return CompanyCandidate(
        company_name=company_name,
        source_url=page.url,
        city=city,
        region=region,
        sector_primary=sector or "tech_startups",
        sector_secondary=technologies,
        website=website,
        public_email=email,
        phone=phone,
    )


def fetch_technopark_candidates(limit: int | None = None) -> list[CompanyCandidate]:
    """Render Technopark page in Chromium and collect startup details."""
    candidates: list[CompanyCandidate] = []

    debug_dir = Path("data/raw/technopark")
    debug_dir.mkdir(parents=True, exist_ok=True)

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
            viewport={"width": 1400, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
        )

        page = context.new_page()

        page.goto(TECHNOPARK_STARTUPS_URL, wait_until="domcontentloaded", timeout=60_000)

        # Do not wait for #root to be visible. It can be attached but hidden.
        page.wait_for_selector("#root", state="attached", timeout=60_000)

        # Wait for React app to render real cards.
        try:
            page.wait_for_selector(
                "button:has-text('Voir Details')",
                state="visible",
                timeout=60_000,
            )
        except Exception:
            page.screenshot(path=str(debug_dir / "technopark_no_buttons.png"), full_page=True)
            (debug_dir / "technopark_no_buttons.html").write_text(
                page.content(),
                encoding="utf-8",
            )
            print("No visible 'Voir Details' buttons detected.")
            print("Debug saved in data/raw/technopark/")
            browser.close()
            return candidates

        detail_buttons = page.locator("button:has-text('Voir Details')")
        button_count = detail_buttons.count()

        print(f"Detected Technopark detail buttons: {button_count}")

        max_items = min(button_count, limit or button_count)

        for index in range(max_items):
            page.goto(TECHNOPARK_STARTUPS_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector("#root", state="attached", timeout=60_000)
            page.wait_for_selector(
                "button:has-text('Voir Details')",
                state="visible",
                timeout=60_000,
            )

            detail_buttons = page.locator("button:has-text('Voir Details')")

            if index >= detail_buttons.count():
                break

            button = detail_buttons.nth(index)
            button.scroll_into_view_if_needed(timeout=30_000)
            button.click(timeout=30_000)

            page.wait_for_selector(".companyDetailsWrapper h2", timeout=30_000)

            candidate = parse_detail_page(page)

            if candidate and normalize_name(candidate.company_name):
                print(f"Collected: {candidate.company_name}")
                candidates.append(candidate)

        browser.close()

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
                website = COALESCE(website, ?),
                domain = COALESCE(domain, ?),
                public_email = COALESCE(public_email, ?),
                phone = COALESCE(phone, ?),
                city = COALESCE(city, ?),
                region = COALESCE(region, ?),
                sector_primary = COALESCE(sector_primary, ?),
                sector_secondary = COALESCE(sector_secondary, ?),
                company_type = COALESCE(company_type, ?),
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
        VALUES (?, ?, ?, ?, 'Morocco', ?, ?, ?, ?, ?, ?, ?, 75, 70, 1, ?, ?, ?, 'active')
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
                f"Fetched rendered startup cards from {TECHNOPARK_STARTUPS_URL}",
            ),
        )

        conn.commit()

    return inserted_or_updated