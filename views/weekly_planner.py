from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import database
import utils


WORK_WEEK_COLUMNS = ["Week_Start", "Week_End", "Total_Days"]
HOLIDAY_COLUMNS = ["Date", "Name"]
CONFIG_COLUMNS = ["Key", "Value", "Notes"]


DEFAULT_CONFIG = {
    "history_window_days": 90,
    "min_target_pct": 0.9,
    "ideal_target_pct": 1.0,
    "stretch_target_pct": 1.1,
    "buffer_pct": 0.1,
    "electricity_per_week": 0.0,
    "transport_per_week": 0.0,
    "maintenance_per_week": 0.0,
    "misc_per_week": 0.0,
    "cement_per_brick": 0.0,
    "flyash_per_brick": 0.0,
    "stone_dust_per_brick": 0.0,
}


def _parse_date(value: object) -> date | None:
    return utils.parse_date_value(value, dayfirst=True)


def _get_config() -> dict[str, float]:
    config_df = database.read_table("Planning_Config")
    production_secrets = st.secrets.get("production", {})
    defaults = DEFAULT_CONFIG.copy()
    defaults["flyash_per_brick"] = utils.safe_float(
        production_secrets.get("flyash_per_brick"),
        defaults["flyash_per_brick"],
    )
    defaults["stone_dust_per_brick"] = utils.safe_float(
        production_secrets.get("stone_dust_per_brick"),
        defaults["stone_dust_per_brick"],
    )
    if config_df.empty:
        return defaults
    config_df = utils.ensure_columns(config_df, CONFIG_COLUMNS)
    config_map = {}
    for _, row in config_df.iterrows():
        key = str(row.get("Key", "")).strip()
        if not key:
            continue
        config_map[key] = utils.safe_float(row.get("Value"), defaults.get(key, 0.0))
    merged = defaults.copy()
    merged.update(config_map)
    return merged


def _average_cost(raw_df: pd.DataFrame, material: str, window_days: int) -> float:
    if raw_df.empty:
        return 0.0
    cutoff = date.today() - timedelta(days=window_days)
    raw_df = raw_df.copy()
    raw_df["Date"] = utils.to_datetime_series_explicit(raw_df["Date"], dayfirst=True).dt.date
    raw_df = raw_df[raw_df["Date"] >= cutoff]
    raw_df = raw_df[raw_df["Material"].astype(str).str.strip().str.lower() == material.lower()]
    qty = utils.to_numeric_series(raw_df.get("Qty", pd.Series(dtype=float))).fillna(0.0)
    total_cost = utils.to_numeric_series(raw_df.get("Total_Cost", pd.Series(dtype=float))).fillna(0.0)
    if qty.sum() <= 0:
        return 0.0
    return float(total_cost.sum() / qty.sum())


def _latest_material_stock(stock_df: pd.DataFrame, material: str) -> float:
    if stock_df.empty:
        return 0.0
    stock_df = stock_df.copy()
    stock_df["Date"] = utils.to_datetime_series_explicit(stock_df["Date"], dayfirst=True).dt.date
    stock_df = stock_df[stock_df["Material"].astype(str).str.strip().str.lower() == material.lower()]
    if stock_df.empty:
        return 0.0
    latest = stock_df.sort_values("Date").iloc[-1]
    return utils.safe_float(latest.get("Closing", 0))


def render() -> None:
    st.header("Weekly Planner")

    st.subheader("Planning Inputs")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Work Week**")
        work_week_df = database.read_table("Work_Week")
        if work_week_df.empty:
            work_week_df = pd.DataFrame(columns=WORK_WEEK_COLUMNS)
        work_week_df = utils.ensure_columns(work_week_df, WORK_WEEK_COLUMNS)
        work_week_editor = st.data_editor(
            work_week_df,
            num_rows="dynamic",
            use_container_width=True,
            key="work_week_editor",
        )
        if st.button("Save Work Week", key="save_work_week"):
            updated = work_week_editor.copy().fillna("")
            database.replace_table("Work_Week", updated, recompute_stock=False)
            st.success("Work week updated.")

    with col2:
        st.markdown("**Holidays**")
        holiday_df = database.read_table("Holidays")
        if holiday_df.empty:
            holiday_df = pd.DataFrame(columns=HOLIDAY_COLUMNS)
        holiday_df = utils.ensure_columns(holiday_df, HOLIDAY_COLUMNS)
        holiday_editor = st.data_editor(
            holiday_df,
            num_rows="dynamic",
            use_container_width=True,
            key="holiday_editor",
        )
        if st.button("Save Holidays", key="save_holidays"):
            updated = holiday_editor.copy().fillna("")
            database.replace_table("Holidays", updated, recompute_stock=False)
            st.success("Holidays updated.")

    st.markdown("**Planning Assumptions**")
    config_df = database.read_table("Planning_Config")
    if config_df.empty:
        defaults_for_editor = _get_config()
        config_df = pd.DataFrame(
            [
                {"Key": key, "Value": value, "Notes": ""}
                for key, value in defaults_for_editor.items()
            ]
        )
    config_df = utils.ensure_columns(config_df, CONFIG_COLUMNS)
    config_editor = st.data_editor(
        config_df,
        num_rows="dynamic",
        use_container_width=True,
        key="planning_config_editor",
    )
    if st.button("Save Planning Config", key="save_planning_config"):
        updated = config_editor.copy().fillna("")
        database.replace_table("Planning_Config", updated, recompute_stock=False)
        st.success("Planning config updated.")

    config = _get_config()

    work_week = work_week_df.copy()
    week_start = _parse_date(work_week.get("Week_Start", pd.Series(dtype=str)).iloc[0]) if not work_week.empty else None
    week_end = _parse_date(work_week.get("Week_End", pd.Series(dtype=str)).iloc[0]) if not work_week.empty else None
    if week_start is None or week_end is None:
        st.warning("Please set Week_Start and Week_End in the Work_Week sheet.")
        st.stop()

    total_days = utils.safe_int(work_week.get("Total_Days", pd.Series(dtype=int)).iloc[0], default=0)
    if total_days <= 0:
        total_days = (week_end - week_start).days + 1

    holiday_df = holiday_df.copy()
    holiday_df["Date"] = utils.to_datetime_series_explicit(
        holiday_df.get("Date", pd.Series(dtype=str)),
        dayfirst=True,
    ).dt.date
    holiday_dates = holiday_df["Date"].dropna().tolist()
    holiday_count = sum(1 for day in holiday_dates if week_start <= day <= week_end)
    available_days = max(total_days - holiday_count, 0)

    st.subheader("Weekly Plan Summary")
    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("Week Start", week_start.isoformat())
    summary_col2.metric("Week End", week_end.isoformat())
    summary_col3.metric("Available Production Days", f"{available_days}")

    production_df = database.read_table("Production_Log")
    production_df = utils.ensure_columns(production_df, ["Date", "No_of_Bricks", "Cement_Consumption", "FlyAsh_Consumption", "StoneDust_Consumption", "Labour_Expense", "No_of_Labour"])
    production_df["Date"] = utils.to_datetime_series_explicit(production_df["Date"], dayfirst=True).dt.date

    sales_df = database.read_table("Sales_Log")
    sales_df = utils.ensure_columns(sales_df, ["Date", "No_of_Bricks", "Total_Amount", "Freight"])
    sales_df["Date"] = utils.to_datetime_series_explicit(sales_df["Date"], dayfirst=True).dt.date

    raw_df = database.read_table("Raw_Material_Log")
    raw_df = utils.ensure_columns(raw_df, ["Date", "Material", "Qty", "Total_Cost"])
    stock_df = database.read_table("Stock_Log")
    stock_df = utils.ensure_columns(stock_df, ["Date", "Material", "Closing"])

    history_days = int(config.get("history_window_days", 90))
    cutoff = date.today() - timedelta(days=history_days)
    prod_window = production_df[production_df["Date"] >= cutoff]
    sales_window = sales_df[sales_df["Date"] >= cutoff]

    prod_window["No_of_Bricks"] = utils.to_numeric_series(
        prod_window.get("No_of_Bricks", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_window["No_of_Bricks"] = utils.to_numeric_series(
        sales_window.get("No_of_Bricks", pd.Series(dtype=float))
    ).fillna(0.0)

    prod_days = prod_window.loc[prod_window["No_of_Bricks"] > 0, "Date"].nunique()
    avg_daily_production = (prod_window["No_of_Bricks"].sum() / prod_days) if prod_days else 0.0
    capacity = avg_daily_production * available_days

    min_target = capacity * config.get("min_target_pct", 0.9)
    ideal_target = capacity * config.get("ideal_target_pct", 1.0)
    stretch_target = capacity * config.get("stretch_target_pct", 1.1)

    st.subheader("Production Plan")
    production_plan = pd.DataFrame(
        [
            {"Target": "Minimum", "Bricks": round(min_target, 0)},
            {"Target": "Ideal", "Bricks": round(ideal_target, 0)},
            {"Target": "Stretch", "Bricks": round(stretch_target, 0)},
        ]
    )
    st.dataframe(production_plan, use_container_width=True)

    cement_ratio = config.get("cement_per_brick", 0.0)
    if cement_ratio <= 0 and prod_window["No_of_Bricks"].sum() > 0:
        cement_ratio = (
            utils.to_numeric_series(prod_window.get("Cement_Consumption", pd.Series(dtype=float))).fillna(0.0).sum()
            / prod_window["No_of_Bricks"].sum()
        )
    flyash_ratio = utils.safe_float(config.get("flyash_per_brick", 0.0))
    stone_ratio = utils.safe_float(config.get("stone_dust_per_brick", 0.0))

    requirement = {
        "Cement": ideal_target * cement_ratio,
        "Fly Ash": ideal_target * flyash_ratio,
        "Stone Dust": ideal_target * stone_ratio,
    }

    buffer_pct = config.get("buffer_pct", 0.1)
    procurement_rows = []
    for material, qty in requirement.items():
        stock = _latest_material_stock(stock_df, material)
        buffer = qty * buffer_pct
        purchase_qty = max(qty + buffer - stock, 0.0)
        purchase_timing = "Buy now" if stock < buffer else "Monitor"
        procurement_rows.append(
            {
                "Material": material,
                "Requirement": round(qty, 2),
                "Buffer": round(buffer, 2),
                "Current Stock": round(stock, 2),
                "Purchase Qty": round(purchase_qty, 2),
                "Timing": purchase_timing,
            }
        )
    st.subheader("Procurement Plan")
    st.dataframe(pd.DataFrame(procurement_rows), use_container_width=True)

    sales_days = sales_window.loc[sales_window["No_of_Bricks"] > 0, "Date"].nunique()
    avg_daily_sales = (
        sales_window["No_of_Bricks"].sum() / sales_days if sales_days else 0.0
    )
    current_inventory = (
        utils.to_numeric_series(production_df.get("No_of_Bricks", pd.Series(dtype=float))).fillna(0.0).sum()
        - utils.to_numeric_series(sales_df.get("No_of_Bricks", pd.Series(dtype=float))).fillna(0.0).sum()
    )
    current_inventory = max(current_inventory, 0.0)
    sales_target = min(current_inventory + ideal_target, avg_daily_sales * available_days)

    st.subheader("Sales Plan")
    st.dataframe(
        pd.DataFrame(
            [
                {"Metric": "Avg daily sales (historical)", "Value": round(avg_daily_sales, 0)},
                {"Metric": "Current inventory", "Value": round(current_inventory, 0)},
                {"Metric": "Weekly sales target", "Value": round(sales_target, 0)},
            ]
        ),
        use_container_width=True,
    )

    avg_price = (
        utils.to_numeric_series(sales_window.get("Total_Amount", pd.Series(dtype=float))).fillna(0.0).sum()
        / sales_window["No_of_Bricks"].sum()
        if sales_window["No_of_Bricks"].sum() > 0
        else 0.0
    )

    cement_cost = _average_cost(raw_df, "Cement", history_days)
    flyash_cost = _average_cost(raw_df, "Fly Ash", history_days)
    stone_cost = _average_cost(raw_df, "Stone Dust", history_days)

    raw_cost_est = (
        requirement["Cement"] * cement_cost
        + requirement["Fly Ash"] * flyash_cost
        + requirement["Stone Dust"] * stone_cost
    )
    labour_cost = (
        utils.to_numeric_series(prod_window.get("Labour_Expense", pd.Series(dtype=float))).fillna(0.0).sum()
        / prod_days
        * available_days
        if prod_days
        else 0.0
    )

    electricity_cost = config.get("electricity_per_week", 0.0)
    transport_cost = config.get("transport_per_week", 0.0)
    maintenance_cost = config.get("maintenance_per_week", 0.0)
    misc_cost = config.get("misc_per_week", 0.0)

    total_cost = raw_cost_est + labour_cost + electricity_cost + transport_cost + maintenance_cost + misc_cost
    revenue = sales_target * avg_price
    profit = revenue - total_cost

    st.subheader("Weekly Budget")
    budget_rows = [
        ("Raw material cost", raw_cost_est),
        ("Labour cost", labour_cost),
        ("Electricity", electricity_cost),
        ("Transport", transport_cost),
        ("Maintenance", maintenance_cost),
        ("Miscellaneous", misc_cost),
    ]
    budget_df = pd.DataFrame(
        [{"Cost": name, "Amount": round(value, 2)} for name, value in budget_rows]
    )
    st.dataframe(budget_df, use_container_width=True)

    st.subheader("Expected Revenue & Profit")
    st.dataframe(
        pd.DataFrame(
            [
                {"Metric": "Expected revenue", "Value": round(revenue, 2)},
                {"Metric": "Expected profit", "Value": round(profit, 2)},
                {"Metric": "Average selling price per brick", "Value": round(avg_price, 2)},
            ]
        ),
        use_container_width=True,
    )

    st.subheader("Weekly Recommendations")
    recommendations = [
        "- Align production to the ideal target to avoid excess inventory.",
        "- Procure raw materials early if stock is below buffer levels.",
        "- Track sales daily to adjust output before mid-week.",
        "- Review labour scheduling if output per day is below average.",
        "- Monitor cash flow: delay non-critical costs if expected profit is low.",
    ]
    st.markdown("\n".join(recommendations))
