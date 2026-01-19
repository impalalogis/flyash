import streamlit as st

import database
from views import (
    dashboard,
    entry_production,
    entry_raw_material,
    entry_sales,
    labour_attendance,
    master_data,
    payments,
    stock,
)


def _init_connection() -> None:
    try:
        database.get_spreadsheet()
        st.sidebar.success("Connected to Google Sheets")
    except Exception as exc:  # noqa: BLE001 - surface connection errors in UI
        st.sidebar.error("Google Sheets connection failed")
        st.sidebar.caption(str(exc))


def main() -> None:
    st.set_page_config(
        page_title="Fly-Ash Brick Management",
        page_icon="F",
        layout="wide",
    )
    st.title("Fly-Ash Brick Manufacturing")

    _init_connection()

    if st.sidebar.button("Refresh data"):
        database.clear_read_cache()
        st.sidebar.success("Cache cleared")

    pages = {
        "Dashboard": dashboard.render,
        "Raw Material Entry": entry_raw_material.render,
        "Production Entry": entry_production.render,
        "Sales Entry": entry_sales.render,
        "Payments": payments.render,
        "Labour Attendance": labour_attendance.render,
        "Stock": stock.render,
        "Master Data": master_data.render,
    }

    selection = st.sidebar.radio("Navigate", list(pages.keys()))
    pages[selection]()


if __name__ == "__main__":
    main()
