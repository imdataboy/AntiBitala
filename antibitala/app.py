from __future__ import annotations

import pandas as pd
import streamlit as st

from antibitala.database.connection import (
    DB_PATH,
    get_company_filter_options,
    get_database_stats,
    search_companies,
)
from antibitala.sources.industrial_zones import (
    get_zone_region_summary,
    get_zone_status_counts,
    validate_zone_coverage,
)


def has_value(value: object) -> bool:
    """Return True when a dataframe cell contains useful text."""
    if value is None:
        return False

    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass

    cleaned = str(value).strip().lower()

    return cleaned not in {"", "none", "null", "nan"}


def non_empty_count(df: pd.DataFrame, column: str) -> int:
    """Count non-empty values in a dataframe column."""
    if column not in df.columns:
        return 0

    return int(df[column].apply(has_value).sum())


def format_lead_status(row: pd.Series) -> str:
    """Create a simple job-seeker contactability label."""
    has_website = has_value(row.get("website"))
    has_email = has_value(row.get("public_email"))
    has_phone = has_value(row.get("phone"))

    if has_website and has_email:
        return "Good lead"

    if has_email or has_phone:
        return "Contactable"

    if has_website:
        return "Website only"

    return "Needs enrichment"


def lead_status_rank(status: str) -> int:
    """Rank lead status for sorting."""
    ranks = {
        "Good lead": 4,
        "Contactable": 3,
        "Website only": 2,
        "Needs enrichment": 1,
    }

    return ranks.get(status, 0)


def apply_lead_quality_filter(
    df: pd.DataFrame,
    lead_quality: str,
) -> pd.DataFrame:
    """Apply lead quality filter to the display dataframe."""
    if df.empty or lead_quality == "All":
        return df

    if lead_quality == "Good lead":
        return df[df["lead_status"] == "Good lead"]

    if lead_quality == "Contactable":
        return df[df["lead_status"].isin(["Good lead", "Contactable"])]

    if lead_quality == "Website only":
        return df[df["lead_status"] == "Website only"]

    if lead_quality == "Needs enrichment":
        return df[df["lead_status"] == "Needs enrichment"]

    return df


def rows_to_dataframe(rows: list) -> pd.DataFrame:
    """Convert SQLite rows to a user-facing display dataframe."""
    data = [dict(row) for row in rows]

    display_columns = [
        "company_name",
        "city",
        "region",
        "sector_primary",
        "website",
        "public_email",
        "phone",
        "lead_status",
    ]

    if not data:
        return pd.DataFrame(columns=display_columns)

    df = pd.DataFrame(data)

    df["lead_status"] = df.apply(format_lead_status, axis=1)
    df["lead_rank"] = df["lead_status"].apply(lead_status_rank)

    df = df.sort_values(
        by=["lead_rank", "company_name"],
        ascending=[False, True],
    )

    existing_columns = [column for column in display_columns if column in df.columns]

    return df[existing_columns]


def render_search_tab() -> None:
    """Render the job seeker search experience."""
    stats = get_database_stats()
    total_companies = int(stats["companies"] or 0)

    options = get_company_filter_options()

    with st.sidebar:
        st.header("Search filters")

        query = st.text_input(
            "Keyword",
            placeholder="data, cybersecurity, finance, marketing...",
        )

        city = st.selectbox(
            "City",
            ["All", *options["cities"]],
        )

        region = st.selectbox(
            "Region",
            ["All", *options["regions"]],
        )

        sector = st.selectbox(
            "Sector",
            ["All", *options["sectors"]],
        )

        st.divider()

        has_website = st.checkbox("Only companies with website")
        has_email = st.checkbox("Only companies with public email")
        has_phone = st.checkbox("Only companies with phone")

        lead_quality = st.selectbox(
            "Lead quality",
            [
                "All",
                "Good lead",
                "Contactable",
                "Website only",
                "Needs enrichment",
            ],
        )

        if total_companies <= 500:
            min_results = 1
            max_results = max(1, total_companies)
            default_limit = min(200, max_results)
            step = 1
        else:
            min_results = 20
            max_results = total_companies
            default_limit = 200
            step = 20

        limit = st.slider(
            f"Maximum results / DB size: {total_companies}",
            min_value=min_results,
            max_value=max_results,
            value=default_limit,
            step=step,
        )

    # Important:
    # If lead quality is selected, we fetch a larger pool first,
    # then filter in pandas. Otherwise, "Contactable" could show 0 only
    # because the first SQL-limited rows did not contain that status.
    search_limit = total_companies if lead_quality != "All" else limit

    rows = search_companies(
        query=query,
        city=city,
        region=region,
        sector=sector,
        has_website=has_website,
        has_email=has_email,
        has_phone=has_phone,
        limit=search_limit,
    )

    df = rows_to_dataframe(rows)
    df = apply_lead_quality_filter(df, lead_quality)
    df = df.head(limit)

    result_col1, result_col2, result_col3, result_col4 = st.columns(4)

    result_col1.metric("Results", len(df))
    result_col2.metric("With website", non_empty_count(df, "website"))
    result_col3.metric("With email", non_empty_count(df, "public_email"))
    result_col4.metric("With phone", non_empty_count(df, "phone"))

    st.caption(
        "Lead quality logic: Good lead = website + email; "
        "Contactable = email or phone; Website only = website without direct contact; "
        "Needs enrichment = no website, email, or phone."
    )

    if not df.empty:
        lead_counts = df["lead_status"].value_counts().to_dict()

        st.caption(
            "Current results: "
            + " | ".join(
                f"{status}: {count}"
                for status, count in lead_counts.items()
            )
        )

    if df.empty:
        st.info("No companies found. Try changing the city, sector, or filters.")
    else:
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "company_name": st.column_config.TextColumn(
                    "Company",
                    width="medium",
                ),
                "city": st.column_config.TextColumn(
                    "City",
                    width="small",
                ),
                "region": st.column_config.TextColumn(
                    "Region",
                    width="medium",
                ),
                "sector_primary": st.column_config.TextColumn(
                    "Sector",
                    width="medium",
                ),
                "website": st.column_config.LinkColumn(
                    "Website",
                    width="medium",
                ),
                "public_email": st.column_config.TextColumn(
                    "Email",
                    width="medium",
                ),
                "phone": st.column_config.TextColumn(
                    "Phone",
                    width="small",
                ),
                "lead_status": st.column_config.TextColumn(
                    "Lead status",
                    width="small",
                ),
            },
        )

    if not df.empty:
        csv_data = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Download results as CSV",
            data=csv_data,
            file_name="antibitala_search_results.csv",
            mime="text/csv",
        )

    st.subheader("Example searches")
    example_col1, example_col2, example_col3, example_col4 = st.columns(4)
    example_col1.write("`data`")
    example_col2.write("`cybersecurite`")
    example_col3.write("`Tanger`")
    example_col4.write("`finance`")


def render_zone_coverage_tab() -> None:
    """Render industrial/economic zone coverage dashboard."""
    st.header("Industrial and economic zone coverage")

    st.write(
        "This section is mainly for database quality control. "
        "It checks whether AntiBitala has zone coverage across all Moroccan regions."
    )

    coverage = validate_zone_coverage()
    status_counts = get_zone_status_counts()
    region_summary = get_zone_region_summary()

    covered_count = coverage["covered_count"]
    total_regions = coverage["total_regions"]
    missing_regions = coverage["missing_regions"]

    seed_count = status_counts.get("seed", 0)
    provisional_count = status_counts.get("provisional_seed", 0)
    verified_count = status_counts.get("verified", 0)

    zone_col1, zone_col2, zone_col3, zone_col4 = st.columns(4)
    zone_col1.metric("Region coverage", f"{covered_count}/{total_regions}")
    zone_col2.metric("Missing regions", len(missing_regions))
    zone_col3.metric("Seed zones", seed_count)
    zone_col4.metric("Provisional zones", provisional_count)

    st.metric("Verified zones", verified_count)

    if missing_regions:
        st.warning("Missing zone coverage: " + ", ".join(missing_regions))
    else:
        st.success("All 12 Moroccan regions have at least one zone seed.")

    if provisional_count > 0:
        st.info(
            f"{provisional_count} zones are provisional seeds. "
            "They should be verified later against official or regional sources."
        )

    region_summary_df = pd.DataFrame(region_summary)

    st.dataframe(
        region_summary_df,
        use_container_width=True,
        hide_index=True,
    )


def render_data_quality_tab() -> None:
    """Render database quality metrics."""
    st.header("Database quality")

    stats = get_database_stats()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Companies", stats["companies"])
    col2.metric("Configured sources", stats["configured_sources"])
    col3.metric("Company-source links", stats["company_sources"])
    col4.metric("Contacts", stats["contacts"])
    col5.metric("Zones", stats["zones"])

    st.write(
        "These indicators are for the builder. They help check whether the "
        "database is growing, source-backed, and useful."
    )

    st.caption(f"Database path: `{DB_PATH}`")


def main() -> None:
    st.set_page_config(
        page_title="AntiBitala",
        page_icon="🔎",
        layout="wide",
    )

    st.title("AntiBitala")
    st.subheader("Local Morocco company database for job seekers")

    st.write(
        "Find companies by city, sector, technology, and contact availability. "
        "The goal is to help job seekers discover employers and prepare outreach."
    )

    if not DB_PATH.exists():
        st.warning("Database not initialized yet. Run: `uv run antibitala init-db`")

    search_tab, zone_tab, quality_tab = st.tabs(
        [
            "Find companies",
            "Zone coverage",
            "Data quality",
        ]
    )

    with search_tab:
        render_search_tab()

    with zone_tab:
        render_zone_coverage_tab()

    with quality_tab:
        render_data_quality_tab()


if __name__ == "__main__":
    main()