from __future__ import annotations

import streamlit as st

from antibitala.database.connection import DB_PATH, get_database_stats


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
        st.warning(
            "Database not initialized yet. Run: `uv run antibitala init-db`"
        )

    stats = get_database_stats()

    st.divider()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Companies", stats["companies"])
    col2.metric("Sources", stats["sources"])
    col3.metric("Contacts", stats["contacts"])
    col4.metric("Zones", stats["zones"])

    st.caption(f"Database path: `{DB_PATH}`")

    st.divider()

    query = st.text_input(
        "Search",
        placeholder="companies in Tangier, AI companies in Rabat, factories in Casablanca...",
    )

    if query:
        st.info(f"Search query received: {query}")


if __name__ == "__main__":
    main()
