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
    "Expenses": "Expense_ID",
}

READ_CACHE_TTL = 120
MANUAL_SALES_LOG_COLUMNS = {"old_Invoice_No", "Invoice_No"}


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


def _without_manual_sales_log_columns(
    table_name: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    if table_name != "Sales_Log":
        return data
    return {
        key: value
        for key, value in data.items()
        if key not in MANUAL_SALES_LOG_COLUMNS
    }


def _preserve_manual_sales_log_columns(
    worksheet: gspread.Worksheet,
    data_frame: pd.DataFrame,
) -> pd.DataFrame:
    if "Sales_ID" not in data_frame.columns:
        return data_frame

    rows = worksheet.get_all_values()
    if not rows:
        return data_frame

    header = rows[0]
    protected_columns = [
        column for column in header if column in MANUAL_SALES_LOG_COLUMNS
    ]
    if not protected_columns or "Sales_ID" not in header:
        return data_frame

    sales_id_idx = header.index("Sales_ID")
    protected_indices = {
        column: header.index(column) for column in protected_columns
    }
    manual_values: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        sales_id = row[sales_id_idx].strip() if sales_id_idx < len(row) else ""
        if not sales_id:
            continue
        manual_values[sales_id] = {
            column: row[idx] if idx < len(row) else ""
            for column, idx in protected_indices.items()
        }

    updated = data_frame.copy()
    sales_ids = updated["Sales_ID"].astype(str).str.strip()
    for column in protected_columns:
        updated[column] = sales_ids.map(
            lambda sales_id: manual_values.get(sales_id, {}).get(column, "")
        )
    return updated


def _safe_header(raw_header: list[str], data_rows: list[list[str]]) -> list[str]:
    max_len = max([len(raw_header)] + [len(row) for row in data_rows] + [0])
    header = raw_header + [""] * (max_len - len(raw_header))
    seen: dict[str, int] = {}
    safe: list[str] = []
    for idx, value in enumerate(header, start=1):
        base = str(value).strip() or f"Column_{idx}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        name = base if count == 1 else f"{base}_{count}"
        safe.append(name)
    return safe


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def _read_table_cached(table_name: str, spreadsheet_id: str) -> pd.DataFrame:
    worksheet = _get_worksheet(table_name)
    rows = worksheet.get_all_values()
    if not rows:
        header = worksheet.row_values(1)
        return pd.DataFrame(columns=header)
    raw_header = rows[0]
    data_rows = rows[1:]
    if not data_rows:
        return pd.DataFrame(columns=_safe_header(raw_header, data_rows))
    header = _safe_header(raw_header, data_rows)
    max_len = len(header)
    padded_rows = [row + [""] * (max_len - len(row)) for row in data_rows]
    return pd.DataFrame(padded_rows, columns=header)


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
    data = _without_manual_sales_log_columns(table_name, data)
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

    data = _without_manual_sales_log_columns(table_name, data)
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
    if table_name == "Sales_Log":
        data_frame = _preserve_manual_sales_log_columns(worksheet, data_frame)
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


def generate_named_id(prefix: str, name: str, existing_ids: list[str] | None = None) -> str:
    return utils.generate_named_id(prefix, name, existing_ids or [])


def generate_customer_id(name: str, existing_ids: list[str] | None = None) -> str:
    return utils.generate_customer_id(name, existing_ids or [])


def generate_log_id(prefix: str, entry_date: object, existing_ids: list[str] | None = None) -> str:
    return utils.generate_log_id(prefix, entry_date, existing_ids or [])


def _update_foreign_keys(
    table_name: str,
    column: str,
    mapping: dict[str, str],
    *,
    recompute_stock: bool = True,
) -> int:
    if not mapping:
        return 0
    data_frame = read_table(table_name)
    if data_frame.empty or column not in data_frame.columns:
        return 0

    def _map_value(value: object) -> str:
        if value is None:
            return ""
        key = str(value).strip()
        if not key:
            return ""
        return mapping.get(key, key)

    updated = data_frame.copy()
    updated[column] = updated[column].apply(_map_value)
    changed = int((updated[column] != data_frame[column].astype(str)).sum())
    replace_table(table_name, updated, recompute_stock=recompute_stock)
    return changed


def _refresh_customer_names(table_name: str, name_map: dict[str, str]) -> int:
    if not name_map:
        return 0
    data_frame = read_table(table_name)
    if data_frame.empty or "Customer_ID" not in data_frame.columns:
        return 0

    updated = data_frame.copy()
    if "Customer_Name" not in updated.columns:
        updated["Customer_Name"] = ""
    ids = updated["Customer_ID"].astype(str).str.strip()
    updated_names = ids.map(lambda value: name_map.get(value, "")).fillna("")
    changed = int((updated["Customer_Name"].astype(str) != updated_names.astype(str)).sum())
    updated["Customer_Name"] = updated_names
    replace_table(table_name, updated, recompute_stock=False)
    return changed


def _rebuild_named_ids(
    table_name: str,
    id_column: str,
    prefix: str,
    *,
    name_column: str = "Name",
    force: bool = False,
) -> tuple[dict[str, str], int]:
    data_frame = read_table(table_name)
    if data_frame.empty:
        return {}, 0
    data_frame = data_frame.copy()
    if id_column not in data_frame.columns:
        data_frame[id_column] = ""
    if name_column not in data_frame.columns:
        data_frame[name_column] = ""

    existing_ids = [] if force else (
        data_frame[id_column].astype(str).str.strip().tolist()
    )
    mapping: dict[str, str] = {}
    updated_count = 0
    for idx in data_frame.index:
        old_id = str(data_frame.at[idx, id_column]).strip()
        if old_id and not force:
            continue
        name = str(data_frame.at[idx, name_column])
        new_id = generate_named_id(prefix, name, existing_ids)
        data_frame.at[idx, id_column] = new_id
        existing_ids.append(new_id)
        if old_id and old_id != new_id:
            mapping[old_id] = new_id
        updated_count += 1

    replace_table(table_name, data_frame, recompute_stock=False)
    return mapping, updated_count


def _rebuild_customer_ids(
    *,
    name_column: str = "Name",
    force: bool = False,
) -> tuple[dict[str, str], int]:
    table_name = "Customers"
    id_column = "Customer_ID"
    data_frame = read_table(table_name)
    if data_frame.empty:
        return {}, 0
    data_frame = data_frame.copy()
    if id_column not in data_frame.columns:
        data_frame[id_column] = ""
    if name_column not in data_frame.columns:
        data_frame[name_column] = ""

    existing_ids = [] if force else (
        data_frame[id_column].astype(str).str.strip().tolist()
    )
    mapping: dict[str, str] = {}
    updated_count = 0
    for idx in data_frame.index:
        old_id = str(data_frame.at[idx, id_column]).strip()
        if old_id and not force:
            continue
        name = str(data_frame.at[idx, name_column])
        new_id = generate_customer_id(name, existing_ids)
        data_frame.at[idx, id_column] = new_id
        existing_ids.append(new_id)
        if old_id and old_id != new_id:
            mapping[old_id] = new_id
        updated_count += 1

    replace_table(table_name, data_frame, recompute_stock=False)
    return mapping, updated_count


def _rebuild_log_ids(
    table_name: str,
    id_column: str,
    prefix: str,
    *,
    date_column: str = "Date",
    force: bool = False,
) -> int:
    data_frame = read_table(table_name)
    if data_frame.empty:
        return 0
    data_frame = data_frame.copy()
    if id_column not in data_frame.columns:
        data_frame[id_column] = ""
    if date_column not in data_frame.columns:
        data_frame[date_column] = ""

    existing_ids = [] if force else (
        data_frame[id_column].astype(str).str.strip().tolist()
    )
    updated_count = 0
    for idx in data_frame.index:
        old_id = str(data_frame.at[idx, id_column]).strip()
        if old_id and not force:
            continue
        entry_date = data_frame.at[idx, date_column]
        new_id = generate_log_id(prefix, entry_date, existing_ids)
        data_frame.at[idx, id_column] = new_id
        existing_ids.append(new_id)
        updated_count += 1

    replace_table(table_name, data_frame, recompute_stock=False)
    return updated_count


def rebuild_all_ids(*, force: bool = False) -> dict[str, int]:
    summary: dict[str, int] = {}

    supplier_map, supplier_count = _rebuild_named_ids(
        "Suppliers",
        "Supplier_ID",
        "SUP",
        force=force,
    )
    summary["Suppliers"] = supplier_count
    if supplier_map:
        summary["Raw_Material_Log.Supplier_ID"] = _update_foreign_keys(
            "Raw_Material_Log",
            "Supplier_ID",
            supplier_map,
            recompute_stock=False,
        )

    customer_map, customer_count = _rebuild_customer_ids(force=force)
    summary["Customers"] = customer_count
    if customer_map:
        summary["Sales_Log.Customer_ID"] = _update_foreign_keys(
            "Sales_Log",
            "Customer_ID",
            customer_map,
        )
        summary["Payments.Customer_ID"] = _update_foreign_keys(
            "Payments",
            "Customer_ID",
            customer_map,
        )
    customers_df = read_table("Customers")
    if not customers_df.empty and "Customer_ID" in customers_df.columns:
        name_map = (
            customers_df.set_index("Customer_ID")
            .get("Name", pd.Series(dtype=str))
            .astype(str)
            .str.strip()
            .to_dict()
        )
        summary["Sales_Log.Customer_Name"] = _refresh_customer_names(
            "Sales_Log", name_map
        )
        summary["Payments.Customer_Name"] = _refresh_customer_names(
            "Payments", name_map
        )

    labour_map, labour_count = _rebuild_named_ids(
        "Labour",
        "Labour_ID",
        "LAB",
        force=force,
    )
    summary["Labour"] = labour_count
    if labour_map:
        summary["Labour_Attendance.Labour_ID"] = _update_foreign_keys(
            "Labour_Attendance",
            "Labour_ID",
            labour_map,
        )

    summary["Raw_Material_Log"] = _rebuild_log_ids(
        "Raw_Material_Log",
        "RM_ID",
        "RM",
        force=force,
    )
    summary["Production_Log"] = _rebuild_log_ids(
        "Production_Log",
        "Prod_ID",
        "PROD",
        force=force,
    )
    summary["Sales_Log"] = _rebuild_log_ids(
        "Sales_Log",
        "Sales_ID",
        "SAL",
        force=force,
    )
    summary["Payments"] = _rebuild_log_ids(
        "Payments",
        "Payment_ID",
        "PAY",
        force=force,
    )
    summary["Expenses"] = _rebuild_log_ids(
        "Expenses",
        "Expense_ID",
        "EXP",
        force=force,
    )
    summary["Labour_Attendance"] = _rebuild_log_ids(
        "Labour_Attendance",
        "Attendance_ID",
        "ATT",
        force=force,
    )

    update_stock_log()
    return summary
