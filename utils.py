from __future__ import annotations

from datetime import date, datetime
import re
from typing import Iterable

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
