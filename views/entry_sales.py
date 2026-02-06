from __future__ import annotations

from datetime import date
import io

import pandas as pd
import streamlit as st
import re
from urllib.parse import quote

import database
import utils


SALES_COLUMNS = [
    "Sales_ID",
    "Date",
    "Fiscal",
    "Fiscal Year",
    "Fiscal_Year",
    "Year",
    "Month",
    "Customer_ID",
    "Destination",
    "No_of_Bricks",
    "Rate",
    "GST",
    "Gst (%12)",
    "Amount",
    "Freight",
    "Transport_Party",
    "Total_Amount",
    "Freight_Paid",
    "Freight_Paid_By",
    "Amount_Received",
    "Payment_Mode",
    "Payment_Date",
    "Payment_ID",
    "Due",
    "Dues",
    "Invoice_No",
]

SHOW_SALES_RECORDS = False
SHOW_VALIDATION = False


def _customer_options(customers: pd.DataFrame) -> dict[str, str]:
    options: dict[str, str] = {}
    for _, row in customers.iterrows():
        customer_id = str(row.get("Customer_ID", "")).strip()
        name = str(row.get("Name", "")).strip()
        if customer_id:
            label = f"{customer_id} - {name}" if name else customer_id
            options[label] = customer_id
    return options


def _invoice_defaults() -> tuple[dict[str, str], dict[str, object], dict[str, str]]:
    invoice_secrets = st.secrets.get("invoice", {})
    company_defaults = {
        "name": str(invoice_secrets.get("company_name", "")).strip() or "Fly-Ash Brick Unit",
        "address": str(invoice_secrets.get("company_address", "")).strip(),
        "contact": str(invoice_secrets.get("company_contact", "")).strip(),
        "gst": str(invoice_secrets.get("company_gst", "")).strip(),
    }
    branding_defaults = {
        "brand_color": str(invoice_secrets.get("brand_color", "#1F4E79")).strip() or "#1F4E79",
        "logo_bytes": utils.decode_base64_data(invoice_secrets.get("logo_base64")),
        "signature_bytes": utils.decode_base64_data(invoice_secrets.get("signature_base64")),
        "font_bytes": utils.decode_base64_data(invoice_secrets.get("font_ttf_base64")),
        "terms": str(invoice_secrets.get("terms", "")).strip(),
        "watermark_text": str(invoice_secrets.get("watermark_text", "")).strip(),
    }
    payment_defaults = {
        "upi_id": str(invoice_secrets.get("upi_id", "")).strip(),
        "bank_name": str(invoice_secrets.get("bank_name", "")).strip(),
        "account_no": str(invoice_secrets.get("account_no", "")).strip(),
        "ifsc": str(invoice_secrets.get("ifsc", "")).strip(),
        "note": str(invoice_secrets.get("payment_note", "")).strip(),
        "label": str(invoice_secrets.get("payment_label", "")).strip(),
        "qr_data": str(invoice_secrets.get("qr_data", "")).strip(),
    }
    return company_defaults, branding_defaults, payment_defaults


def _fy_label_short(value: date) -> str:
    start_year = value.year if value.month >= 4 else value.year - 1
    return f"FY{str(start_year)[-2:]}-{str(start_year + 1)[-2:]}"


def _sales_due_label(entries: pd.DataFrame) -> str:
    if "Dues" in entries.columns:
        return "Dues"
    if "Due" in entries.columns:
        return "Due"
    return "Due"


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in ("", None):
        return None
    parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _invoice_suffix(sales_id: str) -> str | None:
    digits = re.sub(r"\D", "", sales_id)
    if len(digits) >= 4:
        return digits[-4:]
    return None


def _generate_invoice_no(
    sale_date: date,
    sales_id: str,
    existing_invoices: list[str],
) -> str:
    date_part = sale_date.strftime("%d%m%Y")
    suffix = _invoice_suffix(sales_id)
    existing = {str(value).strip() for value in existing_invoices if value}
    if not suffix:
        suffix = f"{pd.Timestamp.utcnow().microsecond % 10000:04d}"
    invoice = f"INV-{date_part}-{suffix}"
    if invoice not in existing:
        return invoice
    for _ in range(20):
        suffix = f"{pd.Timestamp.utcnow().microsecond % 10000:04d}"
        invoice = f"INV-{date_part}-{suffix}"
        if invoice not in existing:
            return invoice
    return invoice


def _sort_sales_log() -> None:
    sales_df = database.read_table("Sales_Log")
    if sales_df.empty or "Date" not in sales_df.columns:
        return
    month_hint = sales_df["Month"] if "Month" in sales_df.columns else None
    sorted_df = sales_df.assign(
        _sort_date=utils.parse_date_series(sales_df["Date"], month_hint=month_hint)
    ).sort_values(["_sort_date", "Sales_ID"], na_position="last")
    sorted_df = sorted_df.drop(columns=["_sort_date"])
    database.replace_table("Sales_Log", sorted_df, recompute_stock=False)


def _payment_applied_amount(row: pd.Series) -> float:
    amount_paid = utils.safe_float(row.get("Amount_Paid", 0.0))
    remaining = utils.safe_float(row.get("Remaining_Amount", 0.0))
    status = str(row.get("Payment_Status", "")).strip().lower()
    if status == "pending":
        return 0.0
    if status == "settled":
        return amount_paid
    if status == "partially settled":
        return max(amount_paid - remaining, 0.0)
    if remaining > 0:
        return max(amount_paid - remaining, 0.0)
    return amount_paid


def _sale_description(row: pd.Series) -> str:
    destination = str(row.get("Destination", "")).strip()
    if destination:
        return f"Sale to {destination}"
    return "Sale invoice"


def _payment_description(row: pd.Series) -> str:
    mode = str(row.get("Mode", "")).strip()
    invoice_ref = str(row.get("Invoice_No", "")).strip()
    if invoice_ref and mode:
        return f"Payment ({mode}) for {invoice_ref}"
    if mode:
        return f"Payment ({mode})"
    if invoice_ref:
        return f"Payment for {invoice_ref}"
    return "Payment received"


def _build_customer_ledger(
    sales_df: pd.DataFrame,
    payments_df: pd.DataFrame,
    customer_id: str,
) -> pd.DataFrame:
    sales_df = utils.ensure_columns(
        sales_df,
        [
            "Sales_ID",
            "Date",
            "Month",
            "Customer_ID",
            "Destination",
            "Total_Amount",
            "Invoice_No",
        ],
    ).copy()
    payments_df = utils.ensure_columns(
        payments_df,
        [
            "Payment_ID",
            "Customer_ID",
            "Invoice_No",
            "Amount_Paid",
            "Date",
            "Mode",
            "Payment_Status",
            "Remaining_Amount",
        ],
    ).copy()

    sales_df = sales_df[sales_df["Customer_ID"].astype(str).str.strip() == customer_id]
    payments_df = payments_df[payments_df["Customer_ID"].astype(str).str.strip() == customer_id]

    if sales_df.empty and payments_df.empty:
        return pd.DataFrame(
            columns=[
                "Date",
                "Type",
                "Reference",
                "Description",
                "Debit",
                "Credit",
                "Running_Balance",
            ]
        )

    sales_df["Total_Amount"] = utils.to_numeric_series(
        sales_df.get("Total_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    payments_df["Amount_Paid"] = utils.to_numeric_series(
        payments_df.get("Amount_Paid", pd.Series(dtype=float))
    ).fillna(0.0)
    payments_df["Remaining_Amount"] = utils.to_numeric_series(
        payments_df.get("Remaining_Amount", pd.Series(dtype=float))
    ).fillna(0.0)

    sales_dates = utils.parse_date_series(
        sales_df.get("Date", pd.Series(dtype=str)),
        month_hint=sales_df["Month"] if "Month" in sales_df.columns else None,
    )
    payment_dates = utils.parse_date_series(
        payments_df.get("Date", pd.Series(dtype=str)),
    )

    sales_events = pd.DataFrame(
        {
            "Date": sales_dates.dt.date,
            "Type": "Sale",
            "Reference": sales_df.get("Invoice_No", pd.Series(dtype=str))
            .astype(str)
            .str.strip()
            .where(
                sales_df.get("Invoice_No", pd.Series(dtype=str)).astype(str).str.strip() != "",
                sales_df.get("Sales_ID", pd.Series(dtype=str)).astype(str),
            ),
            "Description": sales_df.apply(_sale_description, axis=1),
            "Debit": sales_df["Total_Amount"],
            "Credit": 0.0,
            "_applied": 0.0,
        }
    )

    applied_amounts = payments_df.apply(_payment_applied_amount, axis=1)
    payment_refs = payments_df.get("Payment_ID", pd.Series(dtype=str)).astype(str)
    payment_events = pd.DataFrame(
        {
            "Date": payment_dates.dt.date,
            "Type": "Payment",
            "Reference": payment_refs,
            "Description": payments_df.apply(_payment_description, axis=1),
            "Debit": 0.0,
            "Credit": payments_df["Amount_Paid"],
            "_applied": applied_amounts,
        }
    )

    ledger_df = pd.concat([sales_events, payment_events], ignore_index=True)
    ledger_df["_sort_date"] = pd.to_datetime(ledger_df["Date"], errors="coerce")
    ledger_df["_type_order"] = ledger_df["Type"].map({"Sale": 0, "Payment": 1}).fillna(2)
    ledger_df = ledger_df.sort_values(
        ["_sort_date", "_type_order", "Reference"],
        na_position="last",
    )

    running_balance = 0.0
    balances = []
    for _, row in ledger_df.iterrows():
        if row["Type"] == "Sale":
            running_balance += utils.safe_float(row["Debit"], 0.0)
        else:
            running_balance -= utils.safe_float(row["_applied"], 0.0)
        balances.append(running_balance)
    ledger_df["Running_Balance"] = balances
    return ledger_df.drop(columns=["_sort_date", "_type_order", "_applied"])


def _payment_applied_amount(row: pd.Series) -> float:
    amount_paid = utils.safe_float(row.get("Amount_Paid", 0.0))
    status = str(row.get("Payment_Status", "")).strip().lower()
    remaining_raw = row.get("Remaining_Amount", "")
    remaining_known = str(remaining_raw).strip() != ""
    remaining = utils.safe_float(remaining_raw, default=0.0) if remaining_known else None
    if status == "settled":
        return amount_paid
    if status == "partially settled" and remaining is not None:
        return max(amount_paid - remaining, 0.0)
    if status == "pending":
        return 0.0
    if remaining is not None:
        return max(amount_paid - remaining, 0.0)
    return 0.0


def _ledger_events(
    sales_df: pd.DataFrame,
    payments_df: pd.DataFrame,
    customer_id: str,
) -> pd.DataFrame:
    sales_df = utils.ensure_columns(
        sales_df,
        [
            "Sales_ID",
            "Date",
            "Month",
            "Customer_ID",
            "Destination",
            "Total_Amount",
            "Invoice_No",
        ],
    ).copy()
    payments_df = utils.ensure_columns(
        payments_df,
        [
            "Payment_ID",
            "Customer_ID",
            "Invoice_No",
            "Amount_Paid",
            "Date",
            "Mode",
            "Payment_Status",
            "Remaining_Amount",
        ],
    ).copy()

    sales_df["Customer_ID"] = sales_df["Customer_ID"].astype(str).str.strip()
    payments_df["Customer_ID"] = payments_df["Customer_ID"].astype(str).str.strip()
    sales_df = sales_df[sales_df["Customer_ID"] == customer_id]
    payments_df = payments_df[payments_df["Customer_ID"] == customer_id]

    sales_df["Total_Amount"] = utils.to_numeric_series(
        sales_df.get("Total_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    payments_df["Amount_Paid"] = utils.to_numeric_series(
        payments_df.get("Amount_Paid", pd.Series(dtype=float))
    ).fillna(0.0)

    sales_dates = utils.parse_date_series(
        sales_df.get("Date", pd.Series(dtype=str)),
        month_hint=sales_df["Month"] if "Month" in sales_df.columns else None,
    ).dt.date
    payment_dates = utils.parse_date_series(
        payments_df.get("Date", pd.Series(dtype=str))
    ).dt.date

    events: list[dict[str, object]] = []
    for idx, row in sales_df.iterrows():
        invoice_no = str(row.get("Invoice_No", "")).strip()
        reference = invoice_no or str(row.get("Sales_ID", "")).strip()
        destination = str(row.get("Destination", "")).strip()
        description = "Sale"
        if destination:
            description = f"Sale - {destination}"
        events.append(
            {
                "Date": sales_dates.loc[idx],
                "Type": "Sale",
                "Reference": reference,
                "Description": description,
                "Debit": float(row.get("Total_Amount", 0.0)),
                "Credit": 0.0,
                "Applied": 0.0,
                "_order": 0,
            }
        )

    for idx, row in payments_df.iterrows():
        payment_id = str(row.get("Payment_ID", "")).strip()
        invoice_ref = str(row.get("Invoice_No", "")).strip()
        mode = str(row.get("Mode", "")).strip()
        description_parts = ["Payment received"]
        if mode:
            description_parts.append(f"({mode})")
        if invoice_ref:
            description_parts.append(f"Invoice {invoice_ref}")
        description = " ".join(description_parts)
        applied = _payment_applied_amount(row)
        events.append(
            {
                "Date": payment_dates.loc[idx],
                "Type": "Payment",
                "Reference": payment_id,
                "Description": description,
                "Debit": 0.0,
                "Credit": float(row.get("Amount_Paid", 0.0)),
                "Applied": applied,
                "_order": 1,
            }
        )

    if not events:
        return pd.DataFrame(
            columns=[
                "Date",
                "Type",
                "Reference",
                "Description",
                "Debit",
                "Credit",
                "Running_Balance",
            ]
        )

    ledger_df = pd.DataFrame(events)
    ledger_df["_sort_date"] = pd.to_datetime(ledger_df["Date"], errors="coerce")
    ledger_df["_sort_date"] = ledger_df["_sort_date"].fillna(pd.Timestamp.max)
    ledger_df["Reference"] = ledger_df["Reference"].astype(str)
    ledger_df = ledger_df.sort_values(
        ["_sort_date", "_order", "Reference"], na_position="last"
    )

    running_balance = 0.0
    running_values = []
    for _, row in ledger_df.iterrows():
        if row["Type"] == "Sale":
            running_balance += float(row["Debit"])
        else:
            running_balance -= float(row["Applied"])
        running_values.append(running_balance)
    ledger_df["Running_Balance"] = running_values

    ledger_df = ledger_df.drop(columns=["_sort_date", "_order", "Applied"])
    return ledger_df


def _resolve_invoice_settings(
    company_defaults: dict[str, str],
    branding_defaults: dict[str, object],
    payment_defaults: dict[str, str],
) -> tuple[dict[str, str], dict[str, object]]:
    company_info = {
        "name": str(st.session_state.get("company_name", company_defaults["name"])).strip()
        or company_defaults["name"],
        "address": str(
            st.session_state.get("company_address", company_defaults["address"])
        ).strip(),
        "contact": str(
            st.session_state.get("company_contact", company_defaults["contact"])
        ).strip(),
        "gst": str(st.session_state.get("company_gst", company_defaults["gst"])).strip(),
    }
    branding = {
        "brand_color": str(
            st.session_state.get("invoice_brand_color", branding_defaults["brand_color"])
        ).strip()
        or branding_defaults["brand_color"],
        "logo_bytes": st.session_state.get("invoice_logo_bytes")
        or branding_defaults["logo_bytes"],
        "signature_bytes": st.session_state.get("invoice_signature_bytes")
        or branding_defaults["signature_bytes"],
        "font_bytes": st.session_state.get("invoice_font_bytes")
        or branding_defaults["font_bytes"],
        "terms": str(st.session_state.get("invoice_terms", branding_defaults["terms"])).strip(),
        "watermark_text": str(
            st.session_state.get(
                "invoice_watermark_text", branding_defaults["watermark_text"]
            )
        ).strip(),
    }
    payment_details = {
        "upi_id": str(st.session_state.get("invoice_upi_id", payment_defaults["upi_id"])).strip(),
        "bank_name": str(
            st.session_state.get("invoice_bank_name", payment_defaults["bank_name"])
        ).strip(),
        "account_no": str(
            st.session_state.get("invoice_account_no", payment_defaults["account_no"])
        ).strip(),
        "ifsc": str(st.session_state.get("invoice_ifsc", payment_defaults["ifsc"])).strip(),
        "note": str(
            st.session_state.get("invoice_payment_note", payment_defaults["note"])
        ).strip(),
        "label": str(
            st.session_state.get("invoice_payment_label", payment_defaults["label"])
        ).strip(),
        "qr_data": str(st.session_state.get("invoice_qr_data", payment_defaults["qr_data"])).strip(),
    }
    qr_data = payment_details.get("qr_data", "")
    if not qr_data and payment_details.get("upi_id"):
        encoded_name = quote(company_info["name"]) if company_info["name"] else "Payee"
        qr_data = f"upi://pay?pa={payment_details['upi_id']}&pn={encoded_name}"
    branding["payment_details"] = payment_details
    branding["qr_data"] = qr_data
    return company_info, branding


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

    entries = database.read_table("Sales_Log")
    due_label = _sales_due_label(entries)

    company_defaults, branding_defaults, payment_defaults = _invoice_defaults()
    has_company_defaults = any(company_defaults.values())
    has_branding_defaults = any(
        [
            branding_defaults["logo_bytes"],
            branding_defaults["signature_bytes"],
            branding_defaults["font_bytes"],
            branding_defaults["terms"],
            branding_defaults["watermark_text"],
        ]
    )
    has_payment_defaults = any(payment_defaults.values())

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
            gst_rate = st.number_input("GST (%)", min_value=0.0, step=1.0, value=12.0)
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
            invoice_no = st.text_input("Invoice No (optional)")

        amount = utils.calculate_sales_amount(no_of_bricks, rate)
        gst_amount = (amount * gst_rate / 100) if gst_rate else 0.0
        total_amount = utils.calculate_total_amount(amount, freight)
        due_display = total_amount - amount_received

        st.markdown("**Calculated Totals**")
        st.write(f"Amount: {amount:,.2f}")
        st.write(f"GST Amount: {gst_amount:,.2f}")
        st.write(f"Total Amount: {total_amount:,.2f}")
        st.write(f"{due_label} (calc): {due_display:,.2f}")

        submitted = st.form_submit_button("Save Entry")

    if submitted:
        errors = []
        if no_of_bricks <= 0:
            errors.append("No of Bricks must be greater than 0.")
        if rate <= 0:
            errors.append("Rate must be greater than 0.")
        if amount_received > total_amount:
            errors.append("Amount Received cannot exceed Total Amount.")

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
            fiscal_label = _fy_label_short(sale_date)
            due_amount = total_amount - amount_received
            existing_invoices = (
                entries.get("Invoice_No", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .tolist()
            )
            invoice_no_final = (
                str(invoice_no).strip()
                or _generate_invoice_no(sale_date, sales_id, existing_invoices)
            )
            data = {
                "Sales_ID": sales_id,
                "Date": sale_date.isoformat(),
                "Fiscal": fiscal_label,
                "Fiscal Year": fiscal_label,
                "Fiscal_Year": fiscal_label,
                "Year": sale_date.strftime("%Y"),
                "Month": utils.to_month_string(sale_date),
                "Customer_ID": customer_id,
                "Destination": destination,
                "No_of_Bricks": no_of_bricks,
                "Rate": rate,
                "GST": gst_amount,
                "Gst (%12)": gst_amount,
                "Amount": amount,
                "Freight": freight,
                "Transport_Party": transport_party,
                "Total_Amount": total_amount,
                "Freight_Paid": freight_paid,
                "Freight_Paid_By": freight_paid_by,
                "Amount_Received": amount_received,
                "Payment_Mode": payment_mode,
                "Payment_Date": payment_date.isoformat(),
                "Payment_ID": "",
                "Due": total_amount - amount_received,
                "Dues": total_amount - amount_received,
                "Invoice_No": invoice_no_final,
            }
            data = {key: data.get(key, "") for key in SALES_COLUMNS}
            database.insert_row("Sales_Log", data)
            _sort_sales_log()

            outstanding = 0.0
            customer_row = customers.loc[customers["Customer_ID"] == customer_id]
            if not customer_row.empty:
                outstanding = utils.safe_float(
                    customer_row.iloc[0].get("Outstanding_Balance", 0)
                )

            database.update_row(
                "Customers",
                customer_id,
                {"Outstanding_Balance": outstanding + due_amount},
            )
            st.success("Sales entry saved and outstanding updated.")

    entries = database.read_table("Sales_Log")
    has_entries = not entries.empty and "Sales_ID" in entries.columns
    if entries.empty:
        st.info("No sales records yet.")
    elif "Sales_ID" not in entries.columns:
        st.error("Missing Sales_ID column in Sales_Log.")

    if has_entries:
        numeric_columns = [
            "No_of_Bricks",
            "Rate",
            "GST",
            "Gst (%12)",
            "Amount",
            "Freight",
            "Total_Amount",
            "Amount_Received",
            "Due",
            "Dues",
        ]
        entries = utils.coerce_numeric_columns(entries, numeric_columns)

    if SHOW_SALES_RECORDS:
        st.subheader("Sales Records")
        if not has_entries:
            st.info("No sales records yet.")
        else:
            display_entries = entries.copy()
            display_entries["Delete"] = False
            display_entries = display_entries[["Delete"] + [col for col in entries.columns]]
            edited = st.data_editor(
                display_entries,
                width="stretch",
                disabled=[col for col in display_entries.columns if col != "Delete"],
                key="sales_entries",
            )

            if st.button("Delete selected", key="sales_delete"):
                selected = (
                    edited.loc[edited["Delete"] == True, "Sales_ID"]
                    .dropna()
                    .astype(str)
                    .tolist()
                )
                if not selected:
                    st.warning("Select at least one entry to delete.")
                else:
                    customers_df = database.read_table("Customers")
                    outstanding_map = (
                        customers_df.set_index("Customer_ID")["Outstanding_Balance"].apply(
                            utils.safe_float
                        )
                        if not customers_df.empty and "Customer_ID" in customers_df.columns
                        else pd.Series(dtype=float)
                    ).to_dict()
                    for sales_id in selected:
                        row = entries.loc[entries["Sales_ID"] == sales_id]
                        if row.empty:
                            continue
                        row = row.iloc[0]
                        customer_id = str(row.get("Customer_ID", "")).strip()
                        total_amount = utils.safe_float(row.get("Total_Amount", 0))
                        received_amount = utils.safe_float(row.get("Amount_Received", 0))
                        due = total_amount - received_amount
                        if customer_id:
                            outstanding_map[customer_id] = (
                                outstanding_map.get(customer_id, 0.0) - due
                            )
                            database.update_row(
                                "Customers",
                                customer_id,
                                {"Outstanding_Balance": outstanding_map[customer_id]},
                            )
                        database.delete_row("Sales_Log", sales_id)
                    st.success("Selected entries deleted.")
                    st.rerun()

    st.subheader("Generate Invoice (PDF)")
    if not has_entries:
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
                        override_company = st.checkbox(
                            "Override company details for this invoice",
                            value=not has_company_defaults,
                            key="invoice_override_company",
                        )
                        if override_company:
                            company_name = st.text_input(
                                "Company Name",
                                value=st.session_state.get(
                                    "company_name", company_defaults["name"]
                                ),
                            )
                            company_address = st.text_input(
                                "Address",
                                value=st.session_state.get(
                                    "company_address", company_defaults["address"]
                                ),
                            )
                            company_contact = st.text_input(
                                "Contact",
                                value=st.session_state.get(
                                    "company_contact", company_defaults["contact"]
                                ),
                            )
                            company_gst = st.text_input(
                                "GST",
                                value=st.session_state.get("company_gst", company_defaults["gst"]),
                            )
                            st.session_state["company_name"] = company_name
                            st.session_state["company_address"] = company_address
                            st.session_state["company_contact"] = company_contact
                            st.session_state["company_gst"] = company_gst
                        else:
                            company_name = company_defaults["name"]
                            company_address = company_defaults["address"]
                            company_contact = company_defaults["contact"]
                            company_gst = company_defaults["gst"]
                            st.text_input("Company Name", value=company_name, disabled=True)
                            st.text_input("Address", value=company_address, disabled=True)
                            st.text_input("Contact", value=company_contact, disabled=True)
                            st.text_input("GST", value=company_gst, disabled=True)

                    with st.expander("Branding", expanded=False):
                        logo_bytes = None
                        signature_bytes = None
                        font_bytes = branding_defaults["font_bytes"]
                        override_branding = st.checkbox(
                            "Override branding for this invoice",
                            value=not has_branding_defaults,
                            key="invoice_override_branding",
                        )
                        if override_branding:
                            logo_file = st.file_uploader(
                                "Logo (PNG/JPG)",
                                type=["png", "jpg", "jpeg"],
                                key="invoice_logo",
                            )
                            signature_file = st.file_uploader(
                                "Signature (PNG/JPG)",
                                type=["png", "jpg", "jpeg"],
                                key="invoice_signature",
                            )
                            brand_color = st.color_picker(
                                "Brand color",
                                value=st.session_state.get(
                                    "invoice_brand_color", branding_defaults["brand_color"]
                                ),
                            )
                            watermark_text = st.text_input(
                                "Watermark text",
                                value=st.session_state.get(
                                    "invoice_watermark_text",
                                    branding_defaults["watermark_text"],
                                ),
                            )
                            terms = st.text_area(
                                "Terms and notes",
                                value=st.session_state.get(
                                    "invoice_terms", branding_defaults["terms"]
                                ),
                                height=80,
                            )
                            if logo_file:
                                st.session_state["invoice_logo_bytes"] = logo_file.getvalue()
                            if signature_file:
                                st.session_state["invoice_signature_bytes"] = (
                                    signature_file.getvalue()
                                )
                            st.session_state["invoice_brand_color"] = brand_color
                            st.session_state["invoice_watermark_text"] = watermark_text
                            st.session_state["invoice_terms"] = terms
                            logo_bytes = st.session_state.get("invoice_logo_bytes")
                            signature_bytes = st.session_state.get("invoice_signature_bytes")
                        else:
                            brand_color = branding_defaults["brand_color"]
                            terms = branding_defaults["terms"]
                            watermark_text = branding_defaults["watermark_text"]
                            logo_bytes = branding_defaults["logo_bytes"]
                            signature_bytes = branding_defaults["signature_bytes"]
                            font_bytes = branding_defaults["font_bytes"]
                            st.color_picker("Brand color", value=brand_color, disabled=True)
                            st.text_input(
                                "Watermark text",
                                value=watermark_text,
                                disabled=True,
                            )
                            st.text_area("Terms and notes", value=terms, height=80, disabled=True)
                            st.write(
                                {
                                    "logo": "set" if logo_bytes else "not set",
                                    "signature": "set" if signature_bytes else "not set",
                                    "font": "set" if font_bytes else "not set",
                                }
                            )
                    with st.expander("Payment details", expanded=False):
                        override_payment = st.checkbox(
                            "Override payment details for this invoice",
                            value=not has_payment_defaults,
                            key="invoice_override_payment",
                        )
                        if override_payment:
                            upi_id = st.text_input(
                                "UPI ID",
                                value=st.session_state.get(
                                    "invoice_upi_id", payment_defaults["upi_id"]
                                ),
                            )
                            bank_name = st.text_input(
                                "Bank Name",
                                value=st.session_state.get(
                                    "invoice_bank_name", payment_defaults["bank_name"]
                                ),
                            )
                            account_no = st.text_input(
                                "Account No",
                                value=st.session_state.get(
                                    "invoice_account_no", payment_defaults["account_no"]
                                ),
                            )
                            ifsc = st.text_input(
                                "IFSC",
                                value=st.session_state.get(
                                    "invoice_ifsc", payment_defaults["ifsc"]
                                ),
                            )
                            payment_note = st.text_input(
                                "Payment Note",
                                value=st.session_state.get(
                                    "invoice_payment_note", payment_defaults["note"]
                                ),
                            )
                            payment_label = st.text_input(
                                "Payment Label",
                                value=st.session_state.get(
                                    "invoice_payment_label", payment_defaults["label"]
                                ),
                            )
                            qr_data = st.text_input(
                                "QR Data (optional)",
                                value=st.session_state.get(
                                    "invoice_qr_data", payment_defaults["qr_data"]
                                ),
                            )
                            st.session_state["invoice_upi_id"] = upi_id
                            st.session_state["invoice_bank_name"] = bank_name
                            st.session_state["invoice_account_no"] = account_no
                            st.session_state["invoice_ifsc"] = ifsc
                            st.session_state["invoice_payment_note"] = payment_note
                            st.session_state["invoice_payment_label"] = payment_label
                            st.session_state["invoice_qr_data"] = qr_data
                        else:
                            upi_id = payment_defaults["upi_id"]
                            bank_name = payment_defaults["bank_name"]
                            account_no = payment_defaults["account_no"]
                            ifsc = payment_defaults["ifsc"]
                            payment_note = payment_defaults["note"]
                            payment_label = payment_defaults["label"]
                            qr_data = payment_defaults["qr_data"]
                            st.text_input("UPI ID", value=upi_id, disabled=True)
                            st.text_input("Bank Name", value=bank_name, disabled=True)
                            st.text_input("Account No", value=account_no, disabled=True)
                            st.text_input("IFSC", value=ifsc, disabled=True)
                            st.text_input("Payment Note", value=payment_note, disabled=True)
                            st.text_input("Payment Label", value=payment_label, disabled=True)
                            st.text_input("QR Data (optional)", value=qr_data, disabled=True)

                    if not qr_data and upi_id:
                        encoded_name = quote(company_name) if company_name else "Payee"
                        qr_data = f"upi://pay?pa={upi_id}&pn={encoded_name}"

                    pdf_bytes = utils.generate_invoice_pdf(
                        selected_row,
                        customer_row,
                        {
                            "name": company_name,
                            "address": company_address,
                            "contact": company_contact,
                            "gst": company_gst,
                        },
                        {
                            "logo_bytes": logo_bytes,
                            "signature_bytes": signature_bytes,
                            "brand_color": brand_color,
                            "terms": terms,
                            "font_bytes": font_bytes,
                            "watermark_text": watermark_text,
                            "qr_data": qr_data,
                            "payment_details": {
                                "upi_id": upi_id,
                                "bank_name": bank_name,
                                "account_no": account_no,
                                "ifsc": ifsc,
                                "note": payment_note,
                                "label": payment_label,
                            },
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

    st.subheader("Customer Ledger")
    if not has_entries:
        st.info("No sales records available for ledger.")
    else:
        payments_df = database.read_table("Payments")
        ledger_customer_label = st.selectbox(
            "Customer",
            list(customer_labels.keys()),
            key="ledger_customer",
        )
        ledger_customer_id = customer_labels[ledger_customer_label]
        customer_row = customers.loc[customers["Customer_ID"] == ledger_customer_id]
        customer_row = customer_row.iloc[0] if not customer_row.empty else pd.Series(dtype=object)

        ledger_full = _build_customer_ledger(entries, payments_df, ledger_customer_id)
        if ledger_full.empty:
            st.info("No ledger entries for the selected customer.")
        else:
            min_date = ledger_full["Date"].dropna().min()
            max_date = ledger_full["Date"].dropna().max()
            if pd.isna(min_date) or pd.isna(max_date):
                min_date = date.today()
                max_date = date.today()
            date_range = st.date_input(
                "Ledger date range",
                value=(min_date, max_date),
                key="ledger_date_range",
            )
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start_date, end_date = date_range
            else:
                start_date = min_date
                end_date = max_date

            ledger_filtered = ledger_full[
                (ledger_full["Date"] >= start_date)
                & (ledger_full["Date"] <= end_date)
            ].copy()

            if ledger_filtered.empty:
                st.info(
                    "No ledger entries match the selected customer and date range. "
                    "Try expanding the date range."
                )
            else:
                total_sales = float(
                    ledger_filtered.loc[ledger_filtered["Type"] == "Sale", "Debit"].sum()
                )
                total_payments = float(
                    ledger_filtered.loc[ledger_filtered["Type"] == "Payment", "Credit"].sum()
                )
                outstanding = float(ledger_filtered["Running_Balance"].iloc[-1])

                summary_cols = st.columns(3)
                summary_cols[0].metric("Total Sales", f"{total_sales:,.2f}")
                summary_cols[1].metric("Total Payments", f"{total_payments:,.2f}")
                summary_cols[2].metric("Outstanding", f"{outstanding:,.2f}")

                ledger_view = ledger_filtered[
                    [
                        "Date",
                        "Type",
                        "Reference",
                        "Description",
                        "Debit",
                        "Credit",
                        "Running_Balance",
                    ]
                ].rename(columns={"Running_Balance": "Running Balance"})
                st.dataframe(ledger_view, width="stretch")

                file_label = re.sub(r"[^A-Za-z0-9_-]+", "_", ledger_customer_label)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    ledger_view.to_excel(writer, index=False, sheet_name="Ledger")
                    summary_df = pd.DataFrame(
                        [
                            {
                                "Customer": ledger_customer_label,
                                "Start_Date": start_date,
                                "End_Date": end_date,
                                "Total_Sales": total_sales,
                                "Total_Payments": total_payments,
                                "Outstanding": outstanding,
                            }
                        ]
                    )
                    summary_df.to_excel(writer, index=False, sheet_name="Summary")
                st.download_button(
                    "Download Ledger (Excel)",
                    data=output.getvalue(),
                    file_name=f"ledger_{file_label}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                company_info, branding = _resolve_invoice_settings(
                    company_defaults, branding_defaults, payment_defaults
                )
                period_label = f"{start_date:%d-%b-%Y} to {end_date:%d-%b-%Y}"
                pdf_rows = ledger_filtered[
                    [
                        "Date",
                        "Type",
                        "Reference",
                        "Description",
                        "Debit",
                        "Credit",
                        "Running_Balance",
                    ]
                ].rename(columns={"Running_Balance": "Running_Balance"}).copy()
                pdf_bytes = utils.generate_customer_ledger_pdf(
                    pdf_rows,
                    customer_row,
                    company_info,
                    branding,
                    title="Customer Ledger",
                    period_label=period_label,
                )
                st.download_button(
                    "Download Ledger (PDF)",
                    data=pdf_bytes,
                    file_name=f"ledger_{file_label}.pdf",
                    mime="application/pdf",
                )

    if SHOW_VALIDATION and has_entries:
        st.subheader("Validation")
        rules = {
            "Date": {"required": True},
            "Customer_ID": {"required": True},
            "No_of_Bricks": {"numeric": True, "min": 0},
            "Rate": {"numeric": True, "min": 0},
            "GST": {"numeric": True, "min": 0},
            "Gst (%12)": {"numeric": True, "min": 0},
            "Amount": {"numeric": True, "min": 0},
            "Freight": {"numeric": True, "min": 0},
            "Total_Amount": {"numeric": True, "min": 0},
            "Amount_Received": {"numeric": True, "min": 0},
        }
        if "Due" in entries.columns:
            rules["Due"] = {"numeric": True}
        if "Dues" in entries.columns:
            rules["Dues"] = {"numeric": True}
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
        calc_amount = bricks * rate_val
        calc_total = calc_amount + freight
        calc_due = calc_total - received
        mask = utils.apply_invalid_mask(mask, "Amount", (amount - calc_amount).abs() > 0.01)
        mask = utils.apply_invalid_mask(
            mask, "Total_Amount", (total_amount - calc_total).abs() > 0.01
        )
        for due_col in ["Due", "Dues"]:
            if due_col not in entries.columns:
                continue
            due_series = pd.to_numeric(entries.get(due_col, pd.Series(dtype=float)), errors="coerce")
            mask = utils.apply_invalid_mask(
                mask, due_col, (due_series - calc_due).abs() > 0.01
            )

        if mask.any().any():
            st.caption("Rows highlighted in red need correction. Calculated fields will be refreshed.")
            st.dataframe(utils.style_invalid(entries, mask), width="stretch")
            invalid_rows = entries[mask.any(axis=1)].copy()
            edited_invalid = st.data_editor(
                invalid_rows,
                width="stretch",
                disabled=["Sales_ID"],
                key="sales_invalid_editor",
            )
            if st.button("Save Corrections", key="sales_save_corrections"):
                customers_df = database.read_table("Customers")
                outstanding_map = (
                    customers_df.set_index("Customer_ID")["Outstanding_Balance"].apply(
                        utils.safe_float
                    )
                    if not customers_df.empty and "Customer_ID" in customers_df.columns
                    else pd.Series(dtype=float)
                ).to_dict()
                for _, row in edited_invalid.iterrows():
                    row = row.where(pd.notnull(row), "")
                    row_id = str(row.get("Sales_ID", "")).strip()
                    if not row_id:
                        continue
                    original = entries.loc[entries["Sales_ID"] == row_id]
                    if original.empty:
                        continue
                    original = original.iloc[0]
                    old_customer = str(original.get("Customer_ID", "")).strip()
                    old_total = utils.safe_float(original.get("Total_Amount", 0))
                    old_received = utils.safe_float(original.get("Amount_Received", 0))
                    old_due = old_total - old_received

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
                    data["Due"] = total_new - received_new
                    data["Dues"] = total_new - received_new
                    entry_date = _parse_date(row.get("Date", ""))
                    if entry_date:
                        fiscal_label = _fy_label_short(entry_date)
                        data["Year"] = entry_date.strftime("%Y")
                        data["Month"] = utils.to_month_string(entry_date)
                        data["Fiscal"] = fiscal_label
                        data["Fiscal Year"] = fiscal_label
                        data["Fiscal_Year"] = fiscal_label
                    invoice_current = str(row.get("Invoice_No", "")).strip()
                    if not invoice_current:
                        existing_invoices = (
                            entries.get("Invoice_No", pd.Series(dtype=str))
                            .astype(str)
                            .str.strip()
                            .tolist()
                        )
                        data["Invoice_No"] = _generate_invoice_no(
                            entry_date or date.today(),
                            row_id,
                            existing_invoices,
                        )

                    database.update_row("Sales_Log", row_id, data)

                    if old_customer == new_customer:
                        diff = due_new - old_due
                        if abs(diff) > 0.01 and old_customer:
                            outstanding_map[old_customer] = (
                                outstanding_map.get(old_customer, 0.0) + diff
                            )
                            database.update_row(
                                "Customers",
                                old_customer,
                                {"Outstanding_Balance": outstanding_map[old_customer]},
                            )
                    else:
                        if old_customer:
                            outstanding_map[old_customer] = (
                                outstanding_map.get(old_customer, 0.0) - old_due
                            )
                            database.update_row(
                                "Customers",
                                old_customer,
                                {"Outstanding_Balance": outstanding_map[old_customer]},
                            )
                        if new_customer:
                            outstanding_map[new_customer] = (
                                outstanding_map.get(new_customer, 0.0) + due_new
                            )
                            database.update_row(
                                "Customers",
                                new_customer,
                                {"Outstanding_Balance": outstanding_map[new_customer]},
                            )

                _sort_sales_log()
                st.success("Corrections saved.")
                st.rerun()
        else:
            st.success("No validation issues found.")
