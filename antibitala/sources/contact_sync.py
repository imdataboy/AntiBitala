from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from antibitala.database.connection import get_connection


@dataclass(frozen=True)
class ContactCandidate:
    company_id: int
    contact_type: str
    contact_value: str
    contact_source_url: str | None
    confidence_score: int
    last_checked_date: str | None


def clean_text(value: object) -> str | None:
    """Return clean text or None."""
    if value is None:
        return None

    cleaned = str(value).strip()

    if not cleaned or cleaned.lower() in {"none", "null", "nan"}:
        return None

    return cleaned


def normalize_email(value: object) -> str | None:
    """Normalize and validate an email."""
    cleaned = clean_text(value)

    if not cleaned:
        return None

    cleaned = cleaned.lower()

    match = re.search(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        cleaned,
    )

    if not match:
        return None

    return match.group(0)


def normalize_phone(value: object) -> str | None:
    """Normalize and validate a phone number."""
    cleaned = clean_text(value)

    if not cleaned:
        return None

    # Keep + and digits only.
    normalized = re.sub(r"[^\d+]", "", cleaned)

    # Avoid tiny values that are not real phone numbers.
    digits = re.sub(r"\D", "", normalized)

    if len(digits) < 8:
        return None

    return normalized


def normalize_website(value: object) -> str | None:
    """Normalize a website URL."""
    cleaned = clean_text(value)

    if not cleaned:
        return None

    # Some imported values may contain multiple malformed pieces.
    match = re.search(r"https?://[^\s\]\)\"']+", cleaned)

    if match:
        return match.group(0).rstrip(".,;")

    if "." not in cleaned:
        return None

    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"

    return cleaned.rstrip(".,;")


def build_contact_candidates(company: sqlite3.Row) -> list[ContactCandidate]:
    """Build contact candidates from one company row."""
    company_id = int(company["company_id"])
    website = normalize_website(company["website"])
    email = normalize_email(company["public_email"])
    phone = normalize_phone(company["phone"])
    last_checked_date = company["last_checked_date"]

    candidates: list[ContactCandidate] = []

    if email:
        candidates.append(
            ContactCandidate(
                company_id=company_id,
                contact_type="email",
                contact_value=email,
                contact_source_url=website,
                confidence_score=85,
                last_checked_date=last_checked_date,
            )
        )

    if phone:
        candidates.append(
            ContactCandidate(
                company_id=company_id,
                contact_type="phone",
                contact_value=phone,
                contact_source_url=website,
                confidence_score=75,
                last_checked_date=last_checked_date,
            )
        )

    if website:
        candidates.append(
            ContactCandidate(
                company_id=company_id,
                contact_type="website",
                contact_value=website,
                contact_source_url=website,
                confidence_score=70,
                last_checked_date=last_checked_date,
            )
        )

    return candidates


def upsert_contact(conn: sqlite3.Connection, candidate: ContactCandidate) -> bool:
    """Insert or update one contact. Return True when inserted."""
    existing = conn.execute(
        """
        SELECT contact_id
        FROM company_contacts
        WHERE company_id = ?
          AND contact_type = ?
          AND contact_value = ?
        LIMIT 1
        """,
        (
            candidate.company_id,
            candidate.contact_type,
            candidate.contact_value,
        ),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE company_contacts
            SET
                contact_source_url = COALESCE(?, contact_source_url),
                confidence_score = MAX(confidence_score, ?),
                last_checked_date = COALESCE(?, last_checked_date)
            WHERE contact_id = ?
            """,
            (
                candidate.contact_source_url,
                candidate.confidence_score,
                candidate.last_checked_date,
                existing["contact_id"],
            ),
        )
        return False

    conn.execute(
        """
        INSERT INTO company_contacts (
            company_id,
            contact_type,
            contact_value,
            contact_source_url,
            confidence_score,
            last_checked_date
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            candidate.company_id,
            candidate.contact_type,
            candidate.contact_value,
            candidate.contact_source_url,
            candidate.confidence_score,
            candidate.last_checked_date,
        ),
    )

    return True


def sync_company_contacts(limit: int | None = None) -> dict[str, int]:
    """Sync contacts from companies table into company_contacts."""
    sql = """
        SELECT
            company_id,
            website,
            public_email,
            phone,
            last_checked_date
        FROM companies
        WHERE
            (website IS NOT NULL AND TRIM(website) != '')
            OR (public_email IS NOT NULL AND TRIM(public_email) != '')
            OR (phone IS NOT NULL AND TRIM(phone) != '')
    """

    params: list[int] = []

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    inserted = 0
    updated = 0
    candidates_seen = 0

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

        for company in rows:
            candidates = build_contact_candidates(company)

            for candidate in candidates:
                candidates_seen += 1

                was_inserted = upsert_contact(conn, candidate)

                if was_inserted:
                    inserted += 1
                else:
                    updated += 1

        conn.execute(
            """
            INSERT INTO update_log (
                source_name,
                records_added,
                records_updated,
                notes
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "company_contacts_sync",
                inserted,
                updated,
                "Synced contacts from companies.website, companies.public_email, and companies.phone.",
            ),
        )

        conn.commit()

    return {
        "companies_scanned": len(rows),
        "candidates_seen": candidates_seen,
        "inserted": inserted,
        "updated": updated,
    }


def get_contact_stats() -> dict[str, int]:
    """Return contact counts by type."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM company_contacts").fetchone()[0]

        rows = conn.execute(
            """
            SELECT contact_type, COUNT(*) AS total
            FROM company_contacts
            GROUP BY contact_type
            ORDER BY total DESC
            """
        ).fetchall()

    stats = {"total": int(total)}
    stats.update({row["contact_type"]: int(row["total"]) for row in rows})

    return stats


def sample_contacts(limit: int = 30) -> list[sqlite3.Row]:
    """Return sample normalized contacts."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                c.company_name,
                c.city,
                c.region,
                cc.contact_type,
                cc.contact_value,
                cc.confidence_score,
                cc.contact_source_url
            FROM company_contacts cc
            JOIN companies c ON c.company_id = cc.company_id
            ORDER BY cc.confidence_score DESC, c.company_name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
