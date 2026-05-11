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
    "Year",
    "Month",
    "Customer_ID",
    "Customer_Name",
    "Destination",
    "Product",
    "HSN Code",
    "Qty",
    "Sale rate",
    "Rate",
    "GST(%12)",
    "Adjusted_Rate",
    "Adjusted_Amount",
    "Amount",
    "Freight_rate",
    "Freight",
    "Transport_Party",
    "Total_Amount",
    "Adjusted_Total_amount",
    "Freight_Paid",
    "Freight_Paid_By",
    "Amount_Received",
    "Payment_Mode",
    "Payment_Date",
    "Payment_ID",
    "Dues",
    "old_Invoice_No",
    "Invoice_No",
]

SHOW_SALES_RECORDS = False
SHOW_VALIDATION = False
GST_RATE = 12.0
GST_FACTOR = 1 + (GST_RATE / 100)
PRODUCT_HSN_MAP = {
    "fly-ash bricks": "6815",
    "paver blocks": "6810",  # Assuming a code, can be updated
    "concrete blocks": "6810",  # Assuming
}
ROUND_UP_COLUMNS = [
    "Sale rate",
    "Rate",
    "GST(%12)",
    "Adjusted_Rate",
    "Adjusted_Amount",
    "Amount",
    "Freight_rate",
    "Freight",
    "Total_Amount",
    "Adjusted_Total_amount",
]


def _pick_value(row: pd.Series, keys: list[str]) -> object:
    for key in keys:
        if key in row:
            return row.get(key)
    return None


def _sale_rate_components(sale_rate: float, freight_rate: float) -> tuple[float, float, float]:
    base_rate = sale_rate / GST_FACTOR if GST_FACTOR else 0.0
    gst_per_brick = sale_rate - base_rate
    rate_ex_freight = base_rate - freight_rate
    return rate_ex_freight, gst_per_brick, base_rate


def _sales_values_from_rates(
    qty: float,
    *,
    sale_rate: float,
    freight_rate: float,
    rate: float,
    freight: float,
) -> tuple[float, float, float, float, float]:
    sale_rate_value = utils.safe_float(sale_rate, 0.0)
    freight_rate_value = utils.safe_float(freight_rate, 0.0)
    if sale_rate_value > 0:
        rate_ex_freight, gst_per_brick, _ = _sale_rate_components(
            sale_rate_value, freight_rate_value
        )
        amount = qty * rate_ex_freight
        gst_amount = qty * gst_per_brick
        freight_total = qty * freight_rate_value
        total_amount = amount + gst_amount + freight_total
        return rate_ex_freight, gst_amount, amount, freight_total, total_amount

    rate_value = utils.safe_float(rate, 0.0)
    freight_total = utils.safe_float(freight, 0.0)
    if freight_total <= 0 and freight_rate_value > 0:
        freight_total = qty * freight_rate_value
    amount = qty * rate_value
    gst_amount = amount * GST_RATE / 100
    total_amount = amount + freight_total
    return rate_value, gst_amount, amount, freight_total, total_amount


def _customer_options(customers: pd.DataFrame) -> dict[str, str]:
    options: dict[str, str] = {}
    for _, row in customers.iterrows():
        customer_id = str(row.get("Customer_ID", "")).strip()
        name = str(row.get("Name", "")).strip()
        city = str(row.get("City", "")).strip()
        if customer_id:
            label = utils.customer_display_label(customer_id, name, city) or customer_id
            options[label] = customer_id
    return options


def _invoice_defaults() -> tuple[dict[str, str], dict[str, object], dict[str, str]]:
    invoice_secrets = st.secrets.get("invoice", {})
    signature_source = (
        invoice_secrets.get("authorized_signature_base64")
        or invoice_secrets.get("authorized_signature")
        or invoice_secrets.get("signature_base64")
    )
    signature_bytes = utils.resolve_binary_data(signature_source)
    company_defaults = {
        "name": str(invoice_secrets.get("company_name", "")).strip()
        or "IMPALA ECO BRICKS AND TILES",
        "address": str(invoice_secrets.get("company_address", "")).strip()
        or "AMIT SINGH, BELDIHA MORE, LAKARKHAWA, BANKA, State Name : Bihar, Code : 10",
        "contact": str(invoice_secrets.get("company_contact", "")).strip(),
        "gst": str(invoice_secrets.get("company_gst", "")).strip() or "10BJQPS7761G1ZU",
    }
    branding_defaults = {
        "brand_color": str(invoice_secrets.get("brand_color", "#1F4E79")).strip() or "#1F4E79",
        "logo_bytes": utils.resolve_binary_data(invoice_secrets.get("logo_base64")),
        "signature_bytes": signature_bytes,
        "font_bytes": utils.resolve_binary_data(invoice_secrets.get("font_ttf_base64")),
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
    return "Dues"


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in ("", None):
        return None
    parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _generate_invoice_no(
    sale_date: date,
    sales_id: str,
    existing_invoices: list[str],
) -> str:
    del sales_id
    return utils.generate_gst_invoice_no(sale_date, existing_invoices)


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


def _round_up_sales_values(sales_df: pd.DataFrame) -> pd.DataFrame:
    sales_df = sales_df.copy()
    for column in ROUND_UP_COLUMNS:
        if column not in sales_df.columns:
            continue
        source = sales_df[column]
        parsed = utils.to_numeric_series(source)
        has_value = source.astype(str).str.strip() != ""
        rounded = parsed.apply(lambda value: utils.round_up_2(value) if pd.notna(value) else value)
        # Arrow-backed string columns can fail on masked numeric assignment.
        # Build the updated column as object and assign it back in one shot.
        updated_column = source.astype(object).copy()
        updated_column.loc[has_value] = rounded.loc[has_value]
        sales_df[column] = updated_column
    return sales_df


def _apply_adjusted_columns(sales_df: pd.DataFrame) -> pd.DataFrame:
    sales_df = sales_df.copy()
    for column in ["Adjusted_Rate", "Adjusted_Amount", "Adjusted_Total_amount"]:
        if column not in sales_df.columns:
            sales_df[column] = ""

    empty = pd.Series("", index=sales_df.index, dtype=object)
    bricks = utils.to_numeric_series(sales_df.get("Qty", empty)).fillna(0.0)
    amount = utils.to_numeric_series(sales_df.get("Amount", empty)).fillna(0.0)
    freight = utils.to_numeric_series(sales_df.get("Freight", empty)).fillna(0.0)
    gst_source = sales_df.get("GST(%12)")
    if gst_source is None:
        gst_source = sales_df.get("Gst (%12)")
    if gst_source is None:
        gst_source = sales_df.get("GST", empty)
    gst = utils.to_numeric_series(gst_source).fillna(0.0)

    adjusted_rate = pd.Series(0.0, index=sales_df.index, dtype=float)
    valid_bricks = bricks > 0
    adjusted_rate.loc[valid_bricks] = (amount.loc[valid_bricks] + freight.loc[valid_bricks]) / bricks.loc[valid_bricks]
    adjusted_amount = adjusted_rate * bricks
    adjusted_total = adjusted_amount + gst

    sales_df["Adjusted_Rate"] = adjusted_rate.apply(utils.round_up_2)
    sales_df["Adjusted_Amount"] = adjusted_amount.apply(utils.round_up_2)
    sales_df["Adjusted_Total_amount"] = adjusted_total.apply(utils.round_up_2)
    return sales_df


def _updated_invoice_series(sales_df: pd.DataFrame) -> pd.Series:
    updated = pd.Series("", index=sales_df.index, dtype=object)
    if sales_df.empty or "Date" not in sales_df.columns:
        return updated
    month_hint = sales_df["Month"] if "Month" in sales_df.columns else None
    parsed_dates = utils.parse_date_series(sales_df["Date"], month_hint=month_hint)
    sort_df = pd.DataFrame(
        {
            "_sort_date": parsed_dates,
            "_sort_id": sales_df.get("Sales_ID", pd.Series(dtype=str)).astype(str),
        },
        index=sales_df.index,
    ).sort_values(["_sort_date", "_sort_id"], na_position="last")
    sequence_by_fy: dict[int, int] = {}
    for idx in sort_df.index:
        sort_date = sort_df.at[idx, "_sort_date"]
        if pd.isna(sort_date):
            continue
        sale_date = pd.Timestamp(sort_date).date()
        fy_start = utils.financial_year_start_year(sale_date)
        sequence_by_fy[fy_start] = sequence_by_fy.get(fy_start, 0) + 1
        updated.at[idx] = utils.format_gst_invoice_no(sale_date, sequence_by_fy[fy_start])
    return updated


def _apply_sales_log_rules(sales_df: pd.DataFrame, customers_df: pd.DataFrame) -> pd.DataFrame:
    sales_df = sales_df.copy()
    for column in SALES_COLUMNS:
        if column not in sales_df.columns:
            sales_df[column] = ""
    sales_df = _round_up_sales_values(sales_df)
    sales_df = _apply_adjusted_columns(sales_df)
    sales_df["Adjusted_Total_amount"] = utils.to_numeric_series(
        sales_df.get("Adjusted_Total_amount", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Amount_Received"] = utils.to_numeric_series(
        sales_df.get("Amount_Received", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Dues"] = utils.round_up_2(
        sales_df["Adjusted_Total_amount"] - sales_df["Amount_Received"]
    )
    customer_map = (
        customers_df.set_index("Customer_ID")
        .get("Name", pd.Series(dtype=str))
        .astype(str)
        .str.strip()
        .to_dict()
        if not customers_df.empty and "Customer_ID" in customers_df.columns
        else {}
    )
    sales_df["Customer_ID"] = sales_df["Customer_ID"].astype(str).str.strip()
    sales_df["Customer_Name"] = sales_df["Customer_ID"].map(
        lambda customer_id: customer_map.get(customer_id, "")
    )
    sales_df["Invoice_No"] = _updated_invoice_series(sales_df)
    return sales_df


def _sync_sales_log_rules(customers_df: pd.DataFrame) -> None:
    sales_df = database.read_table("Sales_Log")
    if sales_df.empty:
        return
    updated_df = _apply_sales_log_rules(sales_df, customers_df)
    current_df = utils.ensure_columns(sales_df, updated_df.columns.tolist())
    compare_columns = updated_df.columns.tolist()
    has_changes = False
    for column in compare_columns:
        current_col = current_df[column] if column in current_df.columns else pd.Series("", index=updated_df.index)
        updated_col = updated_df[column]
        if column in ROUND_UP_COLUMNS:
            current_num = pd.to_numeric(current_col, errors="coerce")
            updated_num = pd.to_numeric(updated_col, errors="coerce")
            current_cmp = current_num.apply(
                lambda value: "" if pd.isna(value) else f"{float(value):.2f}"
            )
            updated_cmp = updated_num.apply(
                lambda value: "" if pd.isna(value) else f"{float(value):.2f}"
            )
        else:
            current_cmp = current_col.fillna("").astype(str).str.strip()
            updated_cmp = updated_col.fillna("").astype(str).str.strip()
        if not current_cmp.equals(updated_cmp):
            has_changes = True
            break
    if has_changes:
        database.replace_table("Sales_Log", updated_df, recompute_stock=False)


def _payment_applied_amount(row: pd.Series) -> float:
    amount_paid = utils.safe_float(row.get("Amount_Paid", 0.0))
    status = str(row.get("Payment_Status", "")).strip().lower()
    if status == "pending":
        return 0.0
    return amount_paid


def _sale_description(row: pd.Series) -> str:
    destination = str(row.get("Destination", "")).strip()
    product = str(row.get("Product", "fly-ash bricks")).strip() or "fly-ash bricks"
    bricks = utils.safe_float(row.get("Qty", 0.0))
    amount = utils.safe_float(row.get("Amount", 0.0))
    freight = utils.safe_float(row.get("Freight", 0.0))
    adjusted_rate = utils.safe_float(row.get("Adjusted_Rate", 0.0))
    if adjusted_rate <= 0 and bricks > 0:
        adjusted_rate = (amount + freight) / bricks
    adjusted_amount = utils.safe_float(row.get("Adjusted_Amount", 0.0))
    if adjusted_amount <= 0:
        adjusted_amount = amount + freight
    gst = utils.safe_float(
        row.get("GST(%12)", row.get("Gst (%12)", row.get("GST", 0.0)))
    )
    total = utils.safe_float(
        row.get("Adjusted_Total_amount", row.get("Total_Amount", 0.0))
    )
    hsn_code = str(row.get("HSN Code", "")).strip() or "6815"
    breakdown = (
        f"{product} (HSN: {hsn_code}) | Qty {bricks:,.0f}, Rate {adjusted_rate:,.2f}, "
        f"Amount {adjusted_amount:,.2f}, GST {gst:,.2f}, Total {total:,.2f}"
    )
    if destination:
        return f"Sale to {destination} | {breakdown}"
    return f"Sale invoice | {breakdown}"


def _payment_description(row: pd.Series, invoice_map: dict[str, str] | None = None) -> str:
    invoice_map = invoice_map or {}
    mode = str(row.get("Mode", "")).strip()
    raw_invoice_ref = str(row.get("Invoice_No", "")).strip()
    if raw_invoice_ref:
        invoice_parts = [part.strip() for part in raw_invoice_ref.split(",") if part.strip()]
        mapped_parts = [invoice_map.get(part, part) for part in invoice_parts]
        invoice_ref = ", ".join(mapped_parts)
    else:
        invoice_ref = ""
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
            "Product",
            "HSN Code",
            "Qty",
            "Rate",
            "Amount",
            "Freight",
            "GST(%12)",
            "Adjusted_Rate",
            "Adjusted_Amount",
            "Total_Amount",
            "Adjusted_Total_amount",
            "old_Invoice_No",
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
    sales_df["Adjusted_Total_amount"] = utils.to_numeric_series(
        sales_df.get("Adjusted_Total_amount", pd.Series(dtype=float))
    ).fillna(0.0)
    payments_df["Amount_Paid"] = utils.to_numeric_series(
        payments_df.get("Amount_Paid", pd.Series(dtype=float))
    ).fillna(0.0)
    payments_df["Remaining_Amount"] = utils.to_numeric_series(
        payments_df.get("Remaining_Amount", pd.Series(dtype=float))
    ).fillna(0.0)

    sales_dates = utils.parse_date_series(
        sales_df.get("Date", pd.Series(dtype=str)),
        dayfirst=True,
        month_hint=sales_df["Month"] if "Month" in sales_df.columns else None,
    )
    payment_dates = utils.parse_date_series(
        payments_df.get("Date", pd.Series(dtype=str)),
        dayfirst=True,
    )
    invoice_map: dict[str, str] = {}
    for _, sale_row in sales_df.iterrows():
        original = str(sale_row.get("old_Invoice_No", "")).strip()
        updated = str(sale_row.get("Invoice_No", "")).strip()
        canonical = updated or original
        if not canonical:
            continue
        if original:
            invoice_map[original] = canonical
        invoice_map[canonical] = canonical

    sales_date_display = sales_df.get("Date", pd.Series(dtype=str)).astype(str).replace("NaT", "")
    payment_date_display = payments_df.get("Date", pd.Series(dtype=str)).astype(str).replace("NaT", "")

    sales_events = pd.DataFrame(
        {
            "Date": sales_dates.dt.date,
            "Date_Display": sales_date_display,
            "Type": "Sale",
            "Reference": sales_df.get("Invoice_No", pd.Series(dtype=str))
            .astype(str)
            .str.strip()
            .where(
                sales_df.get("Invoice_No", pd.Series(dtype=str)).astype(str).str.strip()
                != "",
                sales_df.get("old_Invoice_No", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .where(
                    sales_df.get("old_Invoice_No", pd.Series(dtype=str)).astype(str).str.strip()
                    != "",
                    sales_df.get("Sales_ID", pd.Series(dtype=str)).astype(str),
                ),
            ),
            "Description": sales_df.apply(_sale_description, axis=1),
            "HSN Code": sales_df.get("HSN Code", pd.Series(dtype=str)).astype(str).str.strip(),
            "Debit": sales_df["Adjusted_Total_amount"].where(
                sales_df["Adjusted_Total_amount"] > 0,
                sales_df["Total_Amount"],
            ),
            "Credit": 0.0,
            "_applied": 0.0,
        }
    )

    applied_amounts = payments_df.apply(_payment_applied_amount, axis=1)
    payment_refs = payments_df.get("Payment_ID", pd.Series(dtype=str)).astype(str)
    payment_events = pd.DataFrame(
        {
            "Date": payment_dates.dt.date,
            "Date_Display": payment_date_display,
            "Type": "Payment",
            "Reference": payment_refs,
            "Description": payments_df.apply(
                lambda payment_row: _payment_description(payment_row, invoice_map),
                axis=1,
            ),
            "HSN Code": "",
            "Debit": 0.0,
            "Credit": payments_df["Amount_Paid"],
            "_applied": applied_amounts,
        }
    )

    ledger_df = pd.concat([sales_events, payment_events], ignore_index=True)
    ledger_df["_sort_date"] = pd.to_datetime(ledger_df["Date"], errors="coerce", dayfirst=True)
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
            "Adjusted_Total_amount",
            "old_Invoice_No",
            "Invoice_No",
            "Qty",
            "Rate",
            "Adjusted_Rate",
            "Amount",
            "Adjusted_Amount",
            "Freight",
            "GST(%12)",
            "HSN Code",
            "Product",
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
    sales_df["Adjusted_Total_amount"] = utils.to_numeric_series(
        sales_df.get("Adjusted_Total_amount", pd.Series(dtype=float))
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

    invoice_map: dict[str, str] = {}
    for _, sale_row in sales_df.iterrows():
        original = str(sale_row.get("Invoice_No", "")).strip()
        updated = str(sale_row.get("Updated_Invoice_No", "")).strip()
        canonical = updated or original
        if not canonical:
            continue
        if original:
            invoice_map[original] = canonical
        invoice_map[canonical] = canonical

    events: list[dict[str, object]] = []
    for idx, row in sales_df.iterrows():
        invoice_no = str(row.get("Updated_Invoice_No", "")).strip() or str(
            row.get("Invoice_No", "")
        ).strip()
        reference = invoice_no or str(row.get("Sales_ID", "")).strip()
        description = _sale_description(row)
        events.append(
            {
                "Date": sales_dates.loc[idx],
                "Type": "Sale",
                "Reference": reference,
                "Description": description,
                "Debit": float(
                    row.get("Adjusted_Total_amount", 0.0)
                    if utils.safe_float(row.get("Adjusted_Total_amount", 0.0)) > 0
                    else row.get("Total_Amount", 0.0)
                ),
                "Credit": 0.0,
                "Applied": 0.0,
                "_order": 0,
            }
        )

    for idx, row in payments_df.iterrows():
        payment_id = str(row.get("Payment_ID", "")).strip()
        raw_invoice_ref = str(row.get("Invoice_No", "")).strip()
        if raw_invoice_ref:
            invoice_parts = [part.strip() for part in raw_invoice_ref.split(",") if part.strip()]
            mapped_parts = [invoice_map.get(part, part) for part in invoice_parts]
            invoice_ref = ", ".join(mapped_parts)
        else:
            invoice_ref = ""
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
    ledger_df["_sort_date"] = pd.to_datetime(ledger_df["Date"], errors="coerce", dayfirst=True)
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
        "signature_bytes": st.session_state.get("invoice_authorized_signature_bytes")
        or st.session_state.get("invoice_signature_bytes")
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

    _sync_sales_log_rules(customers)
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
        col1, col2 = st.columns(2)
        with col1:
            sale_date = st.date_input("Date", value=date.today())
            customer_label = st.selectbox("Customer", list(customer_labels.keys()))
            customer_id = customer_labels[customer_label]
            destination = st.text_input("Destination")
            product = st.selectbox("Product", list(PRODUCT_HSN_MAP.keys()))
            st.text(f"HSN Code: {PRODUCT_HSN_MAP.get(product, '6815')}")
            qty = st.number_input("Qty", min_value=0, step=1)
            sale_rate = st.number_input("Sale rate (per brick)", min_value=0.0, step=1.0)
        with col2:
            st.text_input("GST (%)", value=f"{GST_RATE:.0f}", disabled=True)
            freight_rate = st.number_input("Freight rate (per brick)", min_value=0.0, step=1.0)
            rate_display = 0.0
            gst_per_brick = 0.0
            if sale_rate > 0:
                rate_display, gst_per_brick, _ = _sale_rate_components(sale_rate, freight_rate)
            st.text_input(
                "Rate (excl. GST & freight)",
                value=f"{rate_display:,.2f}" if sale_rate > 0 else "",
                disabled=True,
            )
            st.text_input(
                "GST per brick",
                value=f"{gst_per_brick:,.2f}" if sale_rate > 0 else "",
                disabled=True,
            )
            transport_party = st.text_input("Transport Party")
            freight_paid = st.selectbox("Freight Paid", ["No", "Yes"], index=0)
            freight_paid_by = st.selectbox("Freight Paid By", ["Party", "Company"], index=0)
            invoice_no = st.text_input("Invoice No (optional, next GST sequence only)")

        rate, gst_amount, amount, freight, total_amount = _sales_values_from_rates(
            qty,
            sale_rate=sale_rate,
            freight_rate=freight_rate,
            rate=0.0,
            freight=0.0,
        )
        due_display = total_amount

        st.markdown("**Calculated Totals**")
        st.write(f"Amount: {amount:,.2f}")
        st.write(f"GST Amount: {gst_amount:,.2f}")
        st.write(f"Freight: {freight:,.2f}")
        st.write(f"Total Amount: {total_amount:,.2f}")
        st.write(f"{due_label} (calc): {due_display:,.2f}")

        submitted = st.form_submit_button("Save Entry")

    if submitted:
        errors = []
        if qty <= 0:
            errors.append("No of Bricks must be greater than 0.")
        if sale_rate <= 0:
            errors.append("Sale rate must be greater than 0.")
        if rate < 0:
            errors.append("Calculated rate cannot be negative. Check freight rate.")

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
            due_amount = utils.round_up_2(total_amount - amount_received)
            existing_invoices = (
                entries.get("Invoice_No", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .tolist()
            )
            next_invoice_no = _generate_invoice_no(sale_date, sales_id, existing_invoices)
            manual_invoice_no = str(invoice_no).strip().upper()
            if manual_invoice_no:
                if not utils.is_valid_invoice_identifier(manual_invoice_no):
                    errors.append(
                        "Invoice No must be <=16 chars and use only letters, numbers, '-' or '/'."
                    )
                elif manual_invoice_no != next_invoice_no:
                    errors.append(
                        f"Invoice No must follow GST sequence. Expected next invoice: {next_invoice_no}"
                    )
            invoice_no_final = manual_invoice_no or next_invoice_no
            customer_name_value = (
                customers.loc[customers["Customer_ID"] == customer_id]
                .get("Name", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .iloc[0]
                if not customers.loc[customers["Customer_ID"] == customer_id].empty
                else ""
            )
            if errors:
                for error in errors:
                    st.error(error)
            else:
                data = {
                    "Sales_ID": sales_id,
                    "Date": sale_date.isoformat(),
                    "Fiscal": fiscal_label,
                    "Year": sale_date.strftime("%Y"),
                    "Month": utils.to_month_string(sale_date),
                    "Customer_ID": customer_id,
                    "Customer_Name": customer_name_value,
                    "Destination": destination,
                    "Product": product,
                    "HSN Code": PRODUCT_HSN_MAP.get(product, "6815"),
                    "Qty": qty,
                    "Sale rate": utils.round_up_2(sale_rate),
                    "Rate": utils.round_up_2(rate),
                    "GST(%12)": utils.round_up_2(gst_amount),
                    "Adjusted_Rate": utils.round_up_2(
                        (amount + freight) / qty if qty > 0 else 0.0
                    ),
                    "Adjusted_Amount": utils.round_up_2(amount + freight),
                    "Amount": utils.round_up_2(amount),
                    "Freight_rate": utils.round_up_2(freight_rate),
                    "Freight": utils.round_up_2(freight),
                    "Transport_Party": transport_party,
                    "Total_Amount": utils.round_up_2(total_amount),
                    "Adjusted_Total_amount": utils.round_up_2(total_amount),
                    "Freight_Paid": freight_paid,
                    "Freight_Paid_By": freight_paid_by,
                    "Amount_Received": 0.0,
                    "Payment_Mode": "",
                    "Payment_Date": "",
                    "Payment_ID": "",
                    "Dues": utils.round_up_2(total_amount),
                    "old_Invoice_No": invoice_no_final,
                    "Invoice_No": invoice_no_final,
                }
                data = {key: data.get(key, "") for key in SALES_COLUMNS}
                database.insert_row("Sales_Log", data)
                _sort_sales_log()
                _sync_sales_log_rules(customers)

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
            "Qty",
            "Sale rate",
            "Rate",
            "GST(%12)",
            "Adjusted_Rate",
            "Adjusted_Amount",
            "Amount",
            "Freight_rate",
            "Freight rate",
            "Freight_Rate",
            "Freight",
            "Total_Amount",
            "Adjusted_Total_amount",
            "Amount_Received",
            "Dues",
        ]
        entries = utils.coerce_numeric_columns(entries, numeric_columns)

    if SHOW_SALES_RECORDS:
        st.subheader("Sales Records")
        if not has_entries:
            st.info("No sales records yet.")
        else:
            display_entries = entries.copy()
            if "Customer_ID" in display_entries.columns:
                customer_label_map = {}
                for _, row in customers.iterrows():
                    customer_id = str(row.get("Customer_ID", "")).strip()
                    if not customer_id:
                        continue
                    label = utils.customer_display_label(
                        customer_id,
                        row.get("Name", ""),
                        row.get("City", ""),
                    )
                    if label:
                        customer_label_map[customer_id] = label
                display_entries["Customer_ID"] = display_entries["Customer_ID"].astype(str).str.strip()
                display_entries["Customer_ID"] = display_entries["Customer_ID"].map(
                    lambda value: customer_label_map.get(value, value)
                )
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
            invoice_no = str(
                row.get("Updated_Invoice_No", row.get("Invoice_No", ""))
            ).strip() or str(row.get("Invoice_No", "")).strip()
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
                        authorized_signature_bytes = None
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
                                "Authorized Signature (PNG/JPG)",
                                type=["png", "jpg", "jpeg"],
                                key="invoice_authorized_signature",
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
                                st.session_state["invoice_authorized_signature_bytes"] = (
                                    signature_file.getvalue()
                                )
                                # Backward compatibility with older key naming.
                                st.session_state["invoice_signature_bytes"] = signature_file.getvalue()
                            st.session_state["invoice_brand_color"] = brand_color
                            st.session_state["invoice_watermark_text"] = watermark_text
                            st.session_state["invoice_terms"] = terms
                            logo_bytes = st.session_state.get("invoice_logo_bytes")
                            authorized_signature_bytes = st.session_state.get(
                                "invoice_authorized_signature_bytes"
                            ) or st.session_state.get("invoice_signature_bytes")
                        else:
                            brand_color = branding_defaults["brand_color"]
                            terms = branding_defaults["terms"]
                            watermark_text = branding_defaults["watermark_text"]
                            logo_bytes = branding_defaults["logo_bytes"]
                            authorized_signature_bytes = branding_defaults["signature_bytes"]
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
                                    "authorized_signature": (
                                        "set" if authorized_signature_bytes else "not set"
                                    ),
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

                    selected_row_pdf = selected_row.copy()
                    invoice_display_no = str(
                        selected_row.get("Updated_Invoice_No", "")
                    ).strip() or str(selected_row.get("Invoice_No", "")).strip()
                    if invoice_display_no:
                        selected_row_pdf["Invoice_No"] = invoice_display_no
                    pdf_bytes = utils.generate_invoice_pdf(
                        selected_row_pdf,
                        customer_row,
                        {
                            "name": company_name,
                            "address": company_address,
                            "contact": company_contact,
                            "gst": company_gst,
                        },
                        {
                            "logo_bytes": logo_bytes,
                            "signature_bytes": authorized_signature_bytes,
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
                        "Date_Display",
                        "Type",
                        "Reference",
                        "Description",
                        "Debit",
                        "Credit",
                        "Running_Balance",
                    ]
                ].rename(columns={"Date_Display": "Date", "Running_Balance": "Running Balance"})
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
                actual_start = ledger_filtered["Date"].dropna().min()
                actual_end = ledger_filtered["Date"].dropna().max()
                if pd.isna(actual_start) or pd.isna(actual_end):
                    actual_start = start_date
                    actual_end = end_date
                period_label = f"{actual_start:%d-%b-%Y} to {actual_end:%d-%b-%Y}"
                pdf_rows = ledger_filtered[
                    [
                        "Date_Display",
                        "Type",
                        "Reference",
                        "Description",
                        "Debit",
                        "Credit",
                        "Running_Balance",
                    ]
                ].rename(columns={"Date_Display": "Date", "Running_Balance": "Running_Balance"}).copy()
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
            "Qty": {"numeric": True, "min": 0},
            "Sale rate": {"numeric": True, "min": 0},
            "Rate": {"numeric": True, "min": 0},
            "GST(%12)": {"numeric": True, "min": 0},
            "Amount": {"numeric": True, "min": 0},
            "Freight_rate": {"numeric": True, "min": 0},
            "Freight": {"numeric": True, "min": 0},
            "Total_Amount": {"numeric": True, "min": 0},
            "Amount_Received": {"numeric": True, "min": 0},
        }
        if "Dues" in entries.columns:
            rules["Dues"] = {"numeric": True}
        mask, errors = utils.build_validation_mask(entries, rules)
        bricks = pd.to_numeric(entries.get("Qty", pd.Series(dtype=float)), errors="coerce")
        rate_val = pd.to_numeric(entries.get("Rate", pd.Series(dtype=float)), errors="coerce")
        sale_rate_series = pd.Series(dtype=float)
        for key in ["Sale_rate", "Sale rate", "Sale_Rate"]:
            if key in entries.columns:
                sale_rate_series = pd.to_numeric(entries.get(key, pd.Series(dtype=float)), errors="coerce")
                break
        if sale_rate_series.empty:
            sale_rate_series = pd.Series(0.0, index=entries.index, dtype=float)
        freight_rate_series = pd.Series(dtype=float)
        for key in ["Freight_rate", "Freight rate", "Freight_Rate"]:
            if key in entries.columns:
                freight_rate_series = pd.to_numeric(entries.get(key, pd.Series(dtype=float)), errors="coerce")
                break
        if freight_rate_series.empty:
            freight_rate_series = pd.Series(0.0, index=entries.index, dtype=float)
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
        use_sale_rate = sale_rate_series.fillna(0) > 0
        sale_rate_base = sale_rate_series / GST_FACTOR
        calc_rate = sale_rate_base - freight_rate_series.fillna(0.0)
        calc_amount = bricks * calc_rate
        calc_gst = (sale_rate_series - sale_rate_base) * bricks
        calc_freight = bricks * freight_rate_series.fillna(0.0)

        fallback_amount = bricks * rate_val
        fallback_gst = fallback_amount * GST_RATE / 100
        fallback_freight = freight

        calc_amount = calc_amount.where(use_sale_rate, fallback_amount)
        calc_gst = calc_gst.where(use_sale_rate, fallback_gst)
        calc_freight = calc_freight.where(use_sale_rate, fallback_freight)
        calc_total = calc_amount + calc_gst + calc_freight
        calc_due = calc_total - received
        mask = utils.apply_invalid_mask(mask, "Amount", (amount - calc_amount).abs() > 0.01)
        for gst_col in ["GST", "Gst (%12)", "GST(%12)"]:
            if gst_col in entries.columns:
                gst_series = pd.to_numeric(entries.get(gst_col, pd.Series(dtype=float)), errors="coerce")
                mask = utils.apply_invalid_mask(
                    mask, gst_col, (gst_series - calc_gst).abs() > 0.01
                )
        if "Rate" in entries.columns:
            mask = utils.apply_invalid_mask(
                mask, "Rate", (rate_val - calc_rate.where(use_sale_rate, rate_val)).abs() > 0.01
            )
        if "Freight" in entries.columns:
            mask = utils.apply_invalid_mask(
                mask, "Freight", (freight - calc_freight).abs() > 0.01
            )
        mask = utils.apply_invalid_mask(
            mask, "Total_Amount", (total_amount - calc_total).abs() > 0.01
        )
        for due_col in ["Dues"]:
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
                existing_invoices_all = (
                    entries.get("Invoice_No", pd.Series(dtype=str))
                    .astype(str)
                    .str.strip()
                    .tolist()
                )
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
                    bricks_val = utils.safe_float(row.get("Qty", 0))
                    sale_rate_new = utils.safe_float(
                        _pick_value(row, ["Sale_rate", "Sale rate", "Sale_Rate"]), 0.0
                    )
                    freight_rate_new = utils.safe_float(
                        _pick_value(row, ["Freight_rate", "Freight rate", "Freight_Rate"]), 0.0
                    )
                    rate_new = utils.safe_float(row.get("Rate", 0))
                    freight_new = utils.safe_float(row.get("Freight", 0))
                    received_new = utils.safe_float(row.get("Amount_Received", 0))
                    rate_calc, gst_new, amount_new, freight_total, total_new = (
                        _sales_values_from_rates(
                            bricks_val,
                            sale_rate=sale_rate_new,
                            freight_rate=freight_rate_new,
                            rate=rate_new,
                            freight=freight_new,
                        )
                    )
                    due_new = utils.round_up_2(total_new - received_new)

                    data = row.to_dict()
                    data["Rate"] = utils.round_up_2(rate_calc)
                    data["Amount"] = utils.round_up_2(amount_new)
                    data["GST"] = utils.round_up_2(gst_new)
                    data["Gst (%12)"] = utils.round_up_2(gst_new)
                    data["GST(%12)"] = utils.round_up_2(gst_new)
                    data["Adjusted_Rate"] = utils.round_up_2(
                        (amount_new + freight_total) / bricks_val if bricks_val > 0 else 0.0
                    )
                    data["Adjusted_Amount"] = utils.round_up_2(amount_new + freight_total)
                    data["Freight"] = utils.round_up_2(freight_total)
                    data["Total_Amount"] = utils.round_up_2(total_new)
                    data["Adjusted_Total_amount"] = utils.round_up_2(total_new)
                    data["Dues"] = utils.round_up_2(total_new - received_new)
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
                        generated_invoice = _generate_invoice_no(
                            entry_date or date.today(),
                            row_id,
                            existing_invoices_all,
                        )
                        data["Invoice_No"] = generated_invoice
                        existing_invoices_all.append(generated_invoice)
                    data["Updated_Invoice_No"] = data.get("Invoice_No", "")

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
                _sync_sales_log_rules(customers)
                st.success("Corrections saved.")
                st.rerun()
        else:
            st.success("No validation issues found.")
