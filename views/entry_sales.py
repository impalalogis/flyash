from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
import re

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
        errors = []
        if no_of_bricks <= 0:
            errors.append("No of Bricks must be greater than 0.")
        if rate <= 0:
            errors.append("Rate must be greater than 0.")
        if amount_received > total_amount:
            errors.append("Amount Received cannot exceed Total Amount.")
        if not invoice_no:
            errors.append("Invoice No is required.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            existing_ids = (
                database.read_table("Sales_Log")
                .get("Sales_ID", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .tolist()
            )
            sales_id = database.generate_log_id("SAL", sale_date, existing_ids)
            data = {
                "Sales_ID": sales_id,
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
                outstanding = utils.safe_float(
                    customer_row.iloc[0].get("Outstanding_Balance", 0)
                )

            database.update_row(
                "Customers",
                customer_id,
                {"Outstanding_Balance": outstanding + due},
            )
            st.success("Sales entry saved and outstanding updated.")

    st.subheader("Sales Records")
    entries = database.read_table("Sales_Log")
    if entries.empty:
        st.info("No sales records yet.")
        return
    if "Sales_ID" not in entries.columns:
        st.error("Missing Sales_ID column in Sales_Log.")
        return

    display_entries = entries.copy()
    display_entries["Delete"] = False
    display_entries = display_entries[["Delete"] + [col for col in entries.columns]]
    edited = st.data_editor(
        display_entries,
        use_container_width=True,
        disabled=[col for col in display_entries.columns if col != "Delete"],
        key="sales_entries",
    )

    if st.button("Delete selected", key="sales_delete"):
        selected = edited.loc[edited["Delete"] == True, "Sales_ID"].dropna().astype(str).tolist()
        if not selected:
            st.warning("Select at least one entry to delete.")
        else:
            customers_df = database.read_table("Customers")
            outstanding_map = (
                customers_df.set_index("Customer_ID")["Outstanding_Balance"].apply(utils.safe_float)
                if not customers_df.empty and "Customer_ID" in customers_df.columns
                else pd.Series(dtype=float)
            ).to_dict()
            for sales_id in selected:
                row = entries.loc[entries["Sales_ID"] == sales_id]
                if row.empty:
                    continue
                row = row.iloc[0]
                customer_id = str(row.get("Customer_ID", "")).strip()
                due = utils.safe_float(row.get("Due", 0))
                if customer_id:
                    outstanding_map[customer_id] = outstanding_map.get(customer_id, 0.0) - due
                    database.update_row(
                        "Customers",
                        customer_id,
                        {"Outstanding_Balance": outstanding_map[customer_id]},
                    )
                database.delete_row("Sales_Log", sales_id)
            st.success("Selected entries deleted.")
            st.rerun()

    st.subheader("Generate Invoice (PDF)")
    if entries.empty:
        st.info("No sales records available for invoices.")
    else:
        invoice_labels = []
        for _, row in entries.iterrows():
            sales_id = str(row.get("Sales_ID", "")).strip()
            invoice_no = str(row.get("Invoice_No", "")).strip()
            customer_id = str(row.get("Customer_ID", "")).strip()
            sale_date = str(row.get("Date", "")).strip()
            label = f"{invoice_no or sales_id} | {customer_id} | {sale_date}"
            invoice_labels.append((label, sales_id))
        invoice_labels = [item for item in invoice_labels if item[1]]

        if invoice_labels:
            label = st.selectbox(
                "Select Sale",
                [item[0] for item in invoice_labels],
                key="invoice_select",
            )
            selected_id = dict(invoice_labels).get(label, "")
            selected_row = entries.loc[entries["Sales_ID"] == selected_id]
            if not selected_row.empty:
                selected_row = selected_row.iloc[0]
                customer_id = str(selected_row.get("Customer_ID", "")).strip()
                customer_row = customers.loc[customers["Customer_ID"] == customer_id]
                if customer_row.empty:
                    st.error("Customer record not found for this sale.")
                else:
                    customer_row = customer_row.iloc[0]
                    with st.expander("Company details", expanded=False):
                        company_name = st.text_input(
                            "Company Name",
                            value=st.session_state.get("company_name", "Fly-Ash Brick Unit"),
                        )
                        company_address = st.text_input(
                            "Address",
                            value=st.session_state.get("company_address", ""),
                        )
                        company_contact = st.text_input(
                            "Contact",
                            value=st.session_state.get("company_contact", ""),
                        )
                        company_gst = st.text_input(
                            "GST",
                            value=st.session_state.get("company_gst", ""),
                        )
                        st.session_state["company_name"] = company_name
                        st.session_state["company_address"] = company_address
                        st.session_state["company_contact"] = company_contact
                        st.session_state["company_gst"] = company_gst

                    pdf_bytes = utils.generate_invoice_pdf(
                        selected_row,
                        customer_row,
                        {
                            "name": st.session_state.get("company_name", ""),
                            "address": st.session_state.get("company_address", ""),
                            "contact": st.session_state.get("company_contact", ""),
                            "gst": st.session_state.get("company_gst", ""),
                        },
                    )
                    filename_base = re.sub(r"[^A-Za-z0-9_-]+", "_", label)
                    st.download_button(
                        "Download Invoice PDF",
                        data=pdf_bytes,
                        file_name=f"{filename_base}.pdf",
                        mime="application/pdf",
                    )
        else:
            st.info("Sales IDs are missing. Update or rebuild IDs.")

    st.subheader("Validation")
    rules = {
        "Date": {"required": True},
        "Customer_ID": {"required": True},
        "Invoice_No": {"required": True},
        "No_of_Bricks": {"numeric": True, "min": 0},
        "Rate": {"numeric": True, "min": 0},
        "Amount": {"numeric": True, "min": 0},
        "Freight": {"numeric": True, "min": 0},
        "Total_Amount": {"numeric": True, "min": 0},
        "Amount_Received": {"numeric": True, "min": 0},
        "Due": {"numeric": True},
    }
    mask, errors = utils.build_validation_mask(entries, rules)
    bricks = pd.to_numeric(entries.get("No_of_Bricks", pd.Series(dtype=float)), errors="coerce")
    rate_val = pd.to_numeric(entries.get("Rate", pd.Series(dtype=float)), errors="coerce")
    amount = pd.to_numeric(entries.get("Amount", pd.Series(dtype=float)), errors="coerce")
    freight = pd.to_numeric(entries.get("Freight", pd.Series(dtype=float)), errors="coerce")
    total_amount = pd.to_numeric(
        entries.get("Total_Amount", pd.Series(dtype=float)),
        errors="coerce",
    )
    received = pd.to_numeric(
        entries.get("Amount_Received", pd.Series(dtype=float)),
        errors="coerce",
    )
    due = pd.to_numeric(entries.get("Due", pd.Series(dtype=float)), errors="coerce")
    calc_amount = bricks * rate_val
    calc_total = calc_amount + freight
    calc_due = calc_total - received
    mask = utils.apply_invalid_mask(mask, "Amount", (amount - calc_amount).abs() > 0.01)
    mask = utils.apply_invalid_mask(mask, "Total_Amount", (total_amount - calc_total).abs() > 0.01)
    mask = utils.apply_invalid_mask(mask, "Due", (due - calc_due).abs() > 0.01)

    if mask.any().any():
        st.caption("Rows highlighted in red need correction. Calculated fields will be refreshed.")
        st.dataframe(utils.style_invalid(entries, mask), use_container_width=True)
        invalid_rows = entries[mask.any(axis=1)].copy()
        edited_invalid = st.data_editor(
            invalid_rows,
            use_container_width=True,
            disabled=["Sales_ID"],
            key="sales_invalid_editor",
        )
        if st.button("Save Corrections", key="sales_save_corrections"):
            customers_df = database.read_table("Customers")
            outstanding_map = (
                customers_df.set_index("Customer_ID")["Outstanding_Balance"].apply(utils.safe_float)
                if not customers_df.empty and "Customer_ID" in customers_df.columns
                else pd.Series(dtype=float)
            ).to_dict()
            for _, row in edited_invalid.iterrows():
                row_id = str(row.get("Sales_ID", "")).strip()
                if not row_id:
                    continue
                original = entries.loc[entries["Sales_ID"] == row_id]
                if original.empty:
                    continue
                original = original.iloc[0]
                old_customer = str(original.get("Customer_ID", "")).strip()
                old_due = utils.safe_float(original.get("Due", 0))

                new_customer = str(row.get("Customer_ID", "")).strip()
                bricks_val = utils.safe_float(row.get("No_of_Bricks", 0))
                rate_new = utils.safe_float(row.get("Rate", 0))
                freight_new = utils.safe_float(row.get("Freight", 0))
                received_new = utils.safe_float(row.get("Amount_Received", 0))
                amount_new = bricks_val * rate_new
                total_new = amount_new + freight_new
                due_new = total_new - received_new

                data = row.to_dict()
                data["Amount"] = amount_new
                data["Total_Amount"] = total_new
                data["Due"] = due_new

                database.update_row("Sales_Log", row_id, data)

                if old_customer == new_customer:
                    diff = due_new - old_due
                    if abs(diff) > 0.01 and old_customer:
                        outstanding_map[old_customer] = outstanding_map.get(old_customer, 0.0) + diff
                        database.update_row(
                            "Customers",
                            old_customer,
                            {"Outstanding_Balance": outstanding_map[old_customer]},
                        )
                else:
                    if old_customer:
                        outstanding_map[old_customer] = outstanding_map.get(old_customer, 0.0) - old_due
                        database.update_row(
                            "Customers",
                            old_customer,
                            {"Outstanding_Balance": outstanding_map[old_customer]},
                        )
                    if new_customer:
                        outstanding_map[new_customer] = outstanding_map.get(new_customer, 0.0) + due_new
                        database.update_row(
                            "Customers",
                            new_customer,
                            {"Outstanding_Balance": outstanding_map[new_customer]},
                        )

            st.success("Corrections saved.")
            st.rerun()
    else:
        st.success("No validation issues found.")
