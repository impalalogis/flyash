from __future__ import annotations

from datetime import date, datetime
import re
from typing import Iterable
import io

import pandas as pd


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_numeric_series(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def to_month_string(value: date) -> str:
    return value.strftime("%Y-%m")


def calculate_total_cost(
    qty: float,
    rate: float,
    gst: float,
    route_expenses: float,
    diesel: float,
    driver_salary: float,
    vehicle_charge: float,
    freight: float,
) -> float:
    return (qty * rate) + gst + route_expenses + diesel + driver_salary + vehicle_charge + freight


def calculate_labour_expense(no_of_labour: int, avg_daily_wage: float) -> float:
    return no_of_labour * avg_daily_wage


def calculate_sales_amount(no_of_bricks: int, rate: float) -> float:
    return no_of_bricks * rate


def calculate_total_amount(amount: float, freight: float) -> float:
    return amount + freight


def calculate_due(total_amount: float, amount_received: float) -> float:
    return total_amount - amount_received


def average_daily_wage(labour_df: pd.DataFrame) -> float:
    if labour_df.empty or "Daily_Wage" not in labour_df.columns:
        return 0.0
    wages = pd.to_numeric(labour_df["Daily_Wage"], errors="coerce")
    if wages.dropna().empty:
        return 0.0
    return float(wages.mean())


def ensure_columns(data_frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    data_frame = data_frame.copy()
    for column in columns:
        if column not in data_frame.columns:
            data_frame[column] = ""
    return data_frame[list(columns)]


def ensure_ids(data_frame: pd.DataFrame, id_column: str, prefix: str, generator) -> pd.DataFrame:
    data_frame = data_frame.copy()
    if id_column not in data_frame.columns:
        data_frame[id_column] = ""
    missing_mask = data_frame[id_column].astype(str).str.strip() == ""
    for idx in data_frame[missing_mask].index:
        data_frame.at[idx, id_column] = generator(prefix)
    return data_frame


def _name_tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name)).strip()
    tokens = [token for token in cleaned.split() if token]
    return [token.upper() for token in tokens]


def _next_increment(base: str, existing_ids: list[str]) -> int:
    max_suffix = 0
    prefix = f"{base}-"
    for value in existing_ids:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value.startswith(prefix):
            continue
        parts = value.split("-")
        if not parts:
            continue
        tail = parts[-1]
        if tail.isdigit():
            max_suffix = max(max_suffix, int(tail))
    return max_suffix + 1


def generate_named_id(prefix: str, name: str, existing_ids: list[str]) -> str:
    tokens = _name_tokens(name)
    first = tokens[0] if tokens else "NAME"
    last = tokens[-1] if len(tokens) > 1 else first
    base = f"{prefix}-{first}-{last}"
    suffix = _next_increment(base, existing_ids)
    return f"{base}-{suffix:03d}"


def _parse_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return datetime.utcnow().date()


def generate_log_id(prefix: str, entry_date: object, existing_ids: list[str]) -> str:
    parsed_date = _parse_date(entry_date)
    date_part = parsed_date.strftime("%d-%m-%y")
    time_part = datetime.utcnow().strftime("%H%M%S")
    base = f"{prefix}-{date_part}"
    suffix = _next_increment(base, existing_ids)
    return f"{base}-{time_part}-{suffix:03d}"


def build_validation_mask(
    data_frame: pd.DataFrame,
    rules: dict[str, dict],
) -> tuple[pd.DataFrame, list[str]]:
    mask = pd.DataFrame(False, index=data_frame.index, columns=data_frame.columns)
    errors: list[str] = []
    for column, rule in rules.items():
        if column not in data_frame.columns:
            continue
        series = data_frame[column]
        col_mask = pd.Series(False, index=data_frame.index)
        if rule.get("required"):
            col_mask |= series.astype(str).str.strip() == ""
        if rule.get("numeric"):
            numeric = pd.to_numeric(series, errors="coerce")
            col_mask |= numeric.isna()
            if "min" in rule:
                col_mask |= numeric < rule["min"]
        if col_mask.any():
            errors.append(f"{column}: {int(col_mask.sum())} issue(s)")
        mask[column] = mask[column] | col_mask
    return mask, errors


def apply_invalid_mask(
    mask: pd.DataFrame,
    column: str,
    invalid_series: pd.Series,
) -> pd.DataFrame:
    if column not in mask.columns:
        mask[column] = False
    mask.loc[invalid_series.index, column] = mask.loc[invalid_series.index, column] | invalid_series
    return mask


def style_invalid(data_frame: pd.DataFrame, mask: pd.DataFrame) -> pd.io.formats.style.Styler:
    mask = mask.reindex(index=data_frame.index, columns=data_frame.columns, fill_value=False)

    def _style_row(row: pd.Series) -> list[str]:
        return [
            "background-color: #ffcccc" if mask.loc[row.name, column] else ""
            for column in data_frame.columns
        ]

    return data_frame.style.apply(_style_row, axis=1)


def generate_invoice_pdf(
    sale_row: pd.Series,
    customer_row: pd.Series,
    company_info: dict[str, str],
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    company_name = company_info.get("name", "Fly-Ash Brick Unit")
    company_address = company_info.get("address", "")
    company_contact = company_info.get("contact", "")
    company_gst = company_info.get("gst", "")

    invoice_no = str(sale_row.get("Invoice_No", "")).strip() or str(
        sale_row.get("Sales_ID", "")
    ).strip()
    invoice_date = str(sale_row.get("Date", "")).strip()

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, height - 20 * mm, company_name)
    pdf.setFont("Helvetica", 9)
    y = height - 26 * mm
    if company_address:
        pdf.drawString(20 * mm, y, company_address)
        y -= 4 * mm
    if company_contact:
        pdf.drawString(20 * mm, y, f"Contact: {company_contact}")
        y -= 4 * mm
    if company_gst:
        pdf.drawString(20 * mm, y, f"GST: {company_gst}")
        y -= 4 * mm

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(20 * mm, height - 45 * mm, "Invoice")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, height - 52 * mm, f"Invoice No: {invoice_no}")
    pdf.drawString(20 * mm, height - 57 * mm, f"Date: {invoice_date}")

    customer_name = str(customer_row.get("Name", "")).strip()
    customer_address = str(customer_row.get("Address", "")).strip()
    customer_contact = str(customer_row.get("Contact", "")).strip()
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(20 * mm, height - 70 * mm, "Bill To:")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, height - 75 * mm, customer_name)
    if customer_address:
        pdf.drawString(20 * mm, height - 80 * mm, customer_address)
    if customer_contact:
        pdf.drawString(20 * mm, height - 85 * mm, f"Contact: {customer_contact}")

    table_y = height - 100 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(20 * mm, table_y, "Description")
    pdf.drawRightString(120 * mm, table_y, "Qty")
    pdf.drawRightString(150 * mm, table_y, "Rate")
    pdf.drawRightString(190 * mm, table_y, "Amount")

    qty = safe_float(sale_row.get("No_of_Bricks", 0))
    rate = safe_float(sale_row.get("Rate", 0))
    amount = safe_float(sale_row.get("Amount", qty * rate))
    freight = safe_float(sale_row.get("Freight", 0))
    total = safe_float(sale_row.get("Total_Amount", amount + freight))
    received = safe_float(sale_row.get("Amount_Received", 0))
    due = safe_float(sale_row.get("Due", total - received))

    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, table_y - 6 * mm, "Fly-ash bricks")
    pdf.drawRightString(120 * mm, table_y - 6 * mm, f"{qty:,.0f}")
    pdf.drawRightString(150 * mm, table_y - 6 * mm, f"{rate:,.2f}")
    pdf.drawRightString(190 * mm, table_y - 6 * mm, f"{amount:,.2f}")

    pdf.drawString(20 * mm, table_y - 14 * mm, "Freight")
    pdf.drawRightString(190 * mm, table_y - 14 * mm, f"{freight:,.2f}")

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(20 * mm, table_y - 24 * mm, "Total")
    pdf.drawRightString(190 * mm, table_y - 24 * mm, f"{total:,.2f}")

    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, table_y - 32 * mm, "Amount Received")
    pdf.drawRightString(190 * mm, table_y - 32 * mm, f"{received:,.2f}")

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(20 * mm, table_y - 40 * mm, "Balance Due")
    pdf.drawRightString(190 * mm, table_y - 40 * mm, f"{due:,.2f}")

    pdf.setFont("Helvetica", 8)
    pdf.drawString(20 * mm, 20 * mm, "Thank you for your business.")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer.read()


def compute_stock_log(raw_df: pd.DataFrame, production_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["Date", "Month", "Material", "Opening", "Inward", "Consumed", "Closing"]
    if raw_df.empty and production_df.empty:
        return pd.DataFrame(columns=columns)

    raw_df = ensure_columns(raw_df, ["Date", "Material", "Qty"])
    production_df = ensure_columns(
        production_df,
        ["Date", "Cement_Consumption", "FlyAsh_Consumption"],
    )

    raw_df["Date"] = pd.to_datetime(raw_df["Date"], errors="coerce").dt.date
    production_df["Date"] = pd.to_datetime(production_df["Date"], errors="coerce").dt.date
    raw_df = raw_df.dropna(subset=["Date"])
    production_df = production_df.dropna(subset=["Date"])

    raw_df["Material"] = raw_df["Material"].astype(str).str.strip()
    raw_df["Qty"] = pd.to_numeric(raw_df["Qty"], errors="coerce").fillna(0.0)

    inbound = (
        raw_df.groupby(["Date", "Material"], dropna=False)["Qty"]
        .sum()
        .reset_index()
        .rename(columns={"Qty": "Inward"})
    )

    consumption_rows = []
    consumption_map = {
        "Cement": "Cement_Consumption",
        "Fly Ash": "FlyAsh_Consumption",
    }
    for material, column in consumption_map.items():
        if column not in production_df.columns:
            continue
        temp = production_df[["Date", column]].copy()
        temp[column] = pd.to_numeric(temp[column], errors="coerce").fillna(0.0)
        temp = temp.rename(columns={column: "Consumed"})
        temp["Material"] = material
        consumption_rows.append(temp)

    if consumption_rows:
        consumption_df = pd.concat(consumption_rows, ignore_index=True)
        consumption = (
            consumption_df.groupby(["Date", "Material"], dropna=False)["Consumed"]
            .sum()
            .reset_index()
        )
    else:
        consumption = pd.DataFrame(columns=["Date", "Material", "Consumed"])

    dates = sorted(
        set(inbound["Date"].dropna().tolist())
        | set(consumption["Date"].dropna().tolist())
    )
    materials = sorted(
        set(inbound["Material"].dropna().astype(str).tolist())
        | set(consumption["Material"].dropna().astype(str).tolist())
    )
    if not dates or not materials:
        return pd.DataFrame(columns=columns)

    inbound_map = {
        (row["Date"], str(row["Material"]).strip()): float(row["Inward"])
        for _, row in inbound.iterrows()
    }
    consumption_map = {
        (row["Date"], str(row["Material"]).strip()): float(row["Consumed"])
        for _, row in consumption.iterrows()
    }

    rows = []
    for material in materials:
        opening = 0.0
        for day in dates:
            inward = inbound_map.get((day, material), 0.0)
            consumed = consumption_map.get((day, material), 0.0)
            closing = opening + inward - consumed
            rows.append(
                {
                    "Date": day.isoformat(),
                    "Month": to_month_string(day),
                    "Material": material,
                    "Opening": round(opening, 2),
                    "Inward": round(inward, 2),
                    "Consumed": round(consumed, 2),
                    "Closing": round(closing, 2),
                }
            )
            opening = closing

    return pd.DataFrame(rows, columns=columns)
