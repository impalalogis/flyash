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
    "GST",
    "Contact",
    "City",
    "Address",
    "Outstanding_Balance",
]

LABOUR_COLUMNS = [
    "Labour_ID",
    "Name",
    "Category",
    "Active_Status",
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
    column_config: dict | None = None,
    id_builder=None,
) -> None:
    st.subheader(title)
    data_frame = database.read_table(table_name)
    if data_frame.empty:
        data_frame = pd.DataFrame(columns=columns)
    data_frame = utils.ensure_columns(data_frame, columns)

    edited = st.data_editor(
        data_frame,
        num_rows="dynamic",
        width="stretch",
        disabled=[id_column],
        column_config=column_config,
        key=f"{table_name}_editor",
    )

    if st.button(f"Save {title}", key=f"{table_name}_save"):
        updated = edited.copy()
        non_id_columns = [column for column in columns if column != id_column]
        updated = updated.replace("", pd.NA)
        updated = updated.dropna(how="all", subset=non_id_columns)

        existing_ids = (
            updated.get(id_column, pd.Series(dtype=str)).astype(str).str.strip().tolist()
        )
        for idx in updated.index:
            current = str(updated.at[idx, id_column]).strip() if id_column in updated.columns else ""
            if current:
                continue
            name_value = str(updated.at[idx, "Name"]) if "Name" in updated.columns else ""
            if id_builder:
                new_id = id_builder(name_value, existing_ids)
            else:
                new_id = database.generate_named_id(id_prefix, name_value, existing_ids)
            updated.at[idx, id_column] = new_id
            existing_ids.append(new_id)

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
            "CUST",
            "Customer_ID",
            required_columns=["Name"],
            numeric_columns=["Outstanding_Balance"],
            id_builder=database.generate_customer_id,
        )
    with labour_tab:
        _edit_table(
            "Labour",
            "Labour",
            LABOUR_COLUMNS,
            "LAB",
            "Labour_ID",
            required_columns=["Name", "Category", "Active_Status"],
            numeric_columns=["Daily_Wage"],
            column_config={
                "Active_Status": st.column_config.SelectboxColumn(
                    "Active Status",
                    options=["Active", "Inactive"],
                    required=True,
                ),
            },
        )

    st.divider()
    st.subheader("ID Maintenance")
    st.caption(
        "Use this to fill missing IDs or rebuild all IDs. "
        "Rebuilding updates all related references."
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Fill missing IDs", key="fill_missing_ids"):
            summary = database.rebuild_all_ids(force=False)
            st.success("Missing IDs filled.")
            st.json(summary)
    with col2:
        confirm = st.checkbox("I understand this will rewrite IDs", value=False)
        confirm_text = st.text_input("Type REBUILD to confirm", value="")
        if st.button("Rebuild all IDs", key="rebuild_all_ids"):
            if not confirm or confirm_text.strip().upper() != "REBUILD":
                st.error("Confirmation required to rebuild IDs.")
            else:
                summary = database.rebuild_all_ids(force=True)
                st.success("All IDs rebuilt.")
                st.json(summary)
