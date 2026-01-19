from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database
import utils


SALES_COLUMNS = [
    "Sales_ID",
    "Date",
    "Month",
    "Customer_ID",
    "Destination",
    "No_of_Bricks",
    "Rate",
    "Amount",
    "Freight",
    "Transport_Party",
    "Total_Amount",
    "Freight_Paid",
    "Freight_Paid_By",
    "Amount_Received",
    "Payment_Mode",
    "Payment_Date",
    "Due",
    "Invoice_No",
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
    st.header("Sales Entry")

    customers = database.read_table("Customers")
    if customers.empty:
        st.info("Add customers in Master Data before logging sales.")
        return

    customer_labels = _customer_options(customers)
    if not customer_labels:
        st.info("Customer IDs are missing. Update Master Data.")
        return

    with st.form("sales_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            sale_date = st.date_input("Date", value=date.today())
            customer_label = st.selectbox("Customer", list(customer_labels.keys()))
            customer_id = customer_labels[customer_label]
            destination = st.text_input("Destination")
            no_of_bricks = st.number_input("No of Bricks", min_value=0, step=1)
            rate = st.number_input("Rate", min_value=0.0, step=1.0)
        with col2:
            freight = st.number_input("Freight", min_value=0.0, step=1.0)
            transport_party = st.text_input("Transport Party")
            freight_paid = st.selectbox("Freight Paid", ["No", "Yes"], index=0)
            freight_paid_by = st.selectbox("Freight Paid By", ["Party", "Company"], index=0)
            amount_received = st.number_input("Amount Received", min_value=0.0, step=1.0)
            payment_mode = st.selectbox(
                "Payment Mode",
                ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"],
                index=0,
            )
        with col3:
            payment_date = st.date_input("Payment Date", value=sale_date)
            invoice_no = st.text_input("Invoice No")

        amount = utils.calculate_sales_amount(no_of_bricks, rate)
        total_amount = utils.calculate_total_amount(amount, freight)
        due = utils.calculate_due(total_amount, amount_received)

        st.markdown("**Calculated Totals**")
        st.write(f"Amount: {amount:,.2f}")
        st.write(f"Total Amount: {total_amount:,.2f}")
        st.write(f"Due: {due:,.2f}")

        submitted = st.form_submit_button("Save Entry")

    if submitted:
        data = {
            "Sales_ID": database.generate_id("SAL"),
            "Date": sale_date.isoformat(),
            "Month": utils.to_month_string(sale_date),
            "Customer_ID": customer_id,
            "Destination": destination,
            "No_of_Bricks": no_of_bricks,
            "Rate": rate,
            "Amount": amount,
            "Freight": freight,
            "Transport_Party": transport_party,
            "Total_Amount": total_amount,
            "Freight_Paid": freight_paid,
            "Freight_Paid_By": freight_paid_by,
            "Amount_Received": amount_received,
            "Payment_Mode": payment_mode,
            "Payment_Date": payment_date.isoformat(),
            "Due": due,
            "Invoice_No": invoice_no,
        }
        data = {key: data.get(key, "") for key in SALES_COLUMNS}
        database.insert_row("Sales_Log", data)

        outstanding = 0.0
        customer_row = customers.loc[customers["Customer_ID"] == customer_id]
        if not customer_row.empty:
            outstanding = utils.safe_float(customer_row.iloc[0].get("Outstanding_Balance", 0))

        database.update_row(
            "Customers",
            customer_id,
            {"Outstanding_Balance": outstanding + due},
        )
        st.success("Sales entry saved and outstanding updated.")
