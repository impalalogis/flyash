from __future__ import annotations

import pandas as pd
import streamlit as st

import database
import utils


SUPPLIERS_COLUMNS = [
    "Supplier_ID",
    "Name",
    "Material_Type",
    "Unit_Rate",
    "Contact",
    "GST_Number",
]

CUSTOMERS_COLUMNS = [
    "Customer_ID",
    "Name",
    "Contact",
    "Address",
    "Outstanding_Balance",
    "Credit_Limit",
]

LABOUR_COLUMNS = [
    "Labour_ID",
    "Name",
    "Category",
    "Daily_Wage",
]


def _edit_table(
    title: str,
    table_name: str,
    columns: list[str],
    id_prefix: str,
    id_column: str,
    required_columns: list[str],
    numeric_columns: list[str],
) -> None:
    st.subheader(title)
    data_frame = database.read_table(table_name)
    if data_frame.empty:
        data_frame = pd.DataFrame(columns=columns)
    data_frame = utils.ensure_columns(data_frame, columns)

    edited = st.data_editor(
        data_frame,
        num_rows="dynamic",
        use_container_width=True,
        disabled=[id_column],
        key=f"{table_name}_editor",
    )

    if st.button(f"Save {title}", key=f"{table_name}_save"):
        updated = edited.copy()
        non_id_columns = [column for column in columns if column != id_column]
        updated = updated.replace("", pd.NA)
        updated = updated.dropna(how="all", subset=non_id_columns)
        updated = utils.ensure_ids(updated, id_column, id_prefix, database.generate_id)
        updated = updated.fillna("")
        updated = utils.ensure_columns(updated, columns)

        errors = []
        for column in required_columns:
            missing = updated[column].astype(str).str.strip() == ""
            if missing.any():
                errors.append(f"{column} is required for {missing.sum()} row(s).")

        for column in numeric_columns:
            values = pd.to_numeric(updated[column], errors="coerce")
            invalid = values.isna()
            if invalid.any():
                errors.append(f"{column} must be a number for {invalid.sum()} row(s).")

        if errors:
            for error in errors:
                st.error(error)
            return

        database.replace_table(table_name, updated)
        st.success(f"{title} updated.")


def render() -> None:
    st.header("Master Data")

    supplier_tab, customer_tab, labour_tab = st.tabs(["Suppliers", "Customers", "Labour"])
    with supplier_tab:
        _edit_table(
            "Suppliers",
            "Suppliers",
            SUPPLIERS_COLUMNS,
            "SUP",
            "Supplier_ID",
            required_columns=["Name", "Material_Type"],
            numeric_columns=["Unit_Rate"],
        )
    with customer_tab:
        _edit_table(
            "Customers",
            "Customers",
            CUSTOMERS_COLUMNS,
            "CUS",
            "Customer_ID",
            required_columns=["Name"],
            numeric_columns=["Outstanding_Balance", "Credit_Limit"],
        )
    with labour_tab:
        _edit_table(
            "Labour",
            "Labour",
            LABOUR_COLUMNS,
            "LAB",
            "Labour_ID",
            required_columns=["Name", "Category"],
            numeric_columns=["Daily_Wage"],
        )
