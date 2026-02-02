from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database
import utils


PAYMENT_COLUMNS = [
    "Payment_ID",
    "Customer_ID",
    "Invoice_No",
    "Amount_Paid",
    "Date",
    "Mode",
    "Payment_Status",
]


def _customer_options(customers: pd.DataFrame) -> dict[str, str]:
    options: dict[str, str] = {}
    for _, row in customers.iterrows():
        customer_id = str(row.get("Customer_ID", "")).strip()
        name = str(row.get("Name", "")).strip()
        if customer_id:
            label = f"{customer_id} - {name}" if name else customer_id
            options[label] = customer_id
    return options


def render() -> None:
    st.header("Payments")

    customers = database.read_table("Customers")
    if customers.empty:
        st.info("Add customers in Master Data before logging payments.")
        return

    customer_labels = _customer_options(customers)
    if not customer_labels:
        st.info("Customer IDs are missing. Update Master Data.")
        return

    with st.form("payment_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            payment_date = st.date_input("Date", value=date.today())
            customer_label = st.selectbox("Customer", list(customer_labels.keys()))
            customer_id = customer_labels[customer_label]
            invoice_no = st.text_input("Invoice No")
        with col2:
            amount_paid = st.number_input("Amount Paid", min_value=0.0, step=1.0)
            mode = st.selectbox(
                "Mode",
                ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"],
                index=0,
            )
            payment_status = st.selectbox("Payment Status", ["Received", "Pending"])

        submitted = st.form_submit_button("Save Payment")

    if submitted:
        errors = []
        if amount_paid <= 0:
            errors.append("Amount Paid must be greater than 0.")
        if not invoice_no:
            errors.append("Invoice No is required.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            existing_ids = (
                database.read_table("Payments")
                .get("Payment_ID", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .tolist()
            )
            payment_id = database.generate_log_id("PAY", payment_date, existing_ids)
            data = {
                "Payment_ID": payment_id,
                "Customer_ID": customer_id,
                "Invoice_No": invoice_no,
                "Amount_Paid": amount_paid,
                "Date": payment_date.isoformat(),
                "Mode": mode,
                "Payment_Status": payment_status,
            }
            data = {key: data.get(key, "") for key in PAYMENT_COLUMNS}
            database.insert_row("Payments", data)

            outstanding = 0.0
            customer_row = customers.loc[customers["Customer_ID"] == customer_id]
            if not customer_row.empty:
                outstanding = utils.safe_float(
                    customer_row.iloc[0].get("Outstanding_Balance", 0)
                )

            database.update_row(
                "Customers",
                customer_id,
                {"Outstanding_Balance": outstanding - amount_paid},
            )

            st.success("Payment saved and outstanding updated.")

    st.subheader("Payment History")
    payments_df = database.read_table("Payments")
    if payments_df.empty:
        st.info("No payments logged yet.")
        return

    payment_customer = st.selectbox(
        "Filter by Customer",
        ["All"] + list(customer_labels.keys()),
    )
    if payment_customer != "All":
        customer_id = customer_labels[payment_customer]
        payments_df = payments_df[payments_df["Customer_ID"] == customer_id]

    payments_df = utils.coerce_numeric_columns(payments_df, ["Amount_Paid"])
    st.dataframe(payments_df, width="stretch")

    st.subheader("Payment Records")
    entries = database.read_table("Payments")
    if entries.empty:
        st.info("No payment records yet.")
        return
    if "Payment_ID" not in entries.columns:
        st.error("Missing Payment_ID column in Payments.")
        return

    numeric_columns = ["Amount_Paid"]
    entries = utils.coerce_numeric_columns(entries, numeric_columns)

    display_entries = entries.copy()
    display_entries["Delete"] = False
    display_entries = display_entries[["Delete"] + [col for col in entries.columns]]
    edited = st.data_editor(
        display_entries,
        width="stretch",
        disabled=[col for col in display_entries.columns if col != "Delete"],
        key="payments_entries",
    )

    if st.button("Delete selected", key="payments_delete"):
        selected = edited.loc[edited["Delete"] == True, "Payment_ID"].dropna().astype(str).tolist()
        if not selected:
            st.warning("Select at least one entry to delete.")
        else:
            customers_df = database.read_table("Customers")
            outstanding_map = (
                customers_df.set_index("Customer_ID")["Outstanding_Balance"].apply(utils.safe_float)
                if not customers_df.empty and "Customer_ID" in customers_df.columns
                else pd.Series(dtype=float)
            ).to_dict()
            for payment_id in selected:
                row = entries.loc[entries["Payment_ID"] == payment_id]
                if row.empty:
                    continue
                row = row.iloc[0]
                customer_id = str(row.get("Customer_ID", "")).strip()
                amount = utils.safe_float(row.get("Amount_Paid", 0))
                if customer_id:
                    outstanding_map[customer_id] = outstanding_map.get(customer_id, 0.0) + amount
                    database.update_row(
                        "Customers",
                        customer_id,
                        {"Outstanding_Balance": outstanding_map[customer_id]},
                    )
                database.delete_row("Payments", payment_id)
            st.success("Selected entries deleted.")
            st.rerun()

    st.subheader("Validation")
    rules = {
        "Date": {"required": True},
        "Customer_ID": {"required": True},
        "Invoice_No": {"required": True},
        "Amount_Paid": {"numeric": True, "min": 0},
    }
    mask, errors = utils.build_validation_mask(entries, rules)
    if mask.any().any():
        st.caption("Rows highlighted in red need correction.")
        st.dataframe(utils.style_invalid(entries, mask), width="stretch")
        invalid_rows = entries[mask.any(axis=1)].copy()
        edited_invalid = st.data_editor(
            invalid_rows,
            width="stretch",
            disabled=["Payment_ID"],
            key="payments_invalid_editor",
        )
        if st.button("Save Corrections", key="payments_save_corrections"):
            customers_df = database.read_table("Customers")
            outstanding_map = (
                customers_df.set_index("Customer_ID")["Outstanding_Balance"].apply(utils.safe_float)
                if not customers_df.empty and "Customer_ID" in customers_df.columns
                else pd.Series(dtype=float)
            ).to_dict()
            for _, row in edited_invalid.iterrows():
                row = row.where(pd.notnull(row), "")
                row_id = str(row.get("Payment_ID", "")).strip()
                if not row_id:
                    continue
                original = entries.loc[entries["Payment_ID"] == row_id]
                if original.empty:
                    continue
                original = original.iloc[0]
                old_customer = str(original.get("Customer_ID", "")).strip()
                new_customer = str(row.get("Customer_ID", "")).strip()
                old_amount = utils.safe_float(original.get("Amount_Paid", 0))
                new_amount = utils.safe_float(row.get("Amount_Paid", 0))

                database.update_row("Payments", row_id, row.to_dict())

                if old_customer == new_customer:
                    diff = old_amount - new_amount
                    if abs(diff) > 0.01 and old_customer:
                        outstanding_map[old_customer] = outstanding_map.get(old_customer, 0.0) + diff
                        database.update_row(
                            "Customers",
                            old_customer,
                            {"Outstanding_Balance": outstanding_map[old_customer]},
                        )
                else:
                    if old_customer:
                        outstanding_map[old_customer] = outstanding_map.get(old_customer, 0.0) + old_amount
                        database.update_row(
                            "Customers",
                            old_customer,
                            {"Outstanding_Balance": outstanding_map[old_customer]},
                        )
                    if new_customer:
                        outstanding_map[new_customer] = outstanding_map.get(new_customer, 0.0) - new_amount
                        database.update_row(
                            "Customers",
                            new_customer,
                            {"Outstanding_Balance": outstanding_map[new_customer]},
                        )

            st.success("Corrections saved.")
            st.rerun()
    else:
        st.success("No validation issues found.")
