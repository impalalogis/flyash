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
    raw_df["Material"] = raw_df["Material"].astype(str).str.strip().apply(
        utils.canonical_material_label
    )
    raw_df["Stock_In_Tons"] = raw_df.apply(
        lambda row: utils.material_qty_to_tons(
            row.get("Material", ""), utils.safe_float(row.get("Qty", 0))
        ),
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
    physical_df["Material"] = physical_df["Material"].astype(str).str.strip().apply(
        utils.canonical_material_label
    )

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
    production_window = production_df[
        (production_df["Date"] >= start_date) & (production_df["Date"] <= end_date)
    ]
    bricks_produced = utils.to_numeric_series(
        production_window.get("No_of_Bricks", pd.Series(dtype=float))
    ).fillna(0.0).sum()

    cement_used_bags = utils.to_numeric_series(
        production_window.get("Cement_Consumption", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    flyash_used_kg = utils.to_numeric_series(
        production_window.get("FlyAsh_Consumption", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    stonedust_used_kg = utils.to_numeric_series(
        production_window.get("StoneDust_Consumption", pd.Series(dtype=float))
    ).fillna(0.0).sum()

    cement_used_kg = cement_used_bags * 50
    cement_used_ton = cement_used_kg / 1000
    flyash_used_ton = flyash_used_kg / 1000
    stonedust_used_ton = stonedust_used_kg / 1000

    cement_purchased_bags = raw_df.loc[
        (raw_df["Date"] >= start_date)
        & (raw_df["Date"] <= end_date)
        & (raw_df["Material"].astype(str).str.strip().str.lower() == "cement"),
        "Qty",
    ].sum()
    cement_purchased_kg = cement_purchased_bags * 50
    cement_purchased_ton = cement_purchased_kg / 1000
    flyash_purchased_ton = raw_df.loc[
        (raw_df["Date"] >= start_date)
        & (raw_df["Date"] <= end_date)
        & (raw_df["Material"].astype(str).str.strip().str.lower() == "fly ash"),
        "Qty",
    ].sum()
    stonedust_purchased_ton = raw_df.loc[
        (raw_df["Date"] >= start_date)
        & (raw_df["Date"] <= end_date)
        & (raw_df["Material"].astype(str).str.strip().str.lower() == "stone dust"),
        "Qty",
    ].sum()

    cement_stock_ton = cement_purchased_ton - cement_used_ton
    flyash_stock_ton = flyash_purchased_ton - flyash_used_ton
    stonedust_stock_ton = stonedust_purchased_ton - stonedust_used_ton

    cement_per_brick = cement_used_kg / bricks_produced if bricks_produced else 0.0
    flyash_per_brick = flyash_used_kg / bricks_produced if bricks_produced else 0.0
    stonedust_per_brick = stonedust_used_kg / bricks_produced if bricks_produced else 0.0
    total_material_per_brick = cement_per_brick + flyash_per_brick + stonedust_per_brick

    cement_pct = cement_per_brick / total_material_per_brick if total_material_per_brick else 0.0
    flyash_pct = flyash_per_brick / total_material_per_brick if total_material_per_brick else 0.0
    stonedust_pct = stonedust_per_brick / total_material_per_brick if total_material_per_brick else 0.0

    standard = {
        "cement": 0.20,
        "flyash": 1.70,
        "stone_dust": 1.45,
    }
    cement_variance = cement_per_brick - standard["cement"]
    flyash_variance = flyash_per_brick - standard["flyash"]
    stonedust_variance = stonedust_per_brick - standard["stone_dust"]
    cement_variance_pct = cement_variance / standard["cement"] if standard["cement"] else 0.0
    flyash_variance_pct = flyash_variance / standard["flyash"] if standard["flyash"] else 0.0
    stonedust_variance_pct = stonedust_variance / standard["stone_dust"] if standard["stone_dust"] else 0.0

    alerts = []
    if cement_stock_ton < 0 or flyash_stock_ton < 0 or stonedust_stock_ton < 0:
        alerts.append("NEGATIVE STOCK — opening stock missing")
    if flyash_variance_pct > 0.10:
        alerts.append("HIGH FLYASH USAGE")
    if cement_variance_pct > 0.10:
        alerts.append("HIGH CEMENT USAGE")
    if stonedust_variance_pct > 0.10:
        alerts.append("HIGH STONE DUST USAGE")

    system_rows = [
        {"Material": "Cement", "Purchased_Ton": round(cement_purchased_ton, 2), "Used_Ton": round(cement_used_ton, 2), "Stock_Ton": round(cement_stock_ton, 2)},
        {"Material": "Fly Ash", "Purchased_Ton": round(flyash_purchased_ton, 2), "Used_Ton": round(flyash_used_ton, 2), "Stock_Ton": round(flyash_stock_ton, 2)},
        {"Material": "Stone Dust", "Purchased_Ton": round(stonedust_purchased_ton, 2), "Used_Ton": round(stonedust_used_ton, 2), "Stock_Ton": round(stonedust_stock_ton, 2)},
    ]

    usage_rows = [
        {"Material": "Cement", "Kg_per_Brick": round(cement_per_brick, 3), "Composition_%": f"{cement_pct:.1%}"},
        {"Material": "Fly Ash", "Kg_per_Brick": round(flyash_per_brick, 3), "Composition_%": f"{flyash_pct:.1%}"},
        {"Material": "Stone Dust", "Kg_per_Brick": round(stonedust_per_brick, 3), "Composition_%": f"{stonedust_pct:.1%}"},
    ]

    variance_rows = [
        {"Material": "Cement", "Standard_kg": standard["cement"], "Actual_kg": round(cement_per_brick, 3), "Variance_kg": round(cement_variance, 3), "Variance_%": f"{cement_variance_pct:.1%}"},
        {"Material": "Fly Ash", "Standard_kg": standard["flyash"], "Actual_kg": round(flyash_per_brick, 3), "Variance_kg": round(flyash_variance, 3), "Variance_%": f"{flyash_variance_pct:.1%}"},
        {"Material": "Stone Dust", "Standard_kg": standard["stone_dust"], "Actual_kg": round(stonedust_per_brick, 3), "Variance_kg": round(stonedust_variance, 3), "Variance_%": f"{stonedust_variance_pct:.1%}"},
    ]

    physical_rows = []
    for material in materials:
        physical_stock = _latest_physical(physical_df, material, end_date)
        system_stock = {
            "cement": cement_stock_ton,
            "fly ash": flyash_stock_ton,
            "stone dust": stonedust_stock_ton,
        }.get(material.lower(), 0.0)
        variance = system_stock - (physical_stock if physical_stock is not None else 0.0)
        variance_pct = variance / physical_stock if physical_stock not in (None, 0) else None
        physical_rows.append(
            {
                "Material": material,
                "System_Stock_Ton": round(system_stock, 2),
                "Physical_Stock_Ton": round(physical_stock, 2) if physical_stock is not None else "n/a",
                "Variance_Ton": round(variance, 2),
                "Variance_%": f"{variance_pct:.1%}" if variance_pct is not None else "n/a",
            }
        )

    cost_rows = []
    for material, used_ton in [
        ("Cement", cement_used_ton),
        ("Fly Ash", flyash_used_ton),
        ("Stone Dust", stonedust_used_ton),
    ]:
        material_mask = raw_df["Material"].astype(str).str.strip().str.lower() == material.lower()
        material_cost = utils.to_numeric_series(
            raw_df.loc[material_mask, "Total_Cost"]
        ).fillna(0.0).sum()
        purchased_ton = raw_df.loc[material_mask, "Stock_In_Tons"].sum()
        rate_per_ton = material_cost / purchased_ton if purchased_ton else 0.0
        actual_cost = used_ton * rate_per_ton
        cost_per_brick = actual_cost / bricks_produced if bricks_produced else 0.0
        cost_rows.append(
            {
                "Material": material,
                "Rate_per_Ton": round(rate_per_ton, 2),
                "Actual_Cost": round(actual_cost, 2),
                "Cost_per_Brick": round(cost_per_brick, 4),
            }
        )

    total_cost_per_brick = (
        sum(row["Actual_Cost"] for row in cost_rows) / bricks_produced if bricks_produced else 0.0
    )

    st.subheader("Stock Summary (tons)")
    st.dataframe(pd.DataFrame(system_rows), width="stretch")

    st.subheader("System Stock vs Physical Stock")
    st.dataframe(pd.DataFrame(physical_rows), width="stretch")

    st.subheader("Material Usage per Brick (kg)")
    st.dataframe(pd.DataFrame(usage_rows), width="stretch")

    st.subheader("Composition Percentages per Brick")
    st.dataframe(pd.DataFrame(usage_rows)[["Material", "Composition_%"]], width="stretch")

    st.subheader("Standard vs Actual (kg/brick)")
    st.dataframe(pd.DataFrame(variance_rows), width="stretch")

    st.subheader("Cost per Brick")
    cost_df = pd.DataFrame(cost_rows)
    cost_df.loc[len(cost_df)] = {
        "Material": "Total",
        "Rate_per_Ton": "",
        "Actual_Cost": round(sum(row["Actual_Cost"] for row in cost_rows), 2),
        "Cost_per_Brick": round(total_cost_per_brick, 4),
    }
    st.dataframe(cost_df, width="stretch")

    st.subheader("Diagnostic KPI Report")
    diagnostic_rows = [
        {
            "Material": "Cement",
            "Purchased_Ton": round(cement_purchased_ton, 2),
            "Used_Ton": round(cement_used_ton, 2),
            "Stock_Ton": round(cement_stock_ton, 2),
            "Kg_per_Brick": round(cement_per_brick, 3),
            "Percentage": f"{cement_pct:.1%}",
            "Standard_kg": standard["cement"],
            "Variance_kg": round(cement_variance, 3),
            "Variance_%": f"{cement_variance_pct:.1%}",
        },
        {
            "Material": "Fly Ash",
            "Purchased_Ton": round(flyash_purchased_ton, 2),
            "Used_Ton": round(flyash_used_ton, 2),
            "Stock_Ton": round(flyash_stock_ton, 2),
            "Kg_per_Brick": round(flyash_per_brick, 3),
            "Percentage": f"{flyash_pct:.1%}",
            "Standard_kg": standard["flyash"],
            "Variance_kg": round(flyash_variance, 3),
            "Variance_%": f"{flyash_variance_pct:.1%}",
        },
        {
            "Material": "Stone Dust",
            "Purchased_Ton": round(stonedust_purchased_ton, 2),
            "Used_Ton": round(stonedust_used_ton, 2),
            "Stock_Ton": round(stonedust_stock_ton, 2),
            "Kg_per_Brick": round(stonedust_per_brick, 3),
            "Percentage": f"{stonedust_pct:.1%}",
            "Standard_kg": standard["stone_dust"],
            "Variance_kg": round(stonedust_variance, 3),
            "Variance_%": f"{stonedust_variance_pct:.1%}",
        },
    ]
    st.dataframe(pd.DataFrame(diagnostic_rows), width="stretch")

    st.subheader("Alerts")
    if alerts:
        critical = [item for item in alerts if "NEGATIVE STOCK" in item]
        warning = [item for item in alerts if "HIGH" in item]
        if critical:
            st.error("\n".join(critical))
        if warning:
            st.warning("\n".join(warning))
    else:
        st.success("No over-consumption or negative stock alerts.")
