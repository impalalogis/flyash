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
    "Remaining_Amount",
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


def _format_date_value(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _sort_by_date(
    data_frame: pd.DataFrame,
    date_col: str,
    *,
    secondary_col: str | None = None,
    month_hint: pd.Series | None = None,
) -> pd.DataFrame:
    if data_frame.empty or date_col not in data_frame.columns:
        return data_frame
    sort_date = utils.parse_date_series(data_frame[date_col], month_hint=month_hint)
    sorted_frame = data_frame.assign(_sort_date=sort_date)
    sort_cols = ["_sort_date"]
    if secondary_col and secondary_col in sorted_frame.columns:
        sort_cols.append(secondary_col)
    sorted_frame = sorted_frame.sort_values(sort_cols, na_position="last")
    return sorted_frame.drop(columns=["_sort_date"])


def _reconcile_payments(
    payments_df: pd.DataFrame,
    sales_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    payments_df = utils.ensure_columns(payments_df, PAYMENT_COLUMNS).copy()
    sales_df = utils.ensure_columns(
        sales_df,
        [
            "Sales_ID",
            "Customer_ID",
            "Date",
            "Month",
            "Total_Amount",
            "Amount_Received",
            "Dues",
            "Due",
            "Payment_Mode",
            "Payment_Date",
            "Payment_ID",
        ],
    ).copy()

    payments_df["Amount_Paid"] = utils.to_numeric_series(
        payments_df.get("Amount_Paid", pd.Series(dtype=float))
    ).fillna(0.0)
    payments_df["Remaining_Amount"] = utils.to_numeric_series(
        payments_df.get("Remaining_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Total_Amount"] = utils.to_numeric_series(
        sales_df.get("Total_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Amount_Received"] = utils.to_numeric_series(
        sales_df.get("Amount_Received", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Dues"] = sales_df["Total_Amount"] - sales_df["Amount_Received"]

    payments_df["Payment_Status"] = payments_df.get(
        "Payment_Status", pd.Series(dtype=str)
    ).astype(str)
    pending_mask = payments_df["Payment_Status"].str.strip().str.lower().isin(
        ["pending", ""]
    )
    pending_payments = payments_df[pending_mask & (payments_df["Amount_Paid"] > 0)].copy()

    sales_dates = utils.parse_date_series(
        sales_df.get("Date", pd.Series(dtype=str)),
        month_hint=sales_df["Month"] if "Month" in sales_df.columns else None,
    )
    payments_dates = utils.parse_date_series(
        payments_df.get("Date", pd.Series(dtype=str))
    )
    sales_df = sales_df.assign(_sort_date=sales_dates)
    payments_df = payments_df.assign(_sort_date=payments_dates)
    pending_payments = pending_payments.assign(
        _sort_date=payments_df.loc[pending_payments.index, "_sort_date"]
    )

    customers = pending_payments["Customer_ID"].astype(str).str.strip().unique().tolist()
    for customer_id in customers:
        if not customer_id:
            continue
        sales_mask = (sales_df["Customer_ID"].astype(str).str.strip() == customer_id) & (
            sales_df["Dues"] > 0
        )
        sales_indices = (
            sales_df.loc[sales_mask]
            .sort_values(["_sort_date", "Sales_ID"], na_position="last")
            .index.tolist()
        )
        payment_mask = pending_payments["Customer_ID"].astype(str).str.strip() == customer_id
        payment_indices = (
            pending_payments.loc[payment_mask]
            .sort_values(["_sort_date", "Payment_ID"], na_position="last")
            .index.tolist()
        )

        for payment_idx in payment_indices:
            remaining = float(payments_df.at[payment_idx, "Amount_Paid"])
            payment_mode = str(payments_df.at[payment_idx, "Mode"])
            payment_date_value = _format_date_value(payments_df.at[payment_idx, "Date"])
            payment_id_value = str(payments_df.at[payment_idx, "Payment_ID"]).strip()

            for sale_idx in sales_indices:
                if remaining <= 0:
                    break
                dues = float(sales_df.at[sale_idx, "Dues"])
                if dues <= 0:
                    continue
                if remaining >= dues:
                    remaining -= dues
                    sales_df.at[sale_idx, "Amount_Received"] += dues
                    sales_df.at[sale_idx, "Dues"] = 0.0
                else:
                    sales_df.at[sale_idx, "Amount_Received"] += remaining
                    sales_df.at[sale_idx, "Dues"] = dues - remaining
                    remaining = 0.0
                sales_df.at[sale_idx, "Payment_Mode"] = payment_mode
                sales_df.at[sale_idx, "Payment_Date"] = payment_date_value
                sales_df.at[sale_idx, "Payment_ID"] = payment_id_value
                if remaining <= 0:
                    break

            if remaining <= 0:
                payments_df.at[payment_idx, "Payment_Status"] = "Settled"
                payments_df.at[payment_idx, "Remaining_Amount"] = 0.0
            else:
                payments_df.at[payment_idx, "Payment_Status"] = "Partially Settled"
                payments_df.at[payment_idx, "Remaining_Amount"] = remaining

    sales_df["Dues"] = sales_df["Total_Amount"] - sales_df["Amount_Received"]
    if "Due" in sales_df.columns:
        sales_df["Due"] = sales_df["Dues"]

    sales_df = _sort_by_date(
        sales_df.drop(columns=["_sort_date"]),
        "Date",
        secondary_col="Sales_ID",
        month_hint=sales_df["Month"] if "Month" in sales_df.columns else None,
    )
    payments_df = _sort_by_date(
        payments_df.drop(columns=["_sort_date"]),
        "Date",
        secondary_col="Payment_ID",
    )
    return payments_df, sales_df


def _merge_payment_mode(existing: object, incoming: object) -> str:
    existing_val = str(existing or "").strip()
    incoming_val = str(incoming or "").strip()
    if not existing_val:
        return incoming_val
    if not incoming_val:
        return existing_val
    if existing_val.lower() == incoming_val.lower():
        return existing_val
    return "Multiple"


def _allocate_payment(
    sales_df: pd.DataFrame,
    customer_id: str,
    amount_paid: float,
    payment_date: date,
    mode: str,
    invoice_ref: str,
) -> tuple[float, pd.DataFrame]:
    if sales_df.empty or amount_paid <= 0:
        return 0.0, sales_df
    sales_df = utils.ensure_columns(
        sales_df,
        [
            "Sales_ID",
            "Date",
            "Month",
            "Customer_ID",
            "Invoice_No",
            "Total_Amount",
            "Amount_Received",
            "Payment_Mode",
            "Payment_Date",
            "Due",
            "Dues",
        ],
    )
    sales_df = sales_df.copy()
    sales_df["Total_Amount"] = utils.to_numeric_series(
        sales_df.get("Total_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Amount_Received"] = utils.to_numeric_series(
        sales_df.get("Amount_Received", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Customer_ID"] = sales_df.get("Customer_ID", pd.Series(dtype=str)).astype(str)
    expected_due = utils.sales_expected_due_series(sales_df)
    month_hint = sales_df["Month"] if "Month" in sales_df.columns else None
    date_series = utils.parse_date_series(sales_df.get("Date", pd.Series(dtype=str)), month_hint=month_hint)

    customer_mask = sales_df["Customer_ID"].str.strip() == customer_id
    due_mask = expected_due > 0.01
    candidates = sales_df[customer_mask & due_mask].copy()
    if candidates.empty:
        return 0.0, sales_df

    candidates["_date_sort"] = date_series.loc[candidates.index]
    candidates["_date_sort"] = candidates["_date_sort"].fillna(pd.Timestamp.max)
    candidates = candidates.sort_values(["_date_sort", "Sales_ID"])

    invoice_ref = str(invoice_ref or "").strip()
    if invoice_ref:
        match_mask = (
            candidates.get("Invoice_No", pd.Series(dtype=str)).astype(str).str.strip() == invoice_ref
        ) | (candidates.get("Sales_ID", pd.Series(dtype=str)).astype(str).str.strip() == invoice_ref)
        invoice_matches = candidates[match_mask]
        remaining_candidates = candidates[~match_mask]
        ordered_indices = list(invoice_matches.index) + list(remaining_candidates.index)
    else:
        ordered_indices = list(candidates.index)

    remaining = float(amount_paid)
    applied = 0.0
    due_columns = [col for col in ["Due", "Dues"] if col in sales_df.columns]

    for idx in ordered_indices:
        if remaining <= 0:
            break
        row = sales_df.loc[idx]
        total_amount = float(row.get("Total_Amount", 0.0))
        received = float(row.get("Amount_Received", 0.0))
        due = max(total_amount - received, 0.0)
        if due <= 0:
            continue
        apply_amount = min(remaining, due)
        new_received = received + apply_amount
        remaining -= apply_amount
        applied += apply_amount

        new_mode = _merge_payment_mode(row.get("Payment_Mode", ""), mode)
        payment_iso = payment_date.isoformat()

        update_data = {
            "Amount_Received": new_received,
            "Payment_Mode": new_mode,
            "Payment_Date": payment_iso,
        }
        for due_col in due_columns:
            update_data[due_col] = utils.sales_due_for_column(
                sales_df, total_amount, new_received, column=due_col
            )
        sales_id = str(row.get("Sales_ID", "")).strip()
        if sales_id:
            database.update_row("Sales_Log", sales_id, update_data)

        sales_df.at[idx, "Amount_Received"] = new_received
        sales_df.at[idx, "Payment_Mode"] = new_mode
        sales_df.at[idx, "Payment_Date"] = payment_iso
        for due_col in due_columns:
            sales_df.at[idx, due_col] = update_data[due_col]

    return applied, sales_df


def render() -> None:
    st.header("Payments")
    st.caption(
        "Invoice No is optional. Use it when the payment matches a single sale; "
        "leave it blank for combined payments, partials, or advances."
    )

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
            invoice_no = st.text_input("Invoice No (optional)")
        with col2:
            amount_paid = st.number_input("Amount Paid", min_value=0.0, step=1.0)
            mode = st.selectbox(
                "Mode",
                ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"],
                index=0,
            )
            st.text_input("Payment Status", value="Pending", disabled=True)

        submitted = st.form_submit_button("Save Payment")

    if submitted:
        errors = []
        if amount_paid <= 0:
            errors.append("Amount Paid must be greater than 0.")
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
                "Payment_Status": "Pending",
                "Remaining_Amount": 0.0,
            }
            data = {key: data.get(key, "") for key in PAYMENT_COLUMNS}
            database.insert_row("Payments", data)

            payments_sorted = _sort_by_date(
                database.read_table("Payments"),
                "Date",
                secondary_col="Payment_ID",
            )
            database.replace_table("Payments", payments_sorted, recompute_stock=False)

            payments_after = database.read_table("Payments")
            sales_after = database.read_table("Sales_Log")
            reconciled_payments, reconciled_sales = _reconcile_payments(
                payments_after,
                sales_after,
            )
            database.replace_table("Payments", reconciled_payments, recompute_stock=False)
            database.replace_table("Sales_Log", reconciled_sales, recompute_stock=False)

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

    payments_df = utils.coerce_numeric_columns(payments_df, ["Amount_Paid", "Remaining_Amount"])
    st.dataframe(payments_df, width="stretch")

    st.subheader("Reconcile Pending Payments")
    if st.button("Run reconciliation", key="payments_reconcile"):
        payments_current = database.read_table("Payments")
        sales_current = database.read_table("Sales_Log")
        reconciled_payments, reconciled_sales = _reconcile_payments(
            payments_current,
            sales_current,
        )
        database.replace_table("Payments", reconciled_payments, recompute_stock=False)
        database.replace_table("Sales_Log", reconciled_sales, recompute_stock=False)
        st.success("Payments reconciled with sales log.")
        st.rerun()

    st.subheader("Payment Records")
    entries = database.read_table("Payments")
    if entries.empty:
        st.info("No payment records yet.")
        return
    if "Payment_ID" not in entries.columns:
        st.error("Missing Payment_ID column in Payments.")
        return

    numeric_columns = ["Amount_Paid", "Remaining_Amount"]
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
