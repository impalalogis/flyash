import importlib
from typing import Callable

import streamlit as st

import app_logging
import database

logger = app_logging.get_logger("main")

PAGE_MODULES: dict[str, str] = {
    "Dashboard": "pages.dashboard",
    "Dashboard-1": "pages.dashboard_1",
    "Labour Attendance": "pages.labour_attendance",
    "Raw Material Entry": "pages.raw_material_entry",
    "Production Entry": "pages.production_entry",
    "Stock": "pages.stock",
    "Sales Entry": "pages.sales_entry",
    "Payments": "pages.payments",
    "Expenses": "pages.expenses",
    "Collections & Reconciliation": "pages.collections_reconciliation",
    "Raw Material Reconciliation": "pages.raw_material_reconciliation",
    "Weekly Planner": "pages.weekly_planner",
    "Master Data": "pages.master_data",
}


def _load_page_renderer(page: str) -> Callable[[], None] | None:
    module_path = PAGE_MODULES.get(page)
    if not module_path:
        return None
    module = importlib.import_module(module_path)
    return getattr(module, "render", None)


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
        app_logging.log_event(logger, "gsheets_config_missing", missing=missing)
        return False

    try:
        database.ensure_gsheets_connection()
        st.sidebar.success("Connected to Google Sheets")
        return True
    except Exception as exc:  # noqa: BLE001 - surface connection errors in UI
        st.sidebar.error("Google Sheets connection failed")
        st.sidebar.caption(str(exc))
        app_logging.log_event(logger, "gsheets_connection_failed", error=str(exc))
        return False


def main() -> None:
    app_logging.setup_logging()
    app_logging.log_event(logger, "app_start")

    st.set_page_config(
        page_title="Fly-Ash Brick Management",
        page_icon="F",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
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
        app_logging.log_event(logger, "manual_cache_refresh")

    if "page" not in st.session_state:
        st.session_state["page"] = "Dashboard"

    def _nav_button(label: str) -> None:
        if st.button(label, key=f"nav_{label}"):
            st.session_state["page"] = label

    st.sidebar.title("Navigation")
    st.sidebar.caption(f"Current page: {st.session_state['page']}")

    with st.sidebar.expander("Dashboard", expanded=True):
        _nav_button("Dashboard")
        _nav_button("Dashboard-1")

    with st.sidebar.expander("Operation", expanded=False):
        _nav_button("Labour Attendance")
        _nav_button("Raw Material Entry")
        _nav_button("Production Entry")
        _nav_button("Stock")

    with st.sidebar.expander("Sales", expanded=False):
        _nav_button("Sales Entry")
        _nav_button("Payments")
        _nav_button("Expenses")

    with st.sidebar.expander("Recon", expanded=False):
        _nav_button("Collections & Reconciliation")
        _nav_button("Raw Material Reconciliation")

    with st.sidebar.expander("Planning", expanded=False):
        _nav_button("Weekly Planner")

    with st.sidebar.expander("Data", expanded=False):
        _nav_button("Master Data")

    page = st.session_state["page"]
    handler = _load_page_renderer(page)
    if handler:
        app_logging.log_event(logger, "page_render_start", page=page)
        handler()
        app_logging.log_event(logger, "page_render_complete", page=page)
    else:
        st.error("Page not found.")
        app_logging.log_event(logger, "page_not_found", page=page)


if __name__ == "__main__":
    main()
