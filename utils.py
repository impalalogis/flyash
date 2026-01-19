from __future__ import annotations

from datetime import date
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
