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
            data = {
                "Payment_ID": database.generate_id("PAY"),
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

    st.dataframe(payments_df, use_container_width=True)
