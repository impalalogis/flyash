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
    reconciliation,
    stock,
)


def _init_connection() -> bool:
    config = database.get_gsheets_config()
    has_spreadsheet = bool(config["spreadsheet_id"] or config["spreadsheet_url"])
    has_service_account = bool(st.secrets.get("gcp_service_account"))

    with st.sidebar.expander("GSheets config", expanded=False):
        show_full = st.checkbox("Show full values", value=False, key="show_gsheets_config")

        def _mask(value: str) -> str:
            if not value:
                return "-"
            return value if show_full or len(value) <= 10 else f"...{value[-10:]}"

        st.write(f"spreadsheet_id: {_mask(config['spreadsheet_id'])}")
        st.write(f"spreadsheet_url: {_mask(config['spreadsheet_url'])}")
        st.write(f"resolved_id: {_mask(config['resolved_id'])}")

    if not has_service_account or not has_spreadsheet:
        missing = []
        if not has_service_account:
            missing.append("gcp_service_account")
        if not has_spreadsheet:
            missing.append("gsheets.spreadsheet_id or gsheets.spreadsheet_url")
        st.sidebar.error("Google Sheets connection failed")
        st.sidebar.caption(f"Missing {', '.join(missing)} in secrets.")
        return False

    try:
        database.get_spreadsheet()
        st.sidebar.success("Connected to Google Sheets")
        return True
    except Exception as exc:  # noqa: BLE001 - surface connection errors in UI
        st.sidebar.error("Google Sheets connection failed")
        st.sidebar.caption(str(exc))
        return False


def main() -> None:
    st.set_page_config(
        page_title="Fly-Ash Brick Management",
        page_icon="F",
        layout="wide",
    )
    st.title("Fly-Ash Brick Manufacturing")

    connected = _init_connection()
    if not connected:
        st.error("Google Sheets secrets are missing or invalid.")
        st.markdown(
            "Update Streamlit Cloud secrets with the following blocks, then reboot the app:"
        )
        st.code(
            """[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."

[gsheets]
spreadsheet_id = "YOUR_SHEET_ID"
""",
            language="toml",
        )
        st.stop()

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
        "Reconciliation": reconciliation.render,
        "Master Data": master_data.render,
    }

    selection = st.sidebar.radio("Navigate", list(pages.keys()))
    pages[selection]()


if __name__ == "__main__":
    main()
