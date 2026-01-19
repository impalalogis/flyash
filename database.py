from __future__ import annotations

from datetime import datetime
import re
import uuid
from typing import Any, Dict

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

import utils

ID_COLUMNS = {
    "Suppliers": "Supplier_ID",
    "Customers": "Customer_ID",
    "Labour": "Labour_ID",
    "Labour_Attendance": "Attendance_ID",
    "Raw_Material_Log": "RM_ID",
    "Production_Log": "Prod_ID",
    "Sales_Log": "Sales_ID",
    "Payments": "Payment_ID",
}

READ_CACHE_TTL = 120


def _should_recompute_stock(table_name: str) -> bool:
    return table_name in {"Raw_Material_Log", "Production_Log"}


def _extract_spreadsheet_id(value: str) -> str:
    if "docs.google.com" in value:
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
        if match:
            return match.group(1)
    return value.strip()


def _get_spreadsheet_id() -> str:
    config = get_gsheets_config()
    spreadsheet_value = config["spreadsheet_id"] or config["spreadsheet_url"]
    if not spreadsheet_value:
        raise ValueError("Missing gsheets.spreadsheet_id or gsheets.spreadsheet_url")
    return config["resolved_id"]


def get_gsheets_config() -> dict[str, str]:
    gsheets = st.secrets.get("gsheets", {})
    spreadsheet_id = str(gsheets.get("spreadsheet_id", "")).strip()
    spreadsheet_url = str(gsheets.get("spreadsheet_url", "")).strip()
    resolved = ""
    if spreadsheet_id or spreadsheet_url:
        resolved = _extract_spreadsheet_id(spreadsheet_id or spreadsheet_url)
    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "resolved_id": resolved,
    }


@st.cache_resource
def get_client() -> gspread.Client:
    service_account = st.secrets.get("gcp_service_account")
    if not service_account:
        raise ValueError("Missing gcp_service_account in Streamlit secrets")
    credentials = Credentials.from_service_account_info(
        service_account,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(credentials)


@st.cache_resource
def get_spreadsheet() -> gspread.Spreadsheet:
    client = get_client()
    spreadsheet_id = _get_spreadsheet_id()
    return client.open_by_key(spreadsheet_id)


def _get_worksheet(table_name: str) -> gspread.Worksheet:
    return get_spreadsheet().worksheet(table_name)


def _get_header(worksheet: gspread.Worksheet) -> list[str]:
    header = worksheet.row_values(1)
    if not header:
        raise ValueError(f"Worksheet {worksheet.title} has no header row")
    return header


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def _read_table_cached(table_name: str, spreadsheet_id: str) -> pd.DataFrame:
    worksheet = _get_worksheet(table_name)
    records = worksheet.get_all_records()
    if not records:
        header = worksheet.row_values(1)
        return pd.DataFrame(columns=header)
    return pd.DataFrame(records)


def read_table(table_name: str) -> pd.DataFrame:
    spreadsheet_id = _get_spreadsheet_id()
    return _read_table_cached(table_name, spreadsheet_id).copy()


def clear_read_cache() -> None:
    _read_table_cached.clear()


def update_stock_log() -> None:
    clear_read_cache()
    raw_df = read_table("Raw_Material_Log")
    production_df = read_table("Production_Log")
    stock_df = utils.compute_stock_log(raw_df, production_df)
    replace_table("Stock_Log", stock_df, recompute_stock=False)


def insert_row(table_name: str, data: Dict[str, Any], *, recompute_stock: bool = True) -> None:
    worksheet = _get_worksheet(table_name)
    header = _get_header(worksheet)
    row = [data.get(column, "") for column in header]
    worksheet.append_row(row, value_input_option="USER_ENTERED")
    clear_read_cache()
    if recompute_stock and _should_recompute_stock(table_name):
        update_stock_log()


def _find_row_cell(
    worksheet: gspread.Worksheet,
    row_id: str,
    header: list[str],
    table_name: str,
) -> gspread.Cell:
    id_column = ID_COLUMNS.get(table_name, header[0])
    if id_column not in header:
        raise ValueError(f"ID column {id_column} not found in {table_name}")
    id_col_index = header.index(id_column) + 1
    try:
        return worksheet.find(str(row_id), in_column=id_col_index)
    except gspread.exceptions.CellNotFound as exc:
        raise ValueError(f"Row ID {row_id} not found in {table_name}") from exc


def update_row(
    table_name: str,
    row_id: str,
    data: Dict[str, Any],
    *,
    recompute_stock: bool = True,
) -> None:
    worksheet = _get_worksheet(table_name)
    header = _get_header(worksheet)
    cell = _find_row_cell(worksheet, row_id, header, table_name)

    row_values = worksheet.row_values(cell.row)
    if len(row_values) < len(header):
        row_values.extend([""] * (len(header) - len(row_values)))

    for key, value in data.items():
        if key in header:
            row_values[header.index(key)] = value

    end_cell = gspread.utils.rowcol_to_a1(cell.row, len(header))
    worksheet.update(
        f"A{cell.row}:{end_cell}",
        [row_values],
        value_input_option="USER_ENTERED",
    )
    clear_read_cache()
    if recompute_stock and _should_recompute_stock(table_name):
        update_stock_log()


def delete_row(table_name: str, row_id: str, *, recompute_stock: bool = True) -> None:
    worksheet = _get_worksheet(table_name)
    header = _get_header(worksheet)
    cell = _find_row_cell(worksheet, row_id, header, table_name)
    worksheet.delete_rows(cell.row)
    clear_read_cache()
    if recompute_stock and _should_recompute_stock(table_name):
        update_stock_log()


def replace_table(
    table_name: str,
    data_frame: pd.DataFrame,
    *,
    recompute_stock: bool = True,
) -> None:
    worksheet = _get_worksheet(table_name)
    data_frame = data_frame.copy()
    data_frame = data_frame.where(pd.notnull(data_frame), "")
    rows = [data_frame.columns.tolist()] + data_frame.values.tolist()
    worksheet.clear()
    if rows:
        worksheet.update("A1", rows, value_input_option="USER_ENTERED")
    clear_read_cache()
    if recompute_stock and _should_recompute_stock(table_name):
        update_stock_log()


def generate_id(prefix: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d")
    unique = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{timestamp}-{unique}"
