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


def rows_to_dataframe(rows: list) -> pd.DataFrame:
    """Convert SQLite rows to a display dataframe."""
    data = [dict(row) for row in rows]

    display_columns = [
        "company_name",
        "city",
        "region",
        "sector_primary",
        "sector_secondary",
        "company_type",
        "website",
        "public_email",
        "phone",
        "trust_score",
        "job_relevance_score",
        "source_count",
        "last_checked_date",
    ]

    if not data:
        return pd.DataFrame(columns=display_columns)

    df = pd.DataFrame(data)

    existing_columns = [column for column in display_columns if column in df.columns]
    return df[existing_columns]


def render_company_cards(rows: list, max_cards: int = 30) -> None:
    """Render user-friendly company cards."""
    if not rows:
        st.info("No companies found. Try changing the city, sector, or filters.")
        return

    st.caption(
        f"Showing the first {min(len(rows), max_cards)} companies as cards. "
        "Use the table view or export for the full list."
    )

    for row in rows[:max_cards]:
        company = dict(row)

        name = company.get("company_name") or "Unnamed company"
        city = company.get("city") or "Unknown city"
        region = company.get("region") or "Unknown region"
        sector = company.get("sector_primary") or "Unknown sector"
        company_type = company.get("company_type") or "Unknown type"

        website = company.get("website")
        email = company.get("public_email")
        phone = company.get("phone")

        trust_score = company.get("trust_score") or 0
        job_score = company.get("job_relevance_score") or 0
        source_count = company.get("source_count") or 0

        with st.container(border=True):
            st.markdown(f"### {name}")
            st.caption(f"{city} • {region} • {sector} • {company_type}")

            metric_col1, metric_col2, metric_col3 = st.columns(3)
            metric_col1.metric("Trust", trust_score)
            metric_col2.metric("Job relevance", job_score)
            metric_col3.metric("Sources", source_count)

            contact_parts = []

            if website:
                contact_parts.append(f"[Website]({website})")

            if email:
                contact_parts.append(f"Email: `{email}`")

            if phone:
                contact_parts.append(f"Phone: `{phone}`")

            if contact_parts:
                st.markdown(" • ".join(contact_parts))
            else:
                st.write("No direct website, email, or phone found yet.")

            if company.get("sector_secondary"):
                st.caption(f"Details: {company['sector_secondary']}")


def render_search_tab() -> None:
    """Render the job seeker search experience."""



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

        limit = st.slider(
            "Maximum results",
            min_value=20,
            max_value=500,
            value=200,
            step=20,
        )

    rows = search_companies(
        query=query,
        city=city,
        region=region,
        sector=sector,
        has_website=has_website,
        has_email=has_email,
        has_phone=has_phone,
        limit=limit,
    )

    df = rows_to_dataframe(rows)

    result_col1, result_col2, result_col3 = st.columns(3)
    result_col1.metric("Results", len(df))
    result_col2.metric(
        "With website",
        int(df["website"].notna().sum()) if "website" in df else 0,
    )
    result_col3.metric(
        "With email",
        int(df["public_email"].notna().sum()) if "public_email" in df else 0,
    )

    if df.empty:
        st.info("No companies found. Try changing the city, sector, or filters.")
    else:
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "company_name": st.column_config.TextColumn("Company"),
                "city": st.column_config.TextColumn("City"),
                "region": st.column_config.TextColumn("Region"),
                "sector_primary": st.column_config.TextColumn("Main sector"),
                "sector_secondary": st.column_config.TextColumn("Details"),
                "company_type": st.column_config.TextColumn("Type"),
                "website": st.column_config.LinkColumn("Website"),
                "public_email": st.column_config.TextColumn("Public email"),
                "phone": st.column_config.TextColumn("Phone"),
                "trust_score": st.column_config.NumberColumn("Trust"),
                "job_relevance_score": st.column_config.NumberColumn("Job score"),
                "source_count": st.column_config.NumberColumn("Sources"),
                "last_checked_date": st.column_config.TextColumn("Last checked"),
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