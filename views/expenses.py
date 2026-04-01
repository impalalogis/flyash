from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database
import utils


EXPENSE_COLUMNS = [
    "Expense_ID",
    "Date",
    "Month",
    "Expense_Category",
    "Expense_Subcategory",
    "Expense_Type",
    "Description",
    "Vendor_Name",
    "Amount",
    "Payment_Mode",
    "Reference_No",
    "Notes",
]


EXPENSE_CATEGORIES = {
    "Office Expense": [
        "Food",
        "Electricity",
        "Registration Bill",
        "Stationery",
        "Internet/Phone",
        "Misc Office",
    ],
    "Operational": [
        "Labour",
        "Site Expense",
        "Utilities",
        "Admin Expense",
        "Misc Operational",
    ],
    "Tractor": [
        "Tractor Diesel",
        "Tractor Repair",
        "Tractor Maintenance",
        "Tractor Driver",
    ],
    "Diesel": [
        "Generator Diesel",
        "Transport Diesel",
        "Machine Diesel",
    ],
    "Machine Parts": [
        "Machine Parts",
        "Repair & Service",
        "Tools",
    ],
    "Other": [
        "Other",
    ],
}


def _subcategory_options(category: str) -> list[str]:
    options = EXPENSE_CATEGORIES.get(category, [])
    return options or ["Other"]


def _coerce_expense_columns(data_frame: pd.DataFrame) -> pd.DataFrame:
    return utils.coerce_numeric_columns(data_frame, ["Amount"])


def render() -> None:
    st.header("Expenses")
    st.caption(
        "Track business expenses (labour, food, electricity, tractor diesel, "
        "registration bill, machine parts, etc.) for accurate profitability."
    )

    with st.form("expense_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            expense_date = st.date_input("Date", value=date.today())
            category = st.selectbox("Category", list(EXPENSE_CATEGORIES.keys()))
            subcategory = st.selectbox(
                "Subcategory",
                _subcategory_options(category),
            )
            expense_type = st.selectbox(
                "Expense Type",
                ["Short-term", "Long-term", "Both"],
                index=0,
            )
            amount = st.number_input("Amount", min_value=0.0, step=1.0)
        with col2:
            description = st.text_input("Description")
            vendor_name = st.text_input("Vendor Name")
            payment_mode = st.selectbox(
                "Payment Mode",
                ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"],
                index=0,
            )
            reference_no = st.text_input("Reference No")
            notes = st.text_input("Notes")
        submitted = st.form_submit_button("Save Expense")

    if submitted:
        errors: list[str] = []
        if amount <= 0:
            errors.append("Amount must be greater than 0.")
        if not category:
            errors.append("Category is required.")
        if not subcategory:
            errors.append("Subcategory is required.")
        if errors:
            for error in errors:
                st.error(error)
        else:
            existing_ids = (
                database.read_table("Expenses")
                .get("Expense_ID", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .tolist()
            )
            expense_id = database.generate_log_id("EXP", expense_date, existing_ids)
            data = {
                "Expense_ID": expense_id,
                "Date": expense_date.isoformat(),
                "Month": utils.to_month_string(expense_date),
                "Expense_Category": category,
                "Expense_Subcategory": subcategory,
                "Expense_Type": expense_type,
                "Description": description,
                "Vendor_Name": vendor_name,
                "Amount": amount,
                "Payment_Mode": payment_mode,
                "Reference_No": reference_no,
                "Notes": notes,
            }
            data = {key: data.get(key, "") for key in EXPENSE_COLUMNS}
            database.insert_row("Expenses", data, recompute_stock=False)
            st.success("Expense saved.")

    st.subheader("Expense Records")
    entries = database.read_table("Expenses")
    if entries.empty:
        st.info("No expense records yet.")
        return
    if "Expense_ID" not in entries.columns:
        st.error("Missing Expense_ID column in Expenses sheet.")
        return

    entries = _coerce_expense_columns(entries)

    with st.expander("Update expense", expanded=False):
        editable = entries.copy()
        editable["Expense_ID"] = editable["Expense_ID"].astype(str).str.strip()
        editable = editable[editable["Expense_ID"] != ""]
        if editable.empty:
            st.info("No expense rows available to edit.")
        else:
            options = editable["Expense_ID"].tolist()
            selected_id = st.selectbox("Select Expense ID", options, key="expense_update_id")
            selected_row = editable.loc[editable["Expense_ID"] == selected_id].iloc[0]
            default_date = pd.to_datetime(
                str(selected_row.get("Date", "")).strip(),
                errors="coerce",
                dayfirst=True,
            )
            if pd.isna(default_date):
                default_date = pd.Timestamp(date.today())
            current_category = str(selected_row.get("Expense_Category", "")).strip()
            if current_category not in EXPENSE_CATEGORIES:
                current_category = "Other"
            current_subcategory = str(selected_row.get("Expense_Subcategory", "")).strip()
            sub_options = _subcategory_options(current_category)
            if current_subcategory not in sub_options:
                current_subcategory = sub_options[0]
            current_type = str(selected_row.get("Expense_Type", "")).strip()
            type_options = ["Short-term", "Long-term", "Both"]
            if current_type not in type_options:
                current_type = "Short-term"

            with st.form("expense_update_form", clear_on_submit=False):
                up_col1, up_col2 = st.columns(2)
                with up_col1:
                    upd_date = st.date_input(
                        "Date",
                        value=default_date.date(),
                        key="expense_upd_date",
                    )
                    upd_category = st.selectbox(
                        "Category",
                        list(EXPENSE_CATEGORIES.keys()),
                        index=list(EXPENSE_CATEGORIES.keys()).index(current_category),
                        key="expense_upd_category",
                    )
                    upd_subcategory = st.selectbox(
                        "Subcategory",
                        _subcategory_options(upd_category),
                        key="expense_upd_subcategory",
                    )
                    upd_type = st.selectbox(
                        "Expense Type",
                        type_options,
                        index=type_options.index(current_type),
                        key="expense_upd_type",
                    )
                    upd_amount = st.number_input(
                        "Amount",
                        min_value=0.0,
                        value=float(utils.safe_float(selected_row.get("Amount", 0.0))),
                        step=1.0,
                        key="expense_upd_amount",
                    )
                with up_col2:
                    upd_description = st.text_input(
                        "Description",
                        value=str(selected_row.get("Description", "")),
                        key="expense_upd_description",
                    )
                    upd_vendor = st.text_input(
                        "Vendor Name",
                        value=str(selected_row.get("Vendor_Name", "")),
                        key="expense_upd_vendor",
                    )
                    payment_options = ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"]
                    current_mode = str(selected_row.get("Payment_Mode", "")).strip()
                    if current_mode not in payment_options:
                        current_mode = "Cash"
                    upd_mode = st.selectbox(
                        "Payment Mode",
                        payment_options,
                        index=payment_options.index(current_mode),
                        key="expense_upd_mode",
                    )
                    upd_reference = st.text_input(
                        "Reference No",
                        value=str(selected_row.get("Reference_No", "")),
                        key="expense_upd_reference",
                    )
                    upd_notes = st.text_input(
                        "Notes",
                        value=str(selected_row.get("Notes", "")),
                        key="expense_upd_notes",
                    )

                update_submitted = st.form_submit_button("Update Expense")

            if update_submitted:
                if upd_amount <= 0:
                    st.error("Amount must be greater than 0.")
                else:
                    update_data = {
                        "Date": upd_date.isoformat(),
                        "Month": utils.to_month_string(upd_date),
                        "Expense_Category": upd_category,
                        "Expense_Subcategory": upd_subcategory,
                        "Expense_Type": upd_type,
                        "Description": upd_description,
                        "Vendor_Name": upd_vendor,
                        "Amount": upd_amount,
                        "Payment_Mode": upd_mode,
                        "Reference_No": upd_reference,
                        "Notes": upd_notes,
                    }
                    database.update_row(
                        "Expenses",
                        selected_id,
                        update_data,
                        recompute_stock=False,
                    )
                    st.success("Expense updated.")
                    st.rerun()

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        category_filter = st.selectbox(
            "Filter by category",
            ["All"] + sorted(
                entries.get("Expense_Category", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .replace("", pd.NA)
                .dropna()
                .unique()
                .tolist()
            ),
        )
    with filter_col2:
        subcategory_filter = st.selectbox(
            "Filter by subcategory",
            ["All"] + sorted(
                entries.get("Expense_Subcategory", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .replace("", pd.NA)
                .dropna()
                .unique()
                .tolist()
            ),
        )

    filtered_entries = entries.copy()
    if category_filter != "All":
        filtered_entries = filtered_entries[
            filtered_entries["Expense_Category"].astype(str).str.strip() == category_filter
        ]
    if subcategory_filter != "All":
        filtered_entries = filtered_entries[
            filtered_entries["Expense_Subcategory"].astype(str).str.strip()
            == subcategory_filter
        ]

    display_entries = filtered_entries.copy()
    display_entries["Delete"] = False
    display_entries = display_entries[
        ["Delete"] + [column for column in filtered_entries.columns]
    ]
    edited = st.data_editor(
        display_entries,
        width="stretch",
        disabled=[column for column in display_entries.columns if column != "Delete"],
        key="expense_entries",
    )

    if st.button("Delete selected", key="expense_delete"):
        selected = (
            edited.loc[edited["Delete"] == True, "Expense_ID"]
            .dropna()
            .astype(str)
            .tolist()
        )
        if not selected:
            st.warning("Select at least one entry to delete.")
        else:
            for expense_id in selected:
                database.delete_row("Expenses", expense_id, recompute_stock=False)
            st.success("Selected expenses deleted.")
            st.rerun()

    st.subheader("Validation")
    rules = {
        "Date": {"required": True},
        "Expense_Category": {"required": True},
        "Expense_Subcategory": {"required": True},
        "Amount": {"numeric": True, "min": 0},
    }
    mask, _ = utils.build_validation_mask(entries, rules)
    if mask.any().any():
        st.caption("Rows highlighted in red need correction.")
        st.dataframe(utils.style_invalid(entries, mask), width="stretch")
        invalid_rows = entries[mask.any(axis=1)].copy()
        edited_invalid = st.data_editor(
            invalid_rows,
            width="stretch",
            disabled=["Expense_ID"],
            key="expense_invalid_editor",
        )
        if st.button("Save Corrections", key="expense_save_corrections"):
            for _, row in edited_invalid.iterrows():
                row = row.where(pd.notnull(row), "")
                row_id = str(row.get("Expense_ID", "")).strip()
                if not row_id:
                    continue
                entry_date = pd.to_datetime(
                    str(row.get("Date", "")).strip(),
                    errors="coerce",
                    dayfirst=True,
                )
                if pd.notna(entry_date):
                    row["Date"] = entry_date.date().isoformat()
                    row["Month"] = utils.to_month_string(entry_date.date())
                database.update_row(
                    "Expenses",
                    row_id,
                    row.to_dict(),
                    recompute_stock=False,
                )
            st.success("Corrections saved.")
            st.rerun()
    else:
        st.success("No validation issues found.")
