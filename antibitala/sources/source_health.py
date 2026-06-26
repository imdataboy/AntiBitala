from __future__ import annotations

from dataclasses import dataclass

import requests

from antibitala.database.connection import get_connection


@dataclass(frozen=True)
class SourceHealthResult:
    source_key: str
    source_name: str
    region: str | None
    base_url: str | None
    status: str
    http_status: int | None
    error: str | None


def normalize_url(url: str | None) -> str | None:
    """Normalize a URL before checking it."""
    if not url:
        return None

    cleaned = url.strip()

    if not cleaned:
        return None

    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"

    return cleaned


def check_url_health(url: str | None, timeout: float = 8.0) -> tuple[str, int | None, str | None]:
    """Check whether a URL is reachable."""
    normalized_url = normalize_url(url)

    if not normalized_url:
        return "missing_url", None, "No base_url configured."

    headers = {
        "User-Agent": (
            "AntiBitalaBot/0.1 "
            "(local research tool; contact: https://github.com/imdataboy/AntiBitala)"
        )
    }

    try:
        response = requests.get(
            normalized_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )

        if 200 <= response.status_code < 400:
            return "ok", response.status_code, None

        return "http_error", response.status_code, f"HTTP {response.status_code}"

    except requests.exceptions.RequestException as exc:
        return "request_error", None, str(exc)


def get_regional_sources_for_health_check() -> list[dict[str, object]]:
    """Return enabled CRI/regional sources for health checking."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                source_key,
                source_name,
                region,
                base_url
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

    return [dict(row) for row in rows]


def check_regional_source_health(timeout: float = 8.0) -> list[SourceHealthResult]:
    """Check health of enabled regional ecosystem sources."""
    sources = get_regional_sources_for_health_check()
    results: list[SourceHealthResult] = []

    for source in sources:
        status, http_status, error = check_url_health(
            source["base_url"],
            timeout=timeout,
        )

        results.append(
            SourceHealthResult(
                source_key=str(source["source_key"]),
                source_name=str(source["source_name"]),
                region=source["region"],
                base_url=source["base_url"],
                status=status,
                http_status=http_status,
                error=error,
            )
        )

    return results


def summarize_health_results(
    results: list[SourceHealthResult],
) -> dict[str, int]:
    """Summarize source health results by status."""
    summary: dict[str, int] = {}

    for result in results:
        summary[result.status] = summary.get(result.status, 0) + 1

    return summary

