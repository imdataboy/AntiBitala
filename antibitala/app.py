from __future__ import annotations

import pandas as pd
import streamlit as st

from antibitala.database.connection import (
    DB_PATH,
    get_company_filter_options,
    get_database_stats,
    search_companies,
)


def rows_to_dataframe(rows: list) -> pd.DataFrame:
    """Convert SQLite rows to a display dataframe."""
    data = [dict(row) for row in rows]

    if not data:
        return pd.DataFrame(
            columns=[
                "company_name",
                "city",
                "region",
                "sector_primary",
                "website",
                "public_email",
                "phone",
                "trust_score",
                "job_relevance_score",
            ]
        )

    df = pd.DataFrame(data)

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

    return df[display_columns]


def main() -> None:
    st.set_page_config(
        page_title="AntiBitala",
        page_icon="🔎",
        layout="wide",
    )

    st.title("AntiBitala")
    st.subheader("Local Morocco company database for job seekers")

    st.write(
        "AntiBitala helps users discover reliable companies, career pages, "
        "contact pages, and public company information in Morocco."
    )

    if not DB_PATH.exists():
        st.warning("Database not initialized yet. Run: `uv run antibitala init-db`")

    stats = get_database_stats()

    st.divider()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Companies", stats["companies"])
    col2.metric("Configured sources", stats["configured_sources"])
    col3.metric("Company-source links", stats["company_sources"])
    col4.metric("Contacts", stats["contacts"])
    col5.metric("Zones", stats["zones"])

    st.caption(f"Database path: `{DB_PATH}`")

    st.divider()

    st.header("Search companies")

    options = get_company_filter_options()

    with st.sidebar:
        st.header("Filters")

        query = st.text_input(
            "Search",
            placeholder="company, sector, city, cybersecurity, data...",
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

        has_website = st.checkbox("Has website")
        has_email = st.checkbox("Has public email")
        has_phone = st.checkbox("Has phone")

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

    st.write(f"Showing **{len(df)}** result(s).")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "company_name": st.column_config.TextColumn("Company"),
            "city": st.column_config.TextColumn("City"),
            "region": st.column_config.TextColumn("Region"),
            "sector_primary": st.column_config.TextColumn("Main sector"),
            "sector_secondary": st.column_config.TextColumn("Technologies"),
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

    st.divider()

    st.subheader("Quick checks")

    col_a, col_b, col_c = st.columns(3)
    col_a.write("Try: `data`")
    col_b.write("Try: `cybersecurite`")
    col_c.write("Try city: `Rabat`")


if __name__ == "__main__":
    main()