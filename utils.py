from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import re
from typing import Iterable
import base64
import binascii
from decimal import Decimal, InvalidOperation, ROUND_UP
import io
import os
import tempfile
import textwrap
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import pandas as pd

GST_INVOICE_ALLOWED_PATTERN = re.compile(r"^[A-Za-z0-9/-]+$")


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if cleaned == "":
                return default
            numeric = float(cleaned)
        else:
            numeric = float(value)
        if pd.isna(numeric) or not math.isfinite(numeric):
            return default
        return numeric
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def round_up_2(value: object, default: float = 0.0) -> float:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    quantized = decimal_value.quantize(Decimal("0.01"), rounding=ROUND_UP)
    return float(quantized)


def financial_year_start_year(value: date) -> int:
    return value.year if value.month >= 4 else value.year - 1


def financial_year_code(value: date) -> str:
    start_year = financial_year_start_year(value) % 100
    end_year = (financial_year_start_year(value) + 1) % 100
    return f"FY{start_year:02d}{end_year:02d}"


def is_valid_invoice_identifier(value: object) -> bool:
    invoice = str(value or "").strip()
    if not invoice:
        return False
    if len(invoice) > 16:
        return False
    return bool(GST_INVOICE_ALLOWED_PATTERN.fullmatch(invoice))


def _invoice_sequence_for_fy(invoice: object, sale_date: date) -> int | None:
    invoice_value = str(invoice or "").strip().upper()
    fy_code = financial_year_code(sale_date)
    legacy_fy_code = f"FY{((financial_year_start_year(sale_date) + 1) % 100):02d}"
    patterns = [
        rf"{re.escape(fy_code)}/(\d+)",
        rf"{re.escape(legacy_fy_code)}/(\d+)",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, invoice_value)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def format_gst_invoice_no(sale_date: date, sequence: int) -> str:
    fy_code = financial_year_code(sale_date)
    digits = f"{int(sequence):04d}"
    invoice = f"{fy_code}/{digits}"
    if len(invoice) <= 16:
        return invoice
    trimmed_fy = fy_code[: max(1, 15 - len(digits))]
    return f"{trimmed_fy}/{digits}"[:16]


def generate_gst_invoice_no(sale_date: date, existing_invoices: Iterable[object]) -> str:
    existing = {
        str(value).strip().upper()
        for value in existing_invoices
        if str(value or "").strip()
    }
    max_seq = 0
    for invoice in existing:
        seq = _invoice_sequence_for_fy(invoice, sale_date)
        if seq is not None:
            max_seq = max(max_seq, seq)
    sequence = max_seq + 1
    while True:
        candidate = format_gst_invoice_no(sale_date, sequence)
        if candidate not in existing:
            return candidate
        sequence += 1


def to_numeric_series(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def coerce_numeric_columns(data_frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    data_frame = data_frame.copy()
    for column in columns:
        if column in data_frame.columns:
            data_frame[column] = to_numeric_series(data_frame[column])
    return data_frame


def _month_hint_number(value: object) -> int | None:
    if isinstance(value, datetime):
        return value.month
    if isinstance(value, date):
        return value.month
    value_str = str(value or "").strip()
    if not value_str:
        return None
    cleaned = re.sub(r"[^a-z]", "", value_str.lower())
    month_map = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    if cleaned in month_map:
        return month_map[cleaned]
    if len(cleaned) >= 3 and cleaned[:3] in month_map:
        return month_map[cleaned[:3]]
    digits = re.sub(r"\D", "", value_str)
    if digits:
        try:
            month = int(digits)
        except ValueError:
            return None
        return month if 1 <= month <= 12 else None
    return None


def parse_date_series(
    series: pd.Series,
    *,
    dayfirst: bool = True,
    month_hint: pd.Series | None = None,
) -> pd.Series:
    parsed_dayfirst = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)
    if month_hint is None:
        if parsed_dayfirst.isna().any():
            parsed_monthfirst = pd.to_datetime(
                series, errors="coerce", dayfirst=not dayfirst
            )
            parsed_dayfirst = parsed_dayfirst.fillna(parsed_monthfirst)
        return parsed_dayfirst

    parsed_monthfirst = pd.to_datetime(series, errors="coerce", dayfirst=not dayfirst)
    hint_months = pd.to_numeric(month_hint.apply(_month_hint_number), errors="coerce")
    day_month = parsed_dayfirst.dt.month
    month_month = parsed_monthfirst.dt.month
    use_monthfirst = parsed_monthfirst.notna() & (
        parsed_dayfirst.isna()
        | (
            hint_months.notna()
            & (day_month != hint_months)
            & (month_month == hint_months)
        )
    )
    parsed = parsed_dayfirst.where(~use_monthfirst, parsed_monthfirst)
    return parsed.fillna(parsed_monthfirst)


def sales_expected_due_series(data_frame: pd.DataFrame) -> pd.Series:
    total = to_numeric_series(
        data_frame.get("Total_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    received = to_numeric_series(
        data_frame.get("Amount_Received", pd.Series(dtype=float))
    ).fillna(0.0)
    return total - received


def sales_due_sign(data_frame: pd.DataFrame, column: str) -> int:
    if data_frame.empty or column not in data_frame.columns:
        return -1 if column.strip().lower() == "dues" else 1
    expected = sales_expected_due_series(data_frame)
    due = to_numeric_series(data_frame.get(column, pd.Series(dtype=float)))
    valid = due.notna()
    if not valid.any():
        return -1 if column.strip().lower() == "dues" else 1
    diff_expected = (due[valid] - expected[valid]).abs().mean()
    diff_inverted = (due[valid] + expected[valid]).abs().mean()
    return -1 if diff_inverted < diff_expected else 1


def sales_due_for_column(
    data_frame: pd.DataFrame,
    total_amount: float,
    amount_received: float,
    *,
    column: str,
) -> float:
    sign = sales_due_sign(data_frame, column) if column in data_frame.columns else 1
    return (total_amount - amount_received) * sign


def payment_week_range(entry_date: date, weeks: int) -> tuple[date, date, str]:
    weeks = max(1, int(weeks))
    week_start = entry_date - timedelta(days=entry_date.weekday())
    week_end = week_start + timedelta(days=(7 * weeks) - 1)
    label = f"{week_start:%d-%b-%Y} - {week_end:%d-%b-%Y}"
    return week_start, week_end, label


def to_month_string(value: date) -> str:
    return value.strftime("%B")


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
    return (qty * rate) + gst


def calculate_labour_expense(
    no_of_labour: int,
    avg_daily_wage: float,
    *,
    basis: str = "Day",
    no_of_bricks: int = 0,
    contract_rate: float = 0.0,
) -> float:
    basis_value = str(basis).strip().lower()
    if basis_value.startswith("contract"):
        return float(no_of_bricks) * float(contract_rate)
    return float(no_of_labour) * float(avg_daily_wage)


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


VOWELS = set("AEIOU")


def _name_tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name)).strip()
    tokens = [token for token in cleaned.split() if token]
    return [token.upper() for token in tokens]


def _alpha_tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z]+", " ", str(name)).strip()
    return [token for token in cleaned.split() if token]


def first_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split()[0]


def customer_display_label(customer_id: object, name: object, city: object) -> str:
    cust_id = str(customer_id or "").strip()
    if not cust_id:
        return ""
    first = first_name(name) or "NA"
    city_value = str(city or "").strip() or "NA"
    return f"{cust_id}-{first}-{city_value}"


def _letters_only(token: str) -> list[str]:
    return [char for char in token.upper() if char.isalpha()]


def _first_consonant_or_letter(token: str) -> str:
    letters = _letters_only(token)
    if not letters:
        return "X"
    for char in letters:
        if char not in VOWELS:
            return char
    return letters[0]


def _first_two_letters_for_single(token: str) -> tuple[str, str]:
    letters = _letters_only(token)
    consonants = [char for char in letters if char not in VOWELS]
    first = consonants[0] if consonants else (letters[0] if letters else "X")
    if len(consonants) >= 2:
        second = consonants[1]
    elif len(letters) >= 2:
        second = letters[1]
    else:
        second = "X"
    return first, second


def customer_id_prefix(name: str) -> str:
    parts = _alpha_tokens(name)
    if len(parts) >= 3:
        return (
            _first_consonant_or_letter(parts[0])
            + _first_consonant_or_letter(parts[1])
            + _first_consonant_or_letter(parts[-1])
        )
    if len(parts) == 2:
        return (
            _first_consonant_or_letter(parts[0])
            + _first_consonant_or_letter(parts[1])
            + "X"
        )
    if len(parts) == 1:
        first, second = _first_two_letters_for_single(parts[0])
        return f"{first}{second}X"
    return "XXX"


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


def _next_customer_increment(prefix: str, existing_ids: list[str]) -> int:
    prefix_upper = prefix.upper()
    pattern = re.compile(rf"^{re.escape(prefix_upper)}(\d{{3}})$")
    max_suffix = 0
    for value in existing_ids:
        if not isinstance(value, str):
            continue
        value = value.strip().upper()
        match = pattern.match(value)
        if match:
            max_suffix = max(max_suffix, int(match.group(1)))
    return max_suffix + 1


def generate_named_id(prefix: str, name: str, existing_ids: list[str]) -> str:
    tokens = _name_tokens(name)
    first = tokens[0] if tokens else "NAME"
    last = tokens[-1] if len(tokens) > 1 else first
    base = f"{prefix}-{first}-{last}"
    suffix = _next_increment(base, existing_ids)
    return f"{base}-{suffix:03d}"


def generate_customer_id(name: str, existing_ids: list[str]) -> str:
    prefix = customer_id_prefix(name).upper()
    suffix = _next_customer_increment(prefix, existing_ids)
    return f"{prefix}{suffix:03d}"


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


def decode_base64_data(value: str | None) -> bytes | None:
    if not value:
        return None
    data = str(value).strip()
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(data)
    except (ValueError, binascii.Error, TypeError):
        return None


def _extract_google_drive_file_id(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", raw):
        return raw
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if "drive.google.com" not in host and "docs.google.com" not in host:
        return None
    match = re.search(r"/d/([A-Za-z0-9_-]{20,})", parsed.path)
    if match:
        return match.group(1)
    query_id = parse_qs(parsed.query).get("id", [""])[0].strip()
    return query_id or None


def _download_binary_data(url: str, *, timeout: int = 15) -> bytes | None:
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception:
        return None
    if not payload:
        return None
    # Avoid treating HTML interstitial pages as signature/font bytes.
    if payload[:200].lstrip().lower().startswith(b"<html"):
        return None
    return payload


def resolve_binary_data(value: str | None) -> bytes | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    drive_id = _extract_google_drive_file_id(raw)
    if drive_id:
        for candidate in (
            f"https://drive.google.com/uc?export=download&id={drive_id}",
            f"https://drive.google.com/uc?id={drive_id}",
        ):
            downloaded = _download_binary_data(candidate)
            if downloaded:
                return downloaded

    if re.match(r"^https?://", raw, flags=re.IGNORECASE):
        downloaded = _download_binary_data(raw)
        if downloaded:
            return downloaded

    return decode_base64_data(raw)


def register_ttf_font(font_bytes: bytes | None, font_name: str = "InvoiceFont") -> str | None:
    if not font_bytes:
        return None
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        return None
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as tmp_file:
            tmp_file.write(font_bytes)
            tmp_path = tmp_file.name
        pdfmetrics.registerFont(TTFont(font_name, tmp_path))
        return font_name
    except Exception:
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def generate_invoice_pdf(
    sale_row: pd.Series,
    customer_row: pd.Series,
    company_info: dict[str, str],
    branding: dict[str, object] | None = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.utils import ImageReader
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
    destination = str(sale_row.get("Destination", "")).strip()

    branding = branding or {}
    brand_color = str(branding.get("brand_color", "#1F4E79")).strip() or "#1F4E79"
    logo_bytes = branding.get("logo_bytes")
    signature_bytes = branding.get("signature_bytes")
    terms = str(branding.get("terms", "")).strip()
    font_bytes = branding.get("font_bytes")
    terms_font_name = register_ttf_font(font_bytes) or "Helvetica"
    watermark_text = str(branding.get("watermark_text", "")).strip() or company_name
    payment_details = branding.get("payment_details") or {}
    qr_data = str(branding.get("qr_data", "")).strip()
    payment_label = str(payment_details.get("label", "")).strip() or "Payment Details"

    if watermark_text:
        pdf.saveState()
        pdf.setFillColor(HexColor("#EEEEEE"))
        pdf.setFont("Helvetica-Bold", 60)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(35)
        pdf.drawCentredString(0, 0, watermark_text)
        pdf.restoreState()

    if logo_bytes:
        try:
            logo_reader = ImageReader(io.BytesIO(logo_bytes))
            logo_width, logo_height = logo_reader.getSize()
            max_width = 40 * mm
            max_height = 20 * mm
            scale = min(max_width / logo_width, max_height / logo_height)
            render_width = logo_width * scale
            render_height = logo_height * scale
            pdf.drawImage(
                logo_reader,
                width - 20 * mm - render_width,
                height - 25 * mm,
                render_width,
                render_height,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    header_height = 18 * mm
    pdf.setFillColor(HexColor(brand_color))
    pdf.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(20 * mm, height - 12 * mm, company_name)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawRightString(width - 20 * mm, height - 12 * mm, "INVOICE")
    pdf.setFillColor(HexColor("#000000"))
    pdf.setFont("Helvetica", 9)
    y = height - 32 * mm
    if company_address:
        pdf.drawString(20 * mm, y, company_address)
        y -= 4 * mm
    if company_contact:
        pdf.drawString(20 * mm, y, f"Contact: {company_contact}")
        y -= 4 * mm
    if company_gst:
        pdf.drawString(20 * mm, y, f"GST: {company_gst}")
        y -= 4 * mm

    pdf.setFillColor(HexColor(brand_color))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20 * mm, height - 48 * mm, "Invoice Details")
    pdf.setFillColor(HexColor("#000000"))
    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, height - 54 * mm, f"Invoice No: {invoice_no}")
    pdf.drawString(20 * mm, height - 59 * mm, f"Date: {invoice_date}")

    customer_name = str(customer_row.get("Name", "")).strip()
    customer_address = str(customer_row.get("Address", "")).strip()
    customer_city = str(customer_row.get("City", "")).strip()
    customer_contact = str(customer_row.get("Contact", "")).strip()
    customer_gst = str(customer_row.get("GST", "")).strip()
    pdf.setFillColor(HexColor(brand_color))
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(20 * mm, height - 72 * mm, "Bill To:")
    pdf.setFillColor(HexColor("#000000"))
    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, height - 77 * mm, customer_name)


    # NEW — Destination Section
    if destination:
        pdf.setFillColor(HexColor(brand_color))
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(120 * mm, height - 72 * mm, "Destination:")
        pdf.setFillColor(HexColor("#000000"))
        pdf.setFont("Helvetica", 9)
        pdf.drawString(120 * mm, height - 77 * mm, destination)

    address_parts = []
    if customer_address:
        address_parts.append(customer_address)
    if customer_city:
        city_present_in_address = customer_city.lower() in customer_address.lower()
        if not city_present_in_address:
            address_parts.append(customer_city)
    bill_to_address = ", ".join([part for part in address_parts if part]).strip()

    address_y = height - 82 * mm
    if bill_to_address:
        wrapped_address = textwrap.wrap(f"Address: {bill_to_address}", width=70)
        for line in wrapped_address:
            pdf.drawString(20 * mm, address_y, line)
            address_y -= 4 * mm
    contact_y = address_y if bill_to_address else height - 82 * mm
    if customer_contact:
        pdf.drawString(20 * mm, contact_y, f"Contact: {customer_contact}")
        contact_y -= 4 * mm
    if customer_gst:
        pdf.drawString(20 * mm, contact_y, f"GST: {customer_gst}")

    table_y = height - 105 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(20 * mm, table_y, "Description")
    pdf.drawRightString(120 * mm, table_y, "Qty")
    pdf.drawRightString(150 * mm, table_y, "Rate")
    pdf.drawRightString(190 * mm, table_y, "Amount")

    qty = safe_float(sale_row.get("No_of_Bricks", 0))
    raw_amount = safe_float(sale_row.get("Amount", 0))
    raw_freight = safe_float(sale_row.get("Freight", 0))
    adjusted_rate = safe_float(sale_row.get("Adjusted_Rate", 0))
    if adjusted_rate <= 0 and qty > 0:
        adjusted_rate = (raw_amount + raw_freight) / qty
    adjusted_amount = safe_float(sale_row.get("Adjusted_Amount", 0))
    if adjusted_amount <= 0:
        adjusted_amount = adjusted_rate * qty
    gst_amount = safe_float(
        sale_row.get(
            "GST(%12)",
            sale_row.get("Gst (%12)", sale_row.get("GST", 0)),
        )
    )
    adjusted_total = safe_float(sale_row.get("Adjusted_Total_amount", 0))
    total = (
        adjusted_total
        if adjusted_total > 0
        else safe_float(sale_row.get("Total_Amount", adjusted_amount + gst_amount))
    )
    received = safe_float(sale_row.get("Amount_Received", 0))
    due = safe_float(sale_row.get("Dues", sale_row.get("Due", total - received)))

    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, table_y - 6 * mm, "Fly-ash bricks")
    pdf.drawRightString(120 * mm, table_y - 6 * mm, f"{qty:,.0f}")
    pdf.drawRightString(150 * mm, table_y - 6 * mm, f"{adjusted_rate:,.2f}")
    pdf.drawRightString(190 * mm, table_y - 6 * mm, f"{adjusted_amount:,.2f}")

    pdf.drawString(20 * mm, table_y - 12 * mm, "GST (12%)")
    pdf.drawRightString(190 * mm, table_y - 12 * mm, f"{gst_amount:,.2f}")

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(20 * mm, table_y - 20 * mm, "Total")
    pdf.drawRightString(190 * mm, table_y - 20 * mm, f"{total:,.2f}")

    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, table_y - 28 * mm, "Amount Received")
    pdf.drawRightString(190 * mm, table_y - 28 * mm, f"{received:,.2f}")

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(20 * mm, table_y - 36 * mm, "Balance Due")
    pdf.drawRightString(190 * mm, table_y - 36 * mm, f"{due:,.2f}")

    footer_y = 18 * mm
    reserved_bottom = footer_y + (40 * mm if (qr_data or payment_details) else 10 * mm)
    terms_start = table_y - 46 * mm
    if terms:
        pdf.setFont(terms_font_name, 7)
        text = pdf.beginText(20 * mm, terms_start)
        text.textLine("Terms:")
        for line in textwrap.wrap(terms, width=100):
            if text.getY() < reserved_bottom:
                text.textLine("...")
                break
            text.textLine(line)
        pdf.drawText(text)

    if qr_data:
        try:
            qr_size = 28 * mm
            qr_widget = QrCodeWidget(qr_data)
            bounds = qr_widget.getBounds()
            qr_width = bounds[2] - bounds[0]
            qr_height = bounds[3] - bounds[1]
            drawing = Drawing(qr_size, qr_size)
            drawing.add(
                qr_widget,
                transform=[
                    qr_size / qr_width,
                    0,
                    0,
                    qr_size / qr_height,
                    0,
                    0,
                ],
            )
            qr_x = width - 20 * mm - qr_size
            qr_y = footer_y + 10 * mm
            renderPDF.draw(drawing, pdf, qr_x, qr_y)
        except Exception:
            pass

    if payment_details:
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(20 * mm, reserved_bottom + 8 * mm, payment_label)
        pdf.setFont("Helvetica", 8)
        lines = []
        if payment_details.get("upi_id"):
            lines.append(f"UPI: {payment_details.get('upi_id')}")
        if payment_details.get("bank_name"):
            lines.append(f"Bank: {payment_details.get('bank_name')}")
        if payment_details.get("account_no"):
            lines.append(f"A/C: {payment_details.get('account_no')}")
        if payment_details.get("ifsc"):
            lines.append(f"IFSC: {payment_details.get('ifsc')}")
        if payment_details.get("note"):
            lines.append(str(payment_details.get("note")))
        y = reserved_bottom + 4 * mm
        for line in lines[:5]:
            pdf.drawString(20 * mm, y, line)
            y -= 4 * mm

    if signature_bytes:
        try:
            sig_reader = ImageReader(io.BytesIO(signature_bytes))
            sig_width, sig_height = sig_reader.getSize()
            max_width = 40 * mm
            max_height = 15 * mm
            scale = min(max_width / sig_width, max_height / sig_height)
            render_width = sig_width * scale
            render_height = sig_height * scale
            pdf.drawImage(
                sig_reader,
                width - 60 * mm,
                25 * mm,
                render_width,
                render_height,
                preserveAspectRatio=True,
                mask="auto",
            )
            pdf.setFont("Helvetica", 8)
            pdf.drawString(width - 60 * mm, 20 * mm, "Authorized Signatory")
        except Exception:
            pass

    pdf.setFont("Helvetica", 8)
    pdf.drawString(20 * mm, footer_y, "Thank you for your business.")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer.read()


def generate_customer_ledger_pdf(
    ledger_df: pd.DataFrame,
    customer_row: pd.Series,
    company_info: dict[str, str],
    branding: dict[str, object] | None = None,
    *,
    title: str = "Customer Ledger",
    period_label: str = "",
) -> bytes:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    branding = branding or {}
    brand_color = str(branding.get("brand_color", "#1F4E79")).strip() or "#1F4E79"
    logo_bytes = branding.get("logo_bytes")
    signature_bytes = branding.get("signature_bytes")
    watermark_text = str(branding.get("watermark_text", "")).strip() or company_info.get("name", "")
    payment_details = branding.get("payment_details") or {}
    qr_data = str(branding.get("qr_data", "")).strip()
    payment_label = str(payment_details.get("label", "")).strip() or "Payment Details"

    company_name = company_info.get("name", "Fly-Ash Brick Unit")
    company_address = company_info.get("address", "")
    company_contact = company_info.get("contact", "")
    company_gst = company_info.get("gst", "")

    ledger_df = ledger_df.copy() if ledger_df is not None else pd.DataFrame()
    ledger_df = ledger_df.where(pd.notnull(ledger_df), "")
    ledger_mode = {"Type", "Debit", "Credit"}.issubset(ledger_df.columns)

    if ledger_mode:
        debit_series = pd.to_numeric(
            ledger_df.get("Debit", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        credit_series = pd.to_numeric(
            ledger_df.get("Credit", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        total_amount = float(debit_series.sum())
        total_received = float(credit_series.sum())
        running_col = (
            "Running_Balance"
            if "Running_Balance" in ledger_df.columns
            else "Running Balance"
        )
        running_series = pd.to_numeric(
            ledger_df.get(running_col, pd.Series(dtype=float)), errors="coerce"
        ).dropna()
        total_due = float(running_series.iloc[-1]) if not running_series.empty else 0.0
    else:
        total_amount = float(
            pd.to_numeric(
                ledger_df.get("Total_Amount", pd.Series(dtype=float)),
                errors="coerce",
            )
            .fillna(0.0)
            .sum()
        )
        total_received = float(
            pd.to_numeric(
                ledger_df.get("Amount_Received", pd.Series(dtype=float)),
                errors="coerce",
            )
            .fillna(0.0)
            .sum()
        )
        total_due = float(
            pd.to_numeric(ledger_df.get("Due", pd.Series(dtype=float)), errors="coerce")
            .fillna(0.0)
            .sum()
        )

    def _format_date(value: object) -> str:
        if isinstance(value, date):
            return value.strftime("%d-%b-%Y")
        if isinstance(value, datetime):
            return value.date().strftime("%d-%b-%Y")
        if value in ("", None):
            return ""
        parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
        if pd.isna(parsed):
            return str(value)
        return parsed.date().strftime("%d-%b-%Y")

    def _draw_logo() -> None:
        if not logo_bytes:
            return
        try:
            logo_reader = ImageReader(io.BytesIO(logo_bytes))
            logo_width, logo_height = logo_reader.getSize()
            max_width = 40 * mm
            max_height = 20 * mm
            scale = min(max_width / logo_width, max_height / logo_height)
            render_width = logo_width * scale
            render_height = logo_height * scale
            pdf.drawImage(
                logo_reader,
                width - 20 * mm - render_width,
                height - 25 * mm,
                render_width,
                render_height,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    def _draw_qr(qr_text: str) -> None:
        if not qr_text:
            return
        try:
            qr_size = 26 * mm
            qr_widget = QrCodeWidget(qr_text)
            bounds = qr_widget.getBounds()
            qr_width = bounds[2] - bounds[0]
            qr_height = bounds[3] - bounds[1]
            drawing = Drawing(qr_size, qr_size)
            drawing.add(
                qr_widget,
                transform=[
                    qr_size / qr_width,
                    0,
                    0,
                    qr_size / qr_height,
                    0,
                    0,
                ],
            )
            qr_x = width - 20 * mm - qr_size
            qr_y = 20 * mm
            renderPDF.draw(drawing, pdf, qr_x, qr_y)
        except Exception:
            pass

    def _draw_header() -> float:
        if watermark_text:
            pdf.saveState()
            pdf.setFillColor(HexColor("#EEEEEE"))
            pdf.setFont("Helvetica-Bold", 60)
            pdf.translate(width / 2, height / 2)
            pdf.rotate(35)
            pdf.drawCentredString(0, 0, watermark_text)
            pdf.restoreState()

        header_height = 18 * mm
        pdf.setFillColor(HexColor(brand_color))
        pdf.rect(0, height - header_height, width, header_height, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#FFFFFF"))
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(20 * mm, height - 12 * mm, company_name)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawRightString(width - 20 * mm, height - 12 * mm, title)
        _draw_logo()

        pdf.setFillColor(HexColor("#000000"))
        pdf.setFont("Helvetica", 9)
        y = height - 32 * mm
        if company_address:
            pdf.drawString(20 * mm, y, company_address)
            y -= 4 * mm
        if company_contact:
            pdf.drawString(20 * mm, y, f"Contact: {company_contact}")
            y -= 4 * mm
        if company_gst:
            pdf.drawString(20 * mm, y, f"GST: {company_gst}")
            y -= 6 * mm

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(20 * mm, y, "Customer Details")
        y -= 5 * mm
        pdf.setFont("Helvetica", 9)
        customer_name = str(customer_row.get("Name", "")).strip()
        customer_id = str(customer_row.get("Customer_ID", "")).strip()
        customer_contact = str(customer_row.get("Contact", "")).strip()
        customer_address = str(customer_row.get("Address", "")).strip()
        customer_gst = str(customer_row.get("GST", "")).strip()
        if customer_name:
            pdf.drawString(20 * mm, y, f"Name: {customer_name}")
            y -= 4 * mm
        if customer_id:
            pdf.drawString(20 * mm, y, f"Customer ID: {customer_id}")
            y -= 4 * mm
        if customer_contact:
            pdf.drawString(20 * mm, y, f"Contact: {customer_contact}")
            y -= 4 * mm
        if customer_gst:
            pdf.drawString(20 * mm, y, f"GST: {customer_gst}")
            y -= 4 * mm
        if customer_address:
            address_lines = textwrap.wrap(customer_address, width=70)
            if address_lines:
                pdf.drawString(20 * mm, y, "Address:")
                y -= 4 * mm
                for line in address_lines:
                    pdf.drawString(24 * mm, y, line)
                    y -= 4 * mm

        summary_y = height - 60 * mm
        pdf.setFont("Helvetica-Bold", 9)
        amount_label = "Total Sales" if ledger_mode else "Total Amount"
        received_label = "Total Payments" if ledger_mode else "Total Received"
        pdf.drawRightString(
            width - 20 * mm,
            summary_y,
            f"{amount_label}: {total_amount:,.2f}",
        )
        pdf.drawRightString(
            width - 20 * mm,
            summary_y - 4 * mm,
            f"{received_label}: {total_received:,.2f}",
        )
        pdf.drawRightString(
            width - 20 * mm,
            summary_y - 8 * mm,
            f"Outstanding: {total_due:,.2f}",
        )
        if period_label:
            pdf.setFont("Helvetica", 8)
            pdf.drawRightString(
                width - 20 * mm,
                summary_y - 12 * mm,
                f"Period: {period_label}",
            )

        return height - 95 * mm

    def _draw_footer() -> None:
        footer_y = 15 * mm
        if payment_details:
            pdf.setFont("Helvetica-Bold", 8)
            pdf.drawString(20 * mm, footer_y + 10 * mm, payment_label)
            pdf.setFont("Helvetica", 8)
            lines = []
            if payment_details.get("upi_id"):
                lines.append(f"UPI: {payment_details.get('upi_id')}")
            if payment_details.get("bank_name"):
                lines.append(f"Bank: {payment_details.get('bank_name')}")
            if payment_details.get("account_no"):
                lines.append(f"A/C: {payment_details.get('account_no')}")
            if payment_details.get("ifsc"):
                lines.append(f"IFSC: {payment_details.get('ifsc')}")
            if payment_details.get("note"):
                lines.append(str(payment_details.get("note")))
            y = footer_y + 6 * mm
            for line in lines[:5]:
                pdf.drawString(20 * mm, y, line)
                y -= 4 * mm

        if signature_bytes:
            try:
                sig_reader = ImageReader(io.BytesIO(signature_bytes))
                sig_width, sig_height = sig_reader.getSize()
                max_width = 40 * mm
                max_height = 15 * mm
                scale = min(max_width / sig_width, max_height / sig_height)
                render_width = sig_width * scale
                render_height = sig_height * scale
                pdf.drawImage(
                    sig_reader,
                    width - 60 * mm,
                    footer_y + 2 * mm,
                    render_width,
                    render_height,
                    preserveAspectRatio=True,
                    mask="auto",
                )
                pdf.setFont("Helvetica", 8)
                pdf.drawString(width - 60 * mm, footer_y - 2 * mm, "Authorized Signatory")
            except Exception:
                pass

        _draw_qr(qr_data)

    if ledger_mode:
        columns = [
            ("Date", 16 * mm, "left"),
            ("Type", 14 * mm, "center"),
            ("Reference", 24 * mm, "left"),
            ("Description", 56 * mm, "left"),
            ("Debit", 16 * mm, "right"),
            ("Credit", 16 * mm, "right"),
            ("Balance", 18 * mm, "right"),
        ]
    else:
        columns = [
            ("Date", 18 * mm, "left"),
            ("Invoice", 32 * mm, "left"),
            ("Bricks", 18 * mm, "right"),
            ("Amount", 18 * mm, "right"),
            ("Freight", 16 * mm, "right"),
            ("Total", 20 * mm, "right"),
            ("Received", 22 * mm, "right"),
            ("Due", 18 * mm, "right"),
        ]
    table_width = sum(width for _, width, _ in columns)
    left_x = 15 * mm
    row_height = 6 * mm
    footer_reserved = 30 * mm if (payment_details or qr_data or signature_bytes) else 18 * mm
    bottom_limit = footer_reserved + 10 * mm

    def _wrap_text(
        text: str,
        max_width: float,
        font_name: str,
        font_size: int,
    ) -> list[str]:
        if not text:
            return [""]
        words = text.split()
        lines: list[str] = []
        current = ""

        def _flush() -> None:
            nonlocal current
            if current:
                lines.append(current)
                current = ""

        for word in words:
            candidate = f"{current} {word}".strip()
            if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
                continue
            _flush()
            if pdfmetrics.stringWidth(word, font_name, font_size) <= max_width:
                current = word
                continue
            part = ""
            for ch in word:
                trial = f"{part}{ch}"
                if pdfmetrics.stringWidth(trial, font_name, font_size) <= max_width:
                    part = trial
                else:
                    if part:
                        lines.append(part)
                    part = ch
            if part:
                current = part

        _flush()
        return lines if lines else [text]

    def _draw_table_header(y: float) -> float:
        pdf.setFillColor(HexColor("#F2F2F2"))
        pdf.rect(left_x, y - 4 * mm, table_width, 6 * mm, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#000000"))
        pdf.setFont("Helvetica-Bold", 8)
        x = left_x + 1 * mm
        for label, width, align in columns:
            if align == "right":
                pdf.drawRightString(x + width - 1 * mm, y, label)
            elif align == "center":
                pdf.drawCentredString(x + (width / 2), y, label)
            else:
                pdf.drawString(x, y, label)
            x += width
        return y - row_height

    y_position = _draw_header()
    y_position = _draw_table_header(y_position)

    if ledger_df.empty:
        pdf.setFont("Helvetica", 9)
        pdf.drawString(left_x, y_position - 2 * mm, "No ledger entries found.")
        _draw_footer()
    else:
        pdf.setFont("Helvetica", 8)
        font_name = "Helvetica"
        font_size = 8
        for _, row in ledger_df.iterrows():
            if ledger_mode:
                balance_col = (
                    "Running_Balance"
                    if "Running_Balance" in ledger_df.columns
                    else "Running Balance"
                )
                values = {
                    "Date": _format_date(row.get("Date", "")),
                    "Type": str(row.get("Type", "")).strip(),
                    "Reference": str(row.get("Reference", "")).strip(),
                    "Description": str(row.get("Description", "")).strip(),
                    "Debit": f"{safe_float(row.get('Debit', 0)):,.2f}",
                    "Credit": f"{safe_float(row.get('Credit', 0)):,.2f}",
                    "Balance": f"{safe_float(row.get(balance_col, 0)):,.2f}",
                }
                wrap_cols = {"Reference", "Description"}
                cell_lines: dict[str, list[str]] = {}
                max_lines = 1
                for label, width, _ in columns:
                    text = values.get(label, "")
                    if label in wrap_cols:
                        max_width = max(width - (2 * mm), 10)
                        lines = _wrap_text(text, max_width, font_name, font_size)
                    else:
                        lines = [text]
                    cell_lines[label] = lines
                    max_lines = max(max_lines, len(lines))
            else:
                values = {
                    "Date": _format_date(row.get("Date", "")),
                    "Invoice": str(row.get("Invoice", "")).strip(),
                    "Bricks": f"{safe_float(row.get('No_of_Bricks', 0)):,.0f}",
                    "Amount": f"{safe_float(row.get('Amount', 0)):,.2f}",
                    "Freight": f"{safe_float(row.get('Freight', 0)):,.2f}",
                    "Total": f"{safe_float(row.get('Total_Amount', 0)):,.2f}",
                    "Received": f"{safe_float(row.get('Amount_Received', 0)):,.2f}",
                    "Due": f"{safe_float(row.get('Due', 0)):,.2f}",
                }
                cell_lines = {label: [values.get(label, "")] for label, _, _ in columns}
                max_lines = 1

            row_height_total = row_height * max_lines
            if y_position - row_height_total < bottom_limit:
                _draw_footer()
                pdf.showPage()
                y_position = _draw_header()
                y_position = _draw_table_header(y_position)

            for line_idx in range(max_lines):
                x = left_x + 1 * mm
                y_line = y_position - (line_idx * row_height)
                for label, width, align in columns:
                    lines = cell_lines.get(label, [""])
                    text = lines[line_idx] if line_idx < len(lines) else ""
                    if align == "right":
                        pdf.drawRightString(x + width - 1 * mm, y_line, text)
                    elif align == "center":
                        pdf.drawCentredString(x + (width / 2), y_line, text)
                    else:
                        pdf.drawString(x, y_line, text)
                    x += width
            y_position -= row_height_total

        _draw_footer()

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer.read()


def canonical_material_label(value: object) -> str:
    raw = str(value or "").strip()
    key = re.sub(r"[^a-z]", "", raw.lower())
    mapping = {
        "cement": "Cement",
        "flyash": "Fly Ash",
        "stonedust": "Stone Dust",
    }
    return mapping.get(key, raw)


def material_qty_to_tons(material: str, qty: float) -> float:
    label = canonical_material_label(material)
    label_lower = label.lower()
    if label_lower == "cement":
        return qty * 0.05
    if label_lower in {"fly ash", "stone dust"}:
        return qty
    return 0.0


def _stock_in_tons(raw_df: pd.DataFrame) -> pd.Series:
    if raw_df.empty:
        return pd.Series(dtype=float)
    material = raw_df.get("Material", pd.Series(dtype=str)).astype(str).str.strip().str.lower()
    qty = pd.to_numeric(raw_df.get("Qty", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    stock = pd.Series(0.0, index=raw_df.index, dtype=float)
    cement_mask = material == "cement"
    flyash_mask = material == "fly ash"
    stone_mask = material == "stone dust"
    stock.loc[cement_mask] = qty.loc[cement_mask] * 0.025
    stock.loc[flyash_mask] = qty.loc[flyash_mask]
    stock.loc[stone_mask] = qty.loc[stone_mask]
    return stock


def compute_stock_log(raw_df: pd.DataFrame, production_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["Date", "Month", "Material", "Opening", "Inward", "Consumed", "Closing"]
    if raw_df.empty and production_df.empty:
        return pd.DataFrame(columns=columns)

    raw_df = ensure_columns(raw_df, ["Date", "Material", "Qty"])
    production_df = ensure_columns(
        production_df,
        ["Date", "Cement_Consumption", "FlyAsh_Consumption", "StoneDust_Consumption"],
    )

    raw_df["Date"] = pd.to_datetime(raw_df["Date"], errors="coerce", dayfirst=True).dt.date
    production_df["Date"] = pd.to_datetime(
        production_df["Date"],
        errors="coerce",
        dayfirst=True,
    ).dt.date
    raw_df = raw_df.dropna(subset=["Date"])
    production_df = production_df.dropna(subset=["Date"])

    raw_df["Material"] = raw_df["Material"].astype(str).str.strip().apply(
        canonical_material_label
    )
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
        "Stone Dust": "StoneDust_Consumption",
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
