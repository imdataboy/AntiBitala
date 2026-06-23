import streamlit as st


def main() -> None:
    st.set_page_config(
        page_title="AntiBitala",
        page_icon="🔎",
        layout="wide",
    )

    st.title("AntiBitala")
    st.subheader("Local Morocco company database for job seekers")

    st.write(
        "AntiBitala will help users discover reliable companies, "
        "career pages, contact pages, and public company information in Morocco."
    )

    query = st.text_input(
        "Search",
        placeholder="companies in Tangier, AI companies in Rabat, factories in Casablanca...",
    )

    if query:
        st.info(f"Search query received: {query}")

    st.divider()

    col1, col2, col3 = st.columns(3)

    col1.metric("Companies", "0")
    col2.metric("Sources", "0")
    col3.metric("Last update", "Not built yet")


if __name__ == "__main__":
    main()
