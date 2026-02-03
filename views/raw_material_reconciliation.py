from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import database
import utils


PHYSICAL_COLUMNS = ["Date", "Material", "Physical_Stock_Tons", "Notes"]


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value in ("", None):
        return None
    try:
        return pd.to_datetime(str(value), errors="coerce", dayfirst=True).date()
    except Exception:
        return None


def _latest_by_material(frame: pd.DataFrame, material: str, date_limit: date) -> float:
    if frame.empty:
        return 0.0
    material_mask = frame["Material"].astype(str).str.strip().str.lower() == material.lower()
    frame = frame[material_mask]
    frame = frame[frame["Date"] <= date_limit]
    if frame.empty:
        return 0.0
    return utils.safe_float(frame.sort_values("Date").iloc[-1].get("Closing", 0))


def _latest_physical(frame: pd.DataFrame, material: str, date_limit: date) -> float | None:
    if frame.empty:
        return None
    material_mask = frame["Material"].astype(str).str.strip().str.lower() == material.lower()
    frame = frame[material_mask]
    frame = frame[frame["Date"] <= date_limit]
    if frame.empty:
        return None
    return utils.safe_float(frame.sort_values("Date").iloc[-1].get("Physical_Stock_Tons", 0))


def _material_per_brick(
    material: str,
    production_df: pd.DataFrame,
    config: dict[str, float],
    start_date: date,
    end_date: date,
) -> float:
    key_map = {
        "cement": "cement_per_brick",
        "fly ash": "flyash_per_brick",
        "stone dust": "stone_dust_per_brick",
    }
    key = key_map.get(material.lower())
    if key and config.get(key, 0) > 0:
        return float(config[key])
    subset = production_df[(production_df["Date"] >= start_date) & (production_df["Date"] <= end_date)]
    bricks = utils.to_numeric_series(subset.get("No_of_Bricks", pd.Series(dtype=float))).fillna(0.0).sum()
    if bricks <= 0:
        return 0.0
    col_map = {
        "cement": "Cement_Consumption",
        "fly ash": "FlyAsh_Consumption",
        "stone dust": "StoneDust_Consumption",
    }
    col = col_map.get(material.lower(), "")
    if not col or col not in subset.columns:
        return 0.0
    consumption = utils.to_numeric_series(subset.get(col, pd.Series(dtype=float))).fillna(0.0).sum()
    return float(consumption / bricks) if bricks else 0.0


def render() -> None:
    st.header("Raw Material Reconciliation")

    st.subheader("Physical Stock Log")
    st.caption("Enter physical stock counts in tons for Cement, Fly Ash, and Stone Dust.")
    physical_df = database.read_table("Physical_Stock_Log")
    if physical_df.empty:
        physical_df = pd.DataFrame(columns=PHYSICAL_COLUMNS)
    physical_df = utils.ensure_columns(physical_df, PHYSICAL_COLUMNS)
    physical_editor = st.data_editor(
        physical_df,
        num_rows="dynamic",
        width="stretch",
        key="physical_stock_editor",
    )
    if st.button("Save Physical Stock", key="save_physical_stock"):
        updated = physical_editor.copy().fillna("")
        database.replace_table("Physical_Stock_Log", updated, recompute_stock=False)
        st.success("Physical stock updated.")

    raw_df = database.read_table("Raw_Material_Log")
    raw_df = utils.ensure_columns(raw_df, ["Date", "Material", "Qty", "Total_Cost"])
    raw_df["Date"] = pd.to_datetime(raw_df["Date"], errors="coerce", dayfirst=True).dt.date
    raw_df["Qty"] = utils.to_numeric_series(raw_df.get("Qty", pd.Series(dtype=float))).fillna(0.0)
    raw_df["Stock_In_Tons"] = raw_df.apply(
        lambda row: utils.material_qty_to_tons(row.get("Material", ""), utils.safe_float(row.get("Qty", 0))),
        axis=1,
    )

    production_df = database.read_table("Production_Log")
    production_df = utils.ensure_columns(
        production_df,
        ["Date", "No_of_Bricks", "Cement_Consumption", "FlyAsh_Consumption", "StoneDust_Consumption"],
    )
    production_df["Date"] = pd.to_datetime(production_df["Date"], errors="coerce", dayfirst=True).dt.date

    stock_df = database.read_table("Stock_Log")
    stock_df = utils.ensure_columns(stock_df, ["Date", "Material", "Closing"])
    stock_df["Date"] = pd.to_datetime(stock_df["Date"], errors="coerce", dayfirst=True).dt.date

    physical_df = physical_df.copy()
    physical_df["Date"] = pd.to_datetime(physical_df["Date"], errors="coerce", dayfirst=True).dt.date
    physical_df["Physical_Stock_Tons"] = utils.to_numeric_series(
        physical_df.get("Physical_Stock_Tons", pd.Series(dtype=float))
    ).fillna(0.0)

    all_dates = pd.concat(
        [
            raw_df["Date"].dropna(),
            production_df["Date"].dropna(),
            physical_df["Date"].dropna(),
        ],
        ignore_index=True,
    )
    if all_dates.empty:
        st.info("Add production and raw material data to generate reconciliation.")
        return
    min_date = all_dates.min()
    max_date = all_dates.max()
    date_range = st.date_input("Reconciliation date range", value=(min_date, max_date))
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = min_date
        end_date = max_date

    config_df = database.read_table("Planning_Config")
    config_df = utils.ensure_columns(config_df, ["Key", "Value"])
    config = {str(row.get("Key", "")).strip(): utils.safe_float(row.get("Value", 0)) for _, row in config_df.iterrows()}
    production_secrets = st.secrets.get("production", {})
    config["flyash_per_brick"] = utils.safe_float(
        production_secrets.get("flyash_per_brick"), config.get("flyash_per_brick", 0.0)
    )
    config["stone_dust_per_brick"] = utils.safe_float(
        production_secrets.get("stone_dust_per_brick"), config.get("stone_dust_per_brick", 0.0)
    )

    materials = ["Cement", "Fly Ash", "Stone Dust"]
    bricks_produced = utils.to_numeric_series(
        production_df.loc[
            (production_df["Date"] >= start_date) & (production_df["Date"] <= end_date),
            "No_of_Bricks",
        ]
    ).fillna(0.0).sum()

    system_rows = []
    consumption_rows = []
    cost_rows = []
    alerts = []
    for material in materials:
        inbound_tons = raw_df.loc[
            (raw_df["Date"] >= start_date)
            & (raw_df["Date"] <= end_date)
            & (raw_df["Material"].astype(str).str.strip().str.lower() == material.lower()),
            "Stock_In_Tons",
        ].sum()
        system_stock = _latest_by_material(stock_df, material, end_date)
        physical_stock = _latest_physical(physical_df, material, end_date)
        variance = system_stock - (physical_stock if physical_stock is not None else 0.0)
        variance_pct = variance / physical_stock if physical_stock not in (None, 0) else None

        system_rows.append(
            {
                "Material": material,
                "System_Stock_Tons": round(system_stock, 2),
                "Physical_Stock_Tons": round(physical_stock, 2) if physical_stock is not None else "n/a",
                "Variance_Tons": round(variance, 2),
                "Variance_%": f"{variance_pct:.1%}" if variance_pct is not None else "n/a",
            }
        )

        expected_per_brick = _material_per_brick(material, production_df, config, start_date, end_date)
        expected_usage = bricks_produced * expected_per_brick
        actual_usage = inbound_tons - system_stock
        variance_use = actual_usage - expected_usage
        variance_use_pct = variance_use / expected_usage if expected_usage else None

        consumption_rows.append(
            {
                "Material": material,
                "Expected_Usage_Tons": round(expected_usage, 2),
                "Actual_Usage_Tons": round(actual_usage, 2),
                "Variance_Tons": round(variance_use, 2),
                "Variance_%": f"{variance_use_pct:.1%}" if variance_use_pct is not None else "n/a",
            }
        )

        cost_window = raw_df.loc[
            (raw_df["Date"] >= start_date)
            & (raw_df["Date"] <= end_date)
            & (raw_df["Material"].astype(str).str.strip().str.lower() == material.lower())
        ]
        total_cost = utils.to_numeric_series(cost_window.get("Total_Cost", pd.Series(dtype=float))).fillna(0.0).sum()
        cost_per_ton = (total_cost / inbound_tons) if inbound_tons else 0.0
        actual_cost = actual_usage * cost_per_ton
        cost_per_brick = actual_cost / bricks_produced if bricks_produced else 0.0

        cost_rows.append(
            {
                "Material": material,
                "Rate_per_Ton": round(cost_per_ton, 2),
                "Actual_Cost": round(actual_cost, 2),
                "Cost_per_Brick": round(cost_per_brick, 4),
            }
        )

        if system_stock < 0:
            alerts.append(f"{material}: negative system stock.")
        if variance_use_pct is not None and abs(variance_use_pct) > 0.1:
            alerts.append(f"{material}: high consumption variance ({variance_use_pct:.0%}).")
        if variance_pct is not None and abs(variance_pct) > 0.1:
            alerts.append(f"{material}: stock variance exceeds 10%.")

    total_cost_per_brick = (
        sum(row["Actual_Cost"] for row in cost_rows) / bricks_produced if bricks_produced else 0.0
    )

    st.subheader("System Stock vs Physical Stock")
    st.dataframe(pd.DataFrame(system_rows), width="stretch")

    st.subheader("Expected vs Actual Consumption")
    st.dataframe(pd.DataFrame(consumption_rows), width="stretch")

    st.subheader("Cost per Brick")
    cost_df = pd.DataFrame(cost_rows)
    cost_df.loc[len(cost_df)] = {
        "Material": "Total",
        "Rate_per_Ton": "",
        "Actual_Cost": round(sum(row["Actual_Cost"] for row in cost_rows), 2),
        "Cost_per_Brick": round(total_cost_per_brick, 4),
    }
    st.dataframe(cost_df, width="stretch")

    st.subheader("Variance Analysis & Alerts")
    if alerts:
        st.markdown("\n".join([f"- {item}" for item in alerts]))
    else:
        st.info("No high variance or negative stock alerts.")
