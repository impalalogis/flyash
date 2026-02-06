from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import database
import utils


def _parse_dates(data_frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if column not in data_frame.columns:
        return data_frame
    data_frame = data_frame.copy()
    month_hint = data_frame["Month"] if "Month" in data_frame.columns else None
    data_frame[column] = utils.parse_date_series(
        data_frame[column],
        month_hint=month_hint,
    ).dt.date
    return data_frame


def _filter_by_date(data_frame: pd.DataFrame, column: str, start: date, end: date) -> pd.DataFrame:
    if column not in data_frame.columns:
        return data_frame
    month_hint = data_frame["Month"] if "Month" in data_frame.columns else None
    series = utils.parse_date_series(data_frame[column], month_hint=month_hint)
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)
    return data_frame[(series >= start_ts) & (series <= end_ts)]


def _add_period_column(data_frame: pd.DataFrame, column: str, period: str) -> pd.DataFrame:
    if column not in data_frame.columns:
        return data_frame
    freq = {"Monthly": "M", "Quarterly": "Q", "Yearly": "Y"}[period]
    data_frame = data_frame.copy()
    dt = pd.to_datetime(data_frame[column], errors="coerce", dayfirst=True)
    data_frame["Period"] = dt.dt.to_period(freq).astype(str)
    data_frame = data_frame[data_frame["Period"] != "NaT"]
    return data_frame


def _period_label(value: pd.Period, freq: str) -> str:
    if pd.isna(value):
        return ""
    if freq == "M":
        return value.to_timestamp().strftime("%b-%Y")
    if freq == "Q":
        return f"{value.year} Q{value.quarter}"
    return str(value.year)


FY_START_MONTH = 4


def _fy_start_year(value: date) -> int:
    return value.year if value.month >= FY_START_MONTH else value.year - 1


def _fy_label(start_year: int) -> str:
    return f"FY {start_year}-{str(start_year + 1)[-2:]}"


def _fy_month_windows(start_year: int) -> list[dict[str, date]]:
    windows = []
    for offset in range(12):
        month = ((FY_START_MONTH + offset - 1) % 12) + 1
        year = start_year if month >= FY_START_MONTH else start_year + 1
        start = date(year, month, 1)
        end = (pd.Timestamp(start) + pd.offsets.MonthEnd(1)).date()
        label = pd.Timestamp(start).strftime("%b")
        windows.append({"label": label, "start": start, "end": end})
    return windows


def _fy_years_from_dates(dates: list[date]) -> list[int]:
    if not dates:
        today = date.today()
        return [_fy_start_year(today)]
    start_year = _fy_start_year(min(dates))
    end_year = _fy_start_year(max(dates))
    return list(range(start_year, end_year + 1))


def _reconciliation_monthly_table(
    data_frame: pd.DataFrame,
    date_col: str,
    metrics: list[tuple[str, str]],
    month_windows: list[dict[str, date]],
    *,
    total_label: str = "FY Total",
) -> pd.DataFrame:
    month_hint = data_frame["Month"] if "Month" in data_frame.columns else None
    dt = utils.parse_date_series(
        data_frame.get(date_col, pd.Series(dtype=str)),
        month_hint=month_hint,
    )
    rows: list[dict[str, float | int | str]] = []
    for window in month_windows:
        mask = (dt >= pd.Timestamp(window["start"])) & (dt <= pd.Timestamp(window["end"]))
        subset = data_frame.loc[mask]
        row: dict[str, float | int | str] = {"Date": window["label"]}
        for column, label in metrics:
            series = utils.to_numeric_series(subset.get(column, pd.Series(dtype=float)))
            row[f"{label} (count)"] = int(series.notna().sum())
            row[f"{label} (sum)"] = float(series.fillna(0.0).sum())
        rows.append(row)

    if month_windows:
        fy_start = month_windows[0]["start"]
        fy_end = month_windows[-1]["end"]
        mask = (dt >= pd.Timestamp(fy_start)) & (dt <= pd.Timestamp(fy_end))
        subset = data_frame.loc[mask]
        total_row: dict[str, float | int | str] = {"Date": total_label}
        for column, label in metrics:
            series = utils.to_numeric_series(subset.get(column, pd.Series(dtype=float)))
            total_row[f"{label} (count)"] = int(series.notna().sum())
            total_row[f"{label} (sum)"] = float(series.fillna(0.0).sum())
        rows.append(total_row)

    columns = ["Date"]
    for _, label in metrics:
        columns.extend([f"{label} (count)", f"{label} (sum)"])
    return pd.DataFrame(rows, columns=columns)


def _reconciliation_raw_material_table(
    raw_frame: pd.DataFrame,
    month_windows: list[dict[str, date]],
    *,
    total_label: str = "FY Total",
) -> pd.DataFrame:
    columns = [
        "Date",
        "Qty_Cement (count)",
        "Qty_Cement (sum)",
        "Qty_FlyAsh (count)",
        "Qty_FlyAsh (sum)",
        "Qty_Stone_Dust (count)",
        "Qty_Stone_Dust (sum)",
        "Total_Cost (sum)",
    ]
    if raw_frame.empty:
        return pd.DataFrame(columns=columns)

    frame = raw_frame.copy()
    frame["Material"] = frame.get("Material", pd.Series(dtype=str)).astype(str).str.strip().apply(
        utils.canonical_material_label
    )
    month_hint = frame["Month"] if "Month" in frame.columns else None
    dt = utils.parse_date_series(
        frame.get("Date", pd.Series(dtype=str)),
        month_hint=month_hint,
    )

    def _material_row(subset: pd.DataFrame, material: str) -> tuple[int, float]:
        material_mask = (
            subset.get("Material", pd.Series(dtype=str))
            .astype(str)
            .str.strip()
            .str.lower()
            == material.lower()
        )
        material_subset = subset.loc[material_mask]
        qty_series = utils.to_numeric_series(
            material_subset.get("Qty", pd.Series(dtype=float))
        )
        count = int(qty_series.notna().sum())
        total = float(qty_series.fillna(0.0).sum())
        return count, total

    rows: list[dict[str, float | int | str]] = []
    for window in month_windows:
        mask = (dt >= pd.Timestamp(window["start"])) & (dt <= pd.Timestamp(window["end"]))
        subset = frame.loc[mask]
        cement_count, cement_sum = _material_row(subset, "Cement")
        flyash_count, flyash_sum = _material_row(subset, "Fly Ash")
        stone_count, stone_sum = _material_row(subset, "Stone Dust")
        cost_sum = float(
            utils.to_numeric_series(subset.get("Total_Cost", pd.Series(dtype=float)))
            .fillna(0.0)
            .sum()
        )
        rows.append(
            {
                "Date": window["label"],
                "Qty_Cement (count)": cement_count,
                "Qty_Cement (sum)": cement_sum,
                "Qty_FlyAsh (count)": flyash_count,
                "Qty_FlyAsh (sum)": flyash_sum,
                "Qty_Stone_Dust (count)": stone_count,
                "Qty_Stone_Dust (sum)": stone_sum,
                "Total_Cost (sum)": cost_sum,
            }
        )

    if month_windows:
        fy_start = month_windows[0]["start"]
        fy_end = month_windows[-1]["end"]
        mask = (dt >= pd.Timestamp(fy_start)) & (dt <= pd.Timestamp(fy_end))
        subset = frame.loc[mask]
        cement_count, cement_sum = _material_row(subset, "Cement")
        flyash_count, flyash_sum = _material_row(subset, "Fly Ash")
        stone_count, stone_sum = _material_row(subset, "Stone Dust")
        cost_sum = float(
            utils.to_numeric_series(subset.get("Total_Cost", pd.Series(dtype=float)))
            .fillna(0.0)
            .sum()
        )
        rows.append(
            {
                "Date": total_label,
                "Qty_Cement (count)": cement_count,
                "Qty_Cement (sum)": cement_sum,
                "Qty_FlyAsh (count)": flyash_count,
                "Qty_FlyAsh (sum)": flyash_sum,
                "Qty_Stone_Dust (count)": stone_count,
                "Qty_Stone_Dust (sum)": stone_sum,
                "Total_Cost (sum)": cost_sum,
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _period_totals(
    data_frame: pd.DataFrame,
    date_col: str,
    value_col: str,
    freq: str,
    label: str,
) -> pd.DataFrame:
    if data_frame.empty or date_col not in data_frame.columns:
        return pd.DataFrame(columns=["Period", "Period_Label", label])
    frame = data_frame.copy()
    dt = pd.to_datetime(frame[date_col], errors="coerce", dayfirst=True)
    frame["Period"] = dt.dt.to_period(freq)
    frame = frame[frame["Period"].notna()]
    frame[label] = utils.to_numeric_series(
        frame.get(value_col, pd.Series(dtype=float))
    ).fillna(0.0)
    grouped = frame.groupby("Period", dropna=False)[label].sum().reset_index()
    grouped = grouped.sort_values("Period")
    grouped["Period_Label"] = grouped["Period"].apply(lambda value: _period_label(value, freq))
    return grouped


def _period_day_counts(
    data_frame: pd.DataFrame,
    date_col: str,
    freq: str,
    label: str,
    *,
    filter_column: str | None = None,
) -> pd.DataFrame:
    if data_frame.empty or date_col not in data_frame.columns:
        return pd.DataFrame(columns=["Period", "Period_Label", label])
    frame = data_frame.copy()
    if filter_column and filter_column in frame.columns:
        values = utils.to_numeric_series(frame.get(filter_column, pd.Series(dtype=float))).fillna(0.0)
        frame = frame[values > 0]
    dt = pd.to_datetime(frame[date_col], errors="coerce", dayfirst=True)
    frame["Period"] = dt.dt.to_period(freq)
    frame = frame[frame["Period"].notna()]
    frame["DateOnly"] = dt.dt.date
    grouped = frame.groupby("Period", dropna=False)["DateOnly"].nunique().reset_index()
    grouped = grouped.rename(columns={"DateOnly": label})
    grouped = grouped.sort_values("Period")
    grouped["Period_Label"] = grouped["Period"].apply(lambda value: _period_label(value, freq))
    return grouped


def _fill_numeric_columns(data_frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    data_frame = data_frame.copy()
    for column in columns:
        if column in data_frame.columns:
            data_frame[column] = utils.to_numeric_series(
                data_frame.get(column, pd.Series(dtype=float))
            ).fillna(0.0)
    return data_frame


def _period_cost_summary(
    raw_frame: pd.DataFrame,
    labour_frame: pd.DataFrame,
    sales_frame: pd.DataFrame,
    freq: str,
) -> pd.DataFrame:
    raw_cost = _period_totals(raw_frame, "Date", "Total_Cost", freq, "Raw_Cost")
    labour_cost = _period_totals(labour_frame, "Date", "Labour_Expense", freq, "Labour_Cost")
    freight_cost = _period_totals(sales_frame, "Date", "Freight", freq, "Freight_Cost")
    summary = raw_cost[["Period", "Period_Label", "Raw_Cost"]].merge(
        labour_cost[["Period", "Labour_Cost"]],
        on="Period",
        how="left",
    ).merge(
        freight_cost[["Period", "Freight_Cost"]],
        on="Period",
        how="left",
    )
    summary = _fill_numeric_columns(summary, ["Raw_Cost", "Labour_Cost", "Freight_Cost"])
    summary["Total_Cost"] = (
        summary["Raw_Cost"] + summary["Labour_Cost"] + summary["Freight_Cost"]
    )
    return summary


def _safe_corr(series_a: pd.Series, series_b: pd.Series) -> float | None:
    if series_a.empty or series_b.empty or len(series_a) < 2:
        return None
    aligned = pd.DataFrame({"a": series_a, "b": series_b}).dropna()
    if len(aligned) < 2:
        return None
    return float(aligned["a"].corr(aligned["b"]))


def _latest_change(summary_df: pd.DataFrame, value_col: str) -> dict | None:
    if summary_df.empty or len(summary_df) < 2:
        return None
    current = summary_df.iloc[-1][value_col]
    previous = summary_df.iloc[-2][value_col]
    diff = current - previous
    pct = (diff / previous * 100) if previous else None
    return {
        "current": current,
        "previous": previous,
        "diff": diff,
        "pct": pct,
        "period": summary_df.iloc[-1]["Period_Label"],
    }


def _format_change(change: dict | None) -> str:
    if not change:
        return "n/a"
    pct = change["pct"]
    pct_str = f"{pct:+.1f}%" if pct is not None else "n/a"
    return f"{change['current']:,.0f} ({pct_str})"


def render() -> None:
    st.header("Dashboard")

    raw_materials = _parse_dates(database.read_table("Raw_Material_Log"), "Date")
    raw_materials = utils.coerce_numeric_columns(
        raw_materials,
        [
            "Qty",
            "Rate",
            "GST",
            "Trip_Days",
            "Route_Expenses",
            "Diesel",
            "Driver_Salary",
            "Vehicle_Charge",
            "Freight",
            "Amount_Paid",
            "Material_Rate",
            "Total_Cost",
        ],
    )
    production = _parse_dates(database.read_table("Production_Log"), "Date")
    production = utils.coerce_numeric_columns(
        production,
        [
            "No_of_Bricks",
            "Cement_Consumption",
            "FlyAsh_Consumption",
            "StoneDust_Consumption",
            "No_of_Labour",
            "Contract_Rate",
            "Labour_Expense",
            "Actual_Payment_Amount",
        ],
    )
    sales = _parse_dates(database.read_table("Sales_Log"), "Date")
    sales = utils.coerce_numeric_columns(
        sales,
        [
            "No_of_Bricks",
            "Rate",
            "GST",
            "Gst (%12)",
            "Amount",
            "Freight",
            "Total_Amount",
            "Amount_Received",
            "Dues",
        ],
    )
    stock_log = _parse_dates(database.read_table("Stock_Log"), "Date")
    stock_log = utils.coerce_numeric_columns(
        stock_log,
        ["Opening", "Inward", "Consumed", "Closing"],
    )
    customers = database.read_table("Customers")

    all_dates = []
    for frame in [raw_materials, production, sales]:
        if not frame.empty and "Date" in frame.columns:
            all_dates.extend([d for d in frame["Date"].dropna().tolist() if isinstance(d, date)])
    min_date = min(all_dates) if all_dates else date.today()
    max_date = max(all_dates) if all_dates else date.today()

    scope_options = [
        "Full data",
        "FY 2023-24",
        "FY 2024-25",
        "FY 2025-26",
        "Last 6 months",
        "Last 3 months",
        "Current month",
    ]
    scope = st.selectbox("Data scope", scope_options, index=0)
    if scope == "Full data":
        start_date, end_date = min_date, max_date
    elif scope.startswith("FY"):
        year_part = int(scope.split()[1].split("-")[0])
        start_date = date(year_part, 4, 1)
        end_date = date(year_part + 1, 3, 31)
    elif scope == "Last 6 months":
        start_date = (pd.Timestamp(max_date) - pd.DateOffset(months=6)).date()
        end_date = max_date
    elif scope == "Last 3 months":
        start_date = (pd.Timestamp(max_date) - pd.DateOffset(months=3)).date()
        end_date = max_date
    else:
        start_date = date(max_date.year, max_date.month, 1)
        end_date = max_date

    period = st.selectbox("Period", ["Monthly", "Quarterly", "Yearly"], index=0)

    if scope == "Full data":
        raw_filtered = raw_materials.copy()
        production_filtered = production.copy()
        sales_filtered = sales.copy()
    else:
        raw_filtered = _filter_by_date(raw_materials, "Date", start_date, end_date)
        production_filtered = _filter_by_date(production, "Date", start_date, end_date)
        sales_filtered = _filter_by_date(sales, "Date", start_date, end_date)

    total_sales = utils.to_numeric_series(
        sales_filtered.get("Amount", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    total_raw_cost = utils.to_numeric_series(
        raw_filtered.get("Total_Cost", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    total_labour = utils.to_numeric_series(
        production_filtered.get("Labour_Expense", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    total_production = utils.to_numeric_series(
        production_filtered.get("No_of_Bricks", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    profit = total_sales - (total_raw_cost + total_labour)
    total_sold_bricks = utils.to_numeric_series(
        sales_filtered.get("No_of_Bricks", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    total_received = utils.to_numeric_series(
        sales_filtered.get("Amount_Received", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    avg_price = (total_sales / total_sold_bricks) if total_sold_bricks else 0.0
    labour_per_1000 = (total_labour / total_production * 1000) if total_production else 0.0
    material_per_1000 = (total_raw_cost / total_production * 1000) if total_production else 0.0
    collection_ratio = (total_received / total_sales) if total_sales else 0.0

    if scope == "Full data":
        sales_month_hint = sales["Month"] if "Month" in sales.columns else None
        prod_month_hint = production["Month"] if "Month" in production.columns else None
        invalid_sales_dates = utils.parse_date_series(
            sales.get("Date", pd.Series(dtype=str)),
            month_hint=sales_month_hint,
        ).isna()
        invalid_prod_dates = utils.parse_date_series(
            production.get("Date", pd.Series(dtype=str)),
            month_hint=prod_month_hint,
        ).isna()
        if invalid_sales_dates.any() or invalid_prod_dates.any():
            st.caption(
                "Full data includes rows with invalid dates. "
                "Time-based charts exclude those rows."
            )

    current_inventory = (
        utils.to_numeric_series(
            production_filtered.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0).sum()
        - utils.to_numeric_series(
            sales_filtered.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0).sum()
    )
    current_inventory = max(current_inventory, 0.0)

    production_entries = len(production_filtered) if not production_filtered.empty else 0
    production_days = (
        production_filtered["Date"].dropna().nunique() if not production_filtered.empty else 0
    )

    row1 = st.columns(5)
    row1[0].metric("Total Production", f"{total_production:,.0f}")
    row1[1].metric("Total Sales", f"{total_sales:,.2f}")
    row1[2].metric("Raw Material Cost", f"{total_raw_cost:,.2f}")
    row1[3].metric("Labour Cost", f"{total_labour:,.2f}")
    row1[4].metric("Profit", f"{profit:,.2f}")

    row2 = st.columns(5)
    row2[0].metric("Available Brick Stock", f"{current_inventory:,.0f}")
    row2[1].metric("Avg Selling Price", f"{avg_price:,.2f}")
    row2[2].metric("Collection Ratio", f"{collection_ratio:,.2f}")
    row2[3].metric("Production Entries", f"{production_entries}")
    row2[4].metric("Production Days", f"{production_days}")

    st.subheader("FY Reconciliation Summary")
    fy_years = _fy_years_from_dates(all_dates)
    fy_labels = [_fy_label(year) for year in fy_years]
    default_year = 2023 if 2023 in fy_years else fy_years[-1]
    default_index = fy_years.index(default_year)
    fy_choice = st.selectbox(
        "Financial year",
        fy_labels,
        index=default_index,
        key="recon_fy",
    )
    fy_start_year = fy_years[fy_labels.index(fy_choice)]
    month_windows = _fy_month_windows(fy_start_year)
    if month_windows:
        st.caption(
            f"{_fy_label(fy_start_year)} period: "
            f"{month_windows[0]['start']:%d %b %Y} - {month_windows[-1]['end']:%d %b %Y}"
        )
    st.caption(
        "Counts show number of records with numeric values. "
        "Totals are sums for each month. Tables use full log data."
    )

    st.markdown("**Sales Log**")
    sales_recon = _reconciliation_monthly_table(
        sales,
        "Date",
        [
            ("No_of_Bricks", "No_of_Bricks"),
            ("Amount", "Amount"),
            ("Amount_Received", "Amount_Received"),
        ],
        month_windows,
    )
    st.dataframe(sales_recon, width="stretch")

    st.markdown("**Production Log**")
    production_recon = _reconciliation_monthly_table(
        production,
        "Date",
        [
            ("No_of_Bricks", "No_of_Bricks"),
            ("Cement_Consumption", "Cement_Consumption"),
            ("No_of_Labour", "No_of_Labour"),
            ("Labour_Expense", "Labour_Expense"),
        ],
        month_windows,
    )
    st.dataframe(production_recon, width="stretch")

    st.markdown("**Raw Material Log**")
    raw_recon = _reconciliation_raw_material_table(raw_materials, month_windows)
    st.dataframe(raw_recon, width="stretch")

    st.subheader("Cost & Profit Summary")
    raw_filtered["Material"] = raw_filtered["Material"].astype(str).str.strip().apply(
        utils.canonical_material_label
    )
    raw_filtered["Material_Rate"] = utils.to_numeric_series(
        raw_filtered.get("Material_Rate", pd.Series(dtype=float))
    ).fillna(0.0)
    raw_filtered["Qty"] = utils.to_numeric_series(
        raw_filtered.get("Qty", pd.Series(dtype=float))
    ).fillna(0.0)

    def _unit_rate(material: str) -> float:
        subset = raw_filtered[
            raw_filtered["Material"].astype(str).str.lower() == material.lower()
        ]
        qty_total = subset["Qty"].sum()
        if qty_total <= 0:
            return 0.0
        material_rate_total = subset["Material_Rate"].sum()
        if material_rate_total <= 0:
            material_rate_total = (subset["Qty"] * subset.get("Rate", 0)).sum()
        return float(material_rate_total / qty_total) if qty_total else 0.0

    cement_used_bags = utils.to_numeric_series(
        production_filtered.get("Cement_Consumption", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    flyash_used_tons = utils.to_numeric_series(
        production_filtered.get("FlyAsh_Consumption", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    stonedust_used_tons = utils.to_numeric_series(
        production_filtered.get("StoneDust_Consumption", pd.Series(dtype=float))
    ).fillna(0.0).sum()

    cement_rate = _unit_rate("Cement")
    flyash_rate = _unit_rate("Fly Ash")
    stonedust_rate = _unit_rate("Stone Dust")
    labour_rate = (total_labour / total_production) if total_production else 0.0
    sales_rate = (total_sales / total_sold_bricks) if total_sold_bricks else 0.0

    summary_rows = [
        {
            "Item": "Cement Used",
            "Quantity": f"{cement_used_bags:,.0f} bags",
            "Rate": f"{cement_rate:,.2f} per bag",
            "Amount (₹)": f"{cement_used_bags * cement_rate:,.0f}",
        },
        {
            "Item": "Fly Ash Used",
            "Quantity": f"{flyash_used_tons:,.3f} tons",
            "Rate": f"{flyash_rate:,.2f} per ton",
            "Amount (₹)": f"{flyash_used_tons * flyash_rate:,.0f}",
        },
        {
            "Item": "Stone Dust Used",
            "Quantity": f"{stonedust_used_tons:,.3f} tons",
            "Rate": f"{stonedust_rate:,.2f} per ton",
            "Amount (₹)": f"{stonedust_used_tons * stonedust_rate:,.0f}",
        },
        {
            "Item": "Labour Cost",
            "Quantity": f"{total_production:,.0f} bricks",
            "Rate": f"{labour_rate:,.2f} per brick",
            "Amount (₹)": f"{total_labour:,.0f}",
        },
        {
            "Item": "Total Production Cost",
            "Quantity": "",
            "Rate": "",
            "Amount (₹)": f"{(total_raw_cost + total_labour):,.0f}",
        },
        {
            "Item": "Sales Value",
            "Quantity": f"{total_sold_bricks:,.0f} bricks",
            "Rate": f"{sales_rate:,.2f} per brick",
            "Amount (₹)": f"{total_sales:,.0f}",
        },
        {
            "Item": "Total Profit",
            "Quantity": "",
            "Rate": "",
            "Amount (₹)": f"{profit:,.0f}",
        },
    ]
    st.dataframe(pd.DataFrame(summary_rows), width="stretch")

    st.subheader("Customer Outstanding and Stock")
    col1, col2 = st.columns(2)
    with col1:
        if customers.empty:
            st.info("No customer data available.")
        else:
            sales_outstanding = sales.copy()
            sales_outstanding["Total_Amount"] = utils.to_numeric_series(
                sales_outstanding.get("Total_Amount", pd.Series(dtype=float))
            ).fillna(0.0)
            sales_outstanding["Amount_Received"] = utils.to_numeric_series(
                sales_outstanding.get("Amount_Received", pd.Series(dtype=float))
            ).fillna(0.0)
            if "Dues" in sales_outstanding.columns:
                sales_outstanding["Outstanding"] = utils.to_numeric_series(
                    sales_outstanding.get("Dues", pd.Series(dtype=float))
                ).fillna(0.0)
            else:
                sales_outstanding["Outstanding"] = (
                    sales_outstanding["Total_Amount"]
                    - sales_outstanding["Amount_Received"]
                )
            outstanding_by_customer = (
                sales_outstanding.groupby("Customer_ID", dropna=False)["Outstanding"]
                .sum()
                .reset_index()
            )
            customer_view = customers[["Customer_ID", "Name"]].copy()
            customer_view = customer_view.merge(
                outstanding_by_customer,
                on="Customer_ID",
                how="left",
            ).fillna(0.0)
            customer_view = customer_view.rename(columns={"Outstanding": "Outstanding_Balance"})
            st.dataframe(customer_view, width="stretch")

    with col2:
        if stock_log.empty:
            st.info("No stock data available.")
        else:
            stock_filtered = _filter_by_date(stock_log, "Date", start_date, end_date).copy()
            stock_filtered["Closing"] = utils.to_numeric_series(
                stock_filtered.get("Closing", pd.Series(dtype=float))
            ).fillna(0.0)
            latest_stock = (
                stock_filtered.sort_values("Date")
                .groupby("Material", as_index=False)
                .tail(1)
                .sort_values("Material")
            )
            st.dataframe(latest_stock, width="stretch")

    if not stock_log.empty:
        stock_chart = (
            alt.Chart(stock_filtered)
            .mark_line(point=True)
            .encode(
                x="Date:T",
                y=alt.Y("Closing:Q", title="Closing Stock"),
                color="Material",
                tooltip=["Date", "Material", "Closing"],
            )
        )
        st.altair_chart(stock_chart, width="stretch")

    # Supplementary metrics and capacity utilization removed per request

    st.subheader("Period Performance")
    if sales_filtered.empty and raw_filtered.empty and production_filtered.empty:
        st.info("No data available for the selected range.")
    else:
        sales_period = _add_period_column(sales_filtered, "Date", period)
        sales_period["Amount"] = utils.to_numeric_series(
            sales_period.get("Amount", pd.Series(dtype=float))
        ).fillna(0.0)
        sales_period["No_of_Bricks"] = utils.to_numeric_series(
            sales_period.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0)
        sales_period["Amount_Received"] = utils.to_numeric_series(
            sales_period.get("Amount_Received", pd.Series(dtype=float))
        ).fillna(0.0)

        raw_period = _add_period_column(raw_filtered, "Date", period)
        raw_period["Total_Cost"] = utils.to_numeric_series(
            raw_period.get("Total_Cost", pd.Series(dtype=float))
        ).fillna(0.0)

        labour_period = _add_period_column(production_filtered, "Date", period)
        labour_period["Labour_Expense"] = utils.to_numeric_series(
            labour_period.get("Labour_Expense", pd.Series(dtype=float))
        ).fillna(0.0)
        labour_period["No_of_Bricks"] = utils.to_numeric_series(
            labour_period.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0)
        labour_period["No_of_Labour"] = utils.to_numeric_series(
            labour_period.get("No_of_Labour", pd.Series(dtype=float))
        ).fillna(0.0)
        labour_period["Date"] = pd.to_datetime(
            labour_period.get("Date", pd.Series(dtype=str)),
            errors="coerce",
            dayfirst=True,
        ).dt.date

        sales_summary = (
            sales_period.groupby("Period", dropna=False)["Amount"]
            .sum()
            .reset_index()
            .rename(columns={"Amount": "Sales"})
        )
        prod_summary = (
            labour_period.groupby("Period", dropna=False)["No_of_Bricks"]
            .sum()
            .reset_index()
            .rename(columns={"No_of_Bricks": "Production"})
        )
        raw_summary = (
            raw_period.groupby("Period", dropna=False)["Total_Cost"]
            .sum()
            .reset_index()
            .rename(columns={"Total_Cost": "Raw_Material_Cost"})
        )
        labour_summary = (
            labour_period.groupby("Period", dropna=False)["Labour_Expense"]
            .sum()
            .reset_index()
            .rename(columns={"Labour_Expense": "Labour_Cost"})
        )

        summary = (
            sales_summary.merge(prod_summary, on="Period", how="outer")
            .merge(raw_summary, on="Period", how="outer")
            .merge(labour_summary, on="Period", how="outer")
        )
        summary = summary.fillna(0)
        summary["Total_Cost"] = summary["Raw_Material_Cost"] + summary["Labour_Cost"]
        summary["Avg_Price"] = summary.apply(
            lambda row: (row["Sales"] / row["Production"]) if row["Production"] else 0.0,
            axis=1,
        )

        st.subheader("Sales vs Production")
        base = alt.Chart(summary).encode(x="Period:O")
        sales_line = base.mark_line(point=True).encode(
            y=alt.Y("Sales:Q", title="Sales Amount"),
            tooltip=["Period", "Sales", "Production"],
        )
        production_bar = base.mark_bar(opacity=0.3).encode(
            y=alt.Y("Production:Q", title="Production (Bricks)"),
        )
        st.altair_chart(
            alt.layer(sales_line, production_bar).resolve_scale(y="independent"),
            width="stretch",
        )

        st.subheader("Cost Breakdown")
        cost_melt = summary.melt(
            id_vars=["Period"],
            value_vars=["Raw_Material_Cost", "Labour_Cost"],
            var_name="Cost_Type",
            value_name="Amount",
        )
        cost_chart = (
            alt.Chart(cost_melt)
            .mark_bar()
            .encode(
                x="Period:O",
                y="Amount:Q",
                color="Cost_Type",
                tooltip=["Period", "Cost_Type", "Amount"],
            )
        )
        st.altair_chart(cost_chart, width="stretch")

        st.subheader("Average Selling Price Trend")
        avg_price_chart = (
            alt.Chart(summary)
            .mark_line(point=True)
            .encode(
                x="Period:O",
                y=alt.Y("Avg_Price:Q", title="Avg Price"),
                tooltip=["Period", "Avg_Price"],
            )
        )
        st.altair_chart(avg_price_chart, width="stretch")

        st.subheader("Collection Performance")
        collection_summary = (
            sales_period.groupby("Period", dropna=False)[["Amount", "Amount_Received"]]
            .sum()
            .reset_index()
            .rename(columns={"Amount": "Sales", "Amount_Received": "Collected"})
        )
        collection_melt = collection_summary.melt(
            id_vars=["Period"],
            value_vars=["Sales", "Collected"],
            var_name="Metric",
            value_name="Amount",
        )
        collection_chart = (
            alt.Chart(collection_melt)
            .mark_bar()
            .encode(
                x="Period:O",
                y="Amount:Q",
                color="Metric",
                tooltip=["Period", "Metric", "Amount"],
            )
        )
        st.altair_chart(collection_chart, width="stretch")

        st.subheader("Labour Productivity")
        productivity = (
            labour_period.groupby("Period", dropna=False)[["No_of_Bricks", "No_of_Labour"]]
            .sum()
            .reset_index()
        )
        productivity["Bricks_per_Labour"] = productivity.apply(
            lambda row: (row["No_of_Bricks"] / row["No_of_Labour"]) if row["No_of_Labour"] else 0.0,
            axis=1,
        )
        productivity_chart = (
            alt.Chart(productivity)
            .mark_line(point=True)
            .encode(
                x="Period:O",
                y=alt.Y("Bricks_per_Labour:Q", title="Bricks per Labour"),
                tooltip=["Period", "Bricks_per_Labour"],
            )
        )
        st.altair_chart(productivity_chart, width="stretch")

        st.subheader("Material Consumption per 1000 Bricks")
        consumption_period = _add_period_column(production_filtered, "Date", period)
        consumption_period["Cement_Consumption"] = utils.to_numeric_series(
            consumption_period.get("Cement_Consumption", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption_period["FlyAsh_Consumption"] = utils.to_numeric_series(
            consumption_period.get("FlyAsh_Consumption", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption_period["StoneDust_Consumption"] = utils.to_numeric_series(
            consumption_period.get("StoneDust_Consumption", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption_period["No_of_Bricks"] = utils.to_numeric_series(
            consumption_period.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption_period["Cement_Consumption_bags"] = consumption_period["Cement_Consumption"]
        consumption_period["FlyAsh_Consumption_tons"] = consumption_period["FlyAsh_Consumption"]
        consumption_period["StoneDust_Consumption_tons"] = consumption_period["StoneDust_Consumption"]
        consumption_summary = (
            consumption_period.groupby("Period", dropna=False)[
                [
                    "Cement_Consumption_bags",
                    "FlyAsh_Consumption_tons",
                    "StoneDust_Consumption_tons",
                    "No_of_Bricks",
                ]
            ]
            .sum()
            .reset_index()
        )
        consumption_summary["Cement_bags_per_1000"] = consumption_summary.apply(
            lambda row: (
                row["Cement_Consumption_bags"] / row["No_of_Bricks"] * 1000
                if row["No_of_Bricks"]
                else 0.0
            ),
            axis=1,
        )
        consumption_summary["FlyAsh_tons_per_1000"] = consumption_summary.apply(
            lambda row: (
                row["FlyAsh_Consumption_tons"] / row["No_of_Bricks"] * 1000
                if row["No_of_Bricks"]
                else 0.0
            ),
            axis=1,
        )
        consumption_summary["StoneDust_tons_per_1000"] = consumption_summary.apply(
            lambda row: (
                row["StoneDust_Consumption_tons"] / row["No_of_Bricks"] * 1000
                if row["No_of_Bricks"]
                else 0.0
            ),
            axis=1,
        )
        consumption_melt = consumption_summary.melt(
            id_vars=["Period"],
            value_vars=["Cement_bags_per_1000", "FlyAsh_tons_per_1000", "StoneDust_tons_per_1000"],
            var_name="Material",
            value_name="Per_1000",
        )
        consumption_melt["Material"] = consumption_melt["Material"].map(
            {
                "Cement_bags_per_1000": "Cement (bags)",
                "FlyAsh_tons_per_1000": "Fly Ash (tons)",
                "StoneDust_tons_per_1000": "Stone Dust (tons)",
            }
        )
        consumption_chart = (
            alt.Chart(consumption_melt)
            .mark_line(point=True)
            .encode(
                x="Period:O",
                y=alt.Y("Per_1000:Q", title="Consumption per 1000 Bricks"),
                color="Material",
                tooltip=["Period", "Material", "Per_1000"],
            )
        )
        st.altair_chart(consumption_chart, width="stretch")

        st.subheader("Transport Cost per 1000 Bricks")
        sales_period["Freight"] = utils.to_numeric_series(
            sales_period.get("Freight", pd.Series(dtype=float))
        ).fillna(0.0)
        freight_summary = (
            sales_period.groupby("Period", dropna=False)[["Freight", "No_of_Bricks"]]
            .sum()
            .reset_index()
        )
        freight_summary["Freight_per_1000"] = freight_summary.apply(
            lambda row: (row["Freight"] / row["No_of_Bricks"] * 1000)
            if row["No_of_Bricks"]
            else 0.0,
            axis=1,
        )
        freight_chart = (
            alt.Chart(freight_summary)
            .mark_line(point=True)
            .encode(
                x="Period:O",
                y=alt.Y("Freight_per_1000:Q", title="Freight per 1000 Bricks"),
                tooltip=["Period", "Freight_per_1000"],
            )
        )
        st.altair_chart(freight_chart, width="stretch")

        # Capacity utilization trend removed per request.

    st.subheader("Production Efficiency")
    if production_filtered.empty:
        st.info("No production data available.")
    else:
        efficiency = production_filtered.copy()
        bricks = utils.to_numeric_series(
            efficiency.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0)
        labour = utils.to_numeric_series(
            efficiency.get("No_of_Labour", pd.Series(dtype=float))
        )
        efficiency["Efficiency"] = bricks.div(labour.replace(0, pd.NA))
        efficiency_chart = (
            alt.Chart(efficiency)
            .mark_bar()
            .encode(
                x="Date:T",
                y="Efficiency:Q",
                tooltip=["Date", "No_of_Bricks", "No_of_Labour", "Efficiency"],
            )
        )
        st.altair_chart(efficiency_chart, width="stretch")

    st.subheader("Material Consumption vs Output")
    if production_filtered.empty:
        st.info("No production data available.")
    else:
        consumption = production_filtered.copy()
        consumption = consumption.rename(
            columns={
                "Cement_Consumption": "Cement",
                "FlyAsh_Consumption": "Fly Ash",
                "StoneDust_Consumption": "Stone Dust",
            }
        )
        consumption["Cement"] = utils.to_numeric_series(
            consumption.get("Cement", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption["Fly Ash"] = utils.to_numeric_series(
            consumption.get("Fly Ash", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption["Stone Dust"] = utils.to_numeric_series(
            consumption.get("Stone Dust", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption["No_of_Bricks"] = utils.to_numeric_series(
            consumption.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0)
        melt = consumption.melt(
            id_vars=["Date", "No_of_Bricks"],
            value_vars=["Cement", "Fly Ash", "Stone Dust"],
            var_name="Material",
            value_name="Quantity",
        )
        melt["Material"] = melt["Material"].map(
            {
                "Cement": "Cement (bags)",
                "Fly Ash": "Fly Ash (tons)",
                "Stone Dust": "Stone Dust (tons)",
            }
        )
        line = (
            alt.Chart(melt)
            .mark_line(point=True)
            .encode(
                x="Date:T",
                y=alt.Y("Quantity:Q", title="Consumption (bags / tons)"),
                color="Material",
                tooltip=["Date", "Material", "Quantity"],
            )
        )
        bricks = (
            alt.Chart(consumption)
            .mark_bar(opacity=0.3)
            .encode(x="Date:T", y="No_of_Bricks:Q", tooltip=["Date", "No_of_Bricks"])
        )
        st.altair_chart((line + bricks).resolve_scale(y="independent"), width="stretch")

    st.subheader("Insights & Recommendations")
    prod_month = _period_totals(production_filtered, "Date", "No_of_Bricks", "M", "Production")
    sales_month = _period_totals(sales_filtered, "Date", "No_of_Bricks", "M", "Sales")
    prod_quarter = _period_totals(production_filtered, "Date", "No_of_Bricks", "Q", "Production")
    sales_quarter = _period_totals(sales_filtered, "Date", "No_of_Bricks", "Q", "Sales")
    prod_year = _period_totals(production_filtered, "Date", "No_of_Bricks", "Y", "Production")
    sales_year = _period_totals(sales_filtered, "Date", "No_of_Bricks", "Y", "Sales")

    monthly_summary = prod_month[["Period", "Period_Label", "Production"]].merge(
        sales_month[["Period", "Sales"]],
        on="Period",
        how="outer",
    ).fillna(0.0)
    monthly_summary["Period_Label"] = monthly_summary["Period"].apply(
        lambda value: _period_label(value, "M")
    )
    monthly_summary["Gap"] = monthly_summary["Production"] - monthly_summary["Sales"]
    monthly_summary["Conversion"] = monthly_summary["Sales"].div(
        monthly_summary["Production"].replace(0, pd.NA)
    )

    material_series = raw_filtered.get("Material", pd.Series(dtype=str)).astype(str).str.strip()
    raw_types = {"Cement", "Fly Ash", "Stone Dust", "Sand"}
    transport_types = {"Transport", "Diesel"}
    maintenance_types = {"Maintenance"}
    raw_cost = raw_filtered.loc[material_series.isin(raw_types), "Total_Cost"].sum()
    transport_cost = raw_filtered.loc[material_series.isin(transport_types), "Total_Cost"].sum()
    maintenance_cost = raw_filtered.loc[material_series.isin(maintenance_types), "Total_Cost"].sum()
    other_cost = raw_filtered.loc[
        ~material_series.isin(raw_types | transport_types | maintenance_types),
        "Total_Cost",
    ].sum()
    freight_cost = utils.to_numeric_series(
        sales_filtered.get("Freight", pd.Series(dtype=float))
    ).fillna(0.0).sum()
    cost_rows = [
        ("Raw materials", raw_cost),
        ("Labour", total_labour),
        ("Freight (sales)", freight_cost),
        ("Transport & Diesel", transport_cost),
        ("Maintenance", maintenance_cost),
        ("Other/Unclassified", other_cost),
    ]
    total_cost = sum(value for _, value in cost_rows)
    raw_cost_month = _period_totals(raw_filtered, "Date", "Total_Cost", "M", "Raw_Cost")
    labour_cost_month = _period_totals(
        production_filtered,
        "Date",
        "Labour_Expense",
        "M",
        "Labour_Cost",
    )
    freight_cost_month = _period_totals(sales_filtered, "Date", "Freight", "M", "Freight_Cost")
    cost_month = prod_month[["Period", "Period_Label", "Production"]].merge(
        raw_cost_month[["Period", "Raw_Cost"]],
        on="Period",
        how="left",
    ).merge(
        labour_cost_month[["Period", "Labour_Cost"]],
        on="Period",
        how="left",
    ).merge(
        freight_cost_month[["Period", "Freight_Cost"]],
        on="Period",
        how="left",
    ).fillna(0.0)
    cost_month["Total_Cost"] = (
        cost_month["Raw_Cost"] + cost_month["Labour_Cost"] + cost_month["Freight_Cost"]
    )
    cost_month["Cost_per_Brick"] = cost_month["Total_Cost"].div(
        cost_month["Production"].replace(0, pd.NA)
    )

    if prod_month.empty and sales_month.empty:
        st.info("Add production and sales data to generate insights.")
    else:
        prod_sales_tab, best_tab, material_tab, cost_tab, anomaly_tab, days_tab, kpi_tab = st.tabs(
            [
                "Production vs Sales",
                "Best & Worst Months",
                "Materials & Procurement",
                "Cost Optimization",
                "Data Anomalies",
                "Days & Profitability",
                "KPIs & Recommendations",
            ]
        )

        with prod_sales_tab:
            st.markdown("**Trend comparisons (latest period):**")
            trend_rows = []
            for label, prod_df, sales_df in [
                ("Year-over-Year", prod_year, sales_year),
                ("Quarter-over-Quarter", prod_quarter, sales_quarter),
                ("Month-over-Month", prod_month, sales_month),
            ]:
                prod_change = _latest_change(prod_df, "Production")
                sales_change = _latest_change(sales_df, "Sales")
                gap = None
                if not prod_df.empty and not sales_df.empty:
                    gap = prod_df.iloc[-1]["Production"] - sales_df.iloc[-1]["Sales"]
                trend_rows.append(
                    {
                        "Trend": label,
                        "Production": _format_change(prod_change),
                        "Sales": _format_change(sales_change),
                        "Gap (Bricks)": f"{gap:,.0f}" if gap is not None else "n/a",
                    }
                )
            st.dataframe(pd.DataFrame(trend_rows), width="stretch")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Months where production exceeded sales**")
                over = monthly_summary.sort_values("Gap", ascending=False).head(3)
                st.dataframe(
                    over[["Period_Label", "Production", "Sales", "Gap"]],
                    width="stretch",
                )
            with col2:
                st.markdown("**Months where sales exceeded production**")
                under = monthly_summary.sort_values("Gap").head(3)
                st.dataframe(
                    under[["Period_Label", "Production", "Sales", "Gap"]],
                    width="stretch",
                )

            if not monthly_summary.empty and monthly_summary["Conversion"].notna().any():
                latest_conversion = monthly_summary["Conversion"].dropna().iloc[-1]
                avg_conversion = monthly_summary["Conversion"].dropna().tail(3).mean()
                st.caption(
                    f"Latest conversion ratio: {latest_conversion:.2f} | "
                    f"Last 3-month avg: {avg_conversion:.2f}"
                )

        with best_tab:
            def _best_worst(frame: pd.DataFrame, column: str) -> tuple[pd.Series, pd.Series] | None:
                series = frame[column].dropna()
                if series.empty:
                    return None
                return frame.loc[series.idxmax()], frame.loc[series.idxmin()]

            rows = []
            for label, column, fmt in [
                ("Production (bricks)", "Production", "{:,.0f}"),
                ("Sales (bricks)", "Sales", "{:,.0f}"),
                ("Conversion ratio", "Conversion", "{:.2f}"),
            ]:
                result = _best_worst(monthly_summary, column)
                if not result:
                    continue
                best, worst = result
                rows.append(
                    {
                        "Metric": label,
                        "Best Month": best["Period_Label"],
                        "Best Value": fmt.format(best[column]),
                        "Worst Month": worst["Period_Label"],
                        "Worst Value": fmt.format(worst[column]),
                    }
                )
            if rows:
                st.dataframe(pd.DataFrame(rows), width="stretch")
            else:
                st.info("Not enough monthly data to identify best/worst months.")

        with material_tab:
            consumption = production_filtered.copy()
            if consumption.empty:
                st.info("No production data available for material insights.")
            else:
                consumption["Period"] = pd.to_datetime(
                    consumption.get("Date", pd.Series(dtype=str)),
                    errors="coerce",
                    dayfirst=True,
                ).dt.to_period("M")
                material_cols = {
                    "Cement_Consumption": "Cement",
                    "FlyAsh_Consumption": "Fly Ash",
                    "StoneDust_Consumption": "Stone Dust",
                }
                for col in material_cols:
                    consumption[col] = utils.to_numeric_series(
                        consumption.get(col, pd.Series(dtype=float))
                    ).fillna(0.0)
                consumption["No_of_Bricks"] = utils.to_numeric_series(
                    consumption.get("No_of_Bricks", pd.Series(dtype=float))
                ).fillna(0.0)
                monthly_material = (
                    consumption.groupby("Period", dropna=False)[list(material_cols.keys()) + ["No_of_Bricks"]]
                    .sum()
                    .reset_index()
                    .sort_values("Period")
                )
                monthly_material["Period_Label"] = monthly_material["Period"].apply(
                    lambda value: _period_label(value, "M")
                )
                totals = {
                    material_cols[key]: float(monthly_material[key].sum())
                    for key in material_cols
                    if key in monthly_material.columns
                }
                if totals:
                    top_material = max(totals, key=totals.get)
                    st.metric("Most used material", top_material, f"{totals[top_material]:,.2f}")

                def _top_months(frame: pd.DataFrame, column: str) -> list[str]:
                    if frame.empty or column not in frame.columns:
                        return []
                    top = frame.sort_values(column, ascending=False).head(3)
                    return [value for value in top["Period_Label"].tolist() if value]

                procurement_rows = []
                for col, label in material_cols.items():
                    peaks = _top_months(monthly_material, col)
                    procurement_rows.append(
                        {
                            "Material": label,
                            "Peak Months": ", ".join(peaks) if peaks else "n/a",
                            "Procure Before": ", ".join(peaks) if peaks else "n/a",
                        }
                    )
                st.markdown("**Procurement calendar (based on peak usage)**")
                st.dataframe(pd.DataFrame(procurement_rows), width="stretch")

                recent_months = monthly_material.tail(3)
                if not recent_months.empty and recent_months["No_of_Bricks"].sum() > 0:
                    avg_production = recent_months["No_of_Bricks"].mean()
                    forecast_rows = []
                    for col, label in material_cols.items():
                        ratio = recent_months[col].sum() / recent_months["No_of_Bricks"].sum()
                        forecast_rows.append(
                            {
                                "Material": label,
                                "Avg per brick": f"{ratio:.4f}",
                                "Next-month need (est.)": f"{ratio * avg_production:,.2f}",
                            }
                        )
                    st.markdown("**Next-month material requirement (simple forecast)**")
                    st.dataframe(pd.DataFrame(forecast_rows), width="stretch")

                st.markdown("**Reconciliation snapshot (tons + kg/brick)**")
                standard = {
                    "Cement": 0.20 / 50,
                    "Fly Ash": 1.70 / 1000,
                    "Stone Dust": 1.45 / 1000,
                }

                cement_used_bags = utils.to_numeric_series(
                    production_filtered.get("Cement_Consumption", pd.Series(dtype=float))
                ).fillna(0.0).sum()
                flyash_used_ton = utils.to_numeric_series(
                    production_filtered.get("FlyAsh_Consumption", pd.Series(dtype=float))
                ).fillna(0.0).sum()
                stonedust_used_ton = utils.to_numeric_series(
                    production_filtered.get("StoneDust_Consumption", pd.Series(dtype=float))
                ).fillna(0.0).sum()
                bricks_produced = utils.to_numeric_series(
                    production_filtered.get("No_of_Bricks", pd.Series(dtype=float))
                ).fillna(0.0).sum()

                cement_used_kg = cement_used_bags * 50
                cement_used_ton = cement_used_kg / 1000
                flyash_used_kg = flyash_used_ton * 1000
                stonedust_used_kg = stonedust_used_ton * 1000

                raw_filtered["Material"] = raw_filtered["Material"].astype(str).str.strip().apply(
                    utils.canonical_material_label
                )
                cement_purchased_bags = raw_filtered.loc[
                    raw_filtered["Material"].astype(str).str.lower() == "cement",
                    "Qty",
                ].sum()
                cement_purchased_ton = (cement_purchased_bags * 50) / 1000
                flyash_purchased_ton = raw_filtered.loc[
                    raw_filtered["Material"].astype(str).str.lower() == "fly ash",
                    "Qty",
                ].sum()
                stonedust_purchased_ton = raw_filtered.loc[
                    raw_filtered["Material"].astype(str).str.lower() == "stone dust",
                    "Qty",
                ].sum()

                stock_rows = []
                variance_flags = {}
                for material, used_value, purchased_ton, used_ton in [
                    ("Cement", cement_used_bags, cement_purchased_ton, cement_used_ton),
                    ("Fly Ash", flyash_used_ton, flyash_purchased_ton, flyash_used_ton),
                    ("Stone Dust", stonedust_used_ton, stonedust_purchased_ton, stonedust_used_ton),
                ]:
                    per_brick = used_value / bricks_produced if bricks_produced else 0.0
                    variance_pct = (
                        (per_brick - standard[material]) / standard[material]
                        if bricks_produced and standard.get(material, 0)
                        else None
                    )
                    variance_flags[material] = variance_pct
                    stock_rows.append(
                        {
                            "Material": material,
                            "Stock_Ton": round(purchased_ton - used_ton, 2),
                            "Per_Brick": round(per_brick, 4),
                            "Variance_%": f"{variance_pct:.1%}" if variance_pct is not None else "n/a",
                        }
                    )
                stock_df = pd.DataFrame(stock_rows)
                stock_df["Unit"] = stock_df["Material"].map(
                    {
                        "Cement": "bags/brick",
                        "Fly Ash": "tons/brick",
                        "Stone Dust": "tons/brick",
                    }
                )
                st.dataframe(stock_df, width="stretch")

                alerts = []
                for row in stock_rows:
                    if row["Stock_Ton"] < 0:
                        alerts.append(f"{row['Material']}: negative stock")
                for material, variance_pct in variance_flags.items():
                    if variance_pct is not None and variance_pct > 0.10:
                        alerts.append(f"{material}: high usage variance")
                if alerts:
                    st.caption("Alerts: " + ", ".join(alerts))

        with cost_tab:
            cost_table = pd.DataFrame(
                [
                    {
                        "Cost Type": label,
                        "Amount": value,
                        "Share": f"{(value / total_cost * 100):.1f}%" if total_cost else "n/a",
                    }
                    for label, value in cost_rows
                ]
            )
            st.dataframe(cost_table, width="stretch")

            top_cost = cost_month.sort_values("Cost_per_Brick", ascending=False).head(3)
            st.markdown("**Highest cost per brick (monthly)**")
            st.dataframe(
                top_cost[["Period_Label", "Cost_per_Brick", "Total_Cost"]],
                width="stretch",
            )

        with anomaly_tab:
            anomalies: list[dict[str, str]] = []

            if not stock_log.empty:
                negative_stock = stock_log.loc[stock_log["Closing"] < 0]
                if not negative_stock.empty:
                    sample = negative_stock.head(3)
                    for _, row in sample.iterrows():
                        anomalies.append(
                            {
                                "Type": "Negative stock",
                                "Period": str(row.get("Date", "")),
                                "Finding": f"{row.get('Material', '')} closing {row.get('Closing', 0)}",
                                "Likely cause": "Missing inward entries or over-reported consumption.",
                                "Corrective action": "Verify stock log vs receipts; add missing inward entries.",
                                "Preventive measure": "Weekly stock reconciliation and inward checks.",
                            }
                        )

            if not monthly_summary.empty:
                sales_over_prod = monthly_summary[monthly_summary["Sales"] > monthly_summary["Production"]]
                if not sales_over_prod.empty:
                    for _, row in sales_over_prod.head(3).iterrows():
                        anomalies.append(
                            {
                                "Type": "Sales > Production",
                                "Period": row.get("Period_Label", ""),
                                "Finding": "Sales exceeded production",
                                "Likely cause": "Old inventory cleared or production missing.",
                                "Corrective action": "Confirm opening stock and adjust production log.",
                                "Preventive measure": "Track opening/closing finished goods stock monthly.",
                            }
                        )

                sales_spike = monthly_summary.copy()
                sales_spike["Sales_Change"] = sales_spike["Sales"].pct_change()
                sales_spike["Prod_Change"] = sales_spike["Production"].pct_change()
                spike_rows = sales_spike[
                    (sales_spike["Sales_Change"] > 0.3) & (sales_spike["Prod_Change"] < 0.1)
                ]
                for _, row in spike_rows.head(3).iterrows():
                    anomalies.append(
                        {
                            "Type": "Sales spike without production",
                            "Period": row.get("Period_Label", ""),
                            "Finding": f"Sales up {row.get('Sales_Change', 0):.0%} while production flat",
                            "Likely cause": "Inventory clearance or delayed sales posting.",
                            "Corrective action": "Check inventory dispatch log vs production days.",
                            "Preventive measure": "Weekly sales-production reconciliation.",
                        }
                    )

            if not production_filtered.empty:
                usage = production_filtered.copy()
                usage["Period"] = pd.to_datetime(
                    usage.get("Date", pd.Series(dtype=str)),
                    errors="coerce",
                    dayfirst=True,
                ).dt.to_period("M")
                usage["No_of_Bricks"] = utils.to_numeric_series(
                    usage.get("No_of_Bricks", pd.Series(dtype=float))
                ).fillna(0.0)
                usage["Material_Total"] = (
                    utils.to_numeric_series(usage.get("Cement_Consumption", pd.Series(dtype=float))).fillna(0.0)
                    + utils.to_numeric_series(usage.get("FlyAsh_Consumption", pd.Series(dtype=float))).fillna(0.0)
                    + utils.to_numeric_series(usage.get("StoneDust_Consumption", pd.Series(dtype=float))).fillna(0.0)
                )
                usage_summary = (
                    usage.groupby("Period", dropna=False)[["No_of_Bricks", "Material_Total"]]
                    .sum()
                    .reset_index()
                    .sort_values("Period")
                )
                usage_summary["Material_per_1000"] = usage_summary["Material_Total"].div(
                    usage_summary["No_of_Bricks"].replace(0, pd.NA)
                ) * 1000
                usage_summary["Prod_Change"] = usage_summary["No_of_Bricks"].pct_change().abs()
                usage_summary["Mat_Change"] = usage_summary["Material_per_1000"].pct_change().abs()
                mismatch = usage_summary[
                    (usage_summary["Prod_Change"] < 0.1) & (usage_summary["Mat_Change"] > 0.2)
                ]
                for _, row in mismatch.head(3).iterrows():
                    anomalies.append(
                        {
                            "Type": "Material usage mismatch",
                            "Period": _period_label(row.get("Period"), "M"),
                            "Finding": "Similar production, different material usage",
                            "Likely cause": "Wastage, mix changes, or entry errors.",
                            "Corrective action": "Check mix ratios and validate consumption entries.",
                            "Preventive measure": "Standardize batching logs per shift.",
                        }
                    )

            if not cost_month.empty:
                threshold = cost_month["Cost_per_Brick"].quantile(0.9)
                cost_spike = cost_month[cost_month["Cost_per_Brick"] > threshold]
                for _, row in cost_spike.head(3).iterrows():
                    anomalies.append(
                        {
                            "Type": "Cost spike",
                            "Period": row.get("Period_Label", ""),
                            "Finding": f"Cost per brick {row.get('Cost_per_Brick', 0):.2f}",
                            "Likely cause": "Higher input prices or lower output.",
                            "Corrective action": "Review procurement prices and downtime logs.",
                            "Preventive measure": "Lock rates before peak season, track idle time.",
                        }
                    )

            if anomalies:
                st.dataframe(pd.DataFrame(anomalies), width="stretch")
            else:
                st.info("No major anomalies detected in the selected range.")

        with days_tab:
            prod_days_m = _period_day_counts(
                production_filtered,
                "Date",
                "M",
                "Production_Days",
                filter_column="No_of_Bricks",
            )
            sales_days_m = _period_day_counts(
                sales_filtered,
                "Date",
                "M",
                "Sales_Days",
                filter_column="No_of_Bricks",
            )
            prod_days_q = _period_day_counts(
                production_filtered,
                "Date",
                "Q",
                "Production_Days",
                filter_column="No_of_Bricks",
            )
            sales_days_q = _period_day_counts(
                sales_filtered,
                "Date",
                "Q",
                "Sales_Days",
                filter_column="No_of_Bricks",
            )
            prod_days_y = _period_day_counts(
                production_filtered,
                "Date",
                "Y",
                "Production_Days",
                filter_column="No_of_Bricks",
            )
            sales_days_y = _period_day_counts(
                sales_filtered,
                "Date",
                "Y",
                "Sales_Days",
                filter_column="No_of_Bricks",
            )

            st.markdown("**Production vs Sales days (monthly)**")
            days_month = prod_days_m[["Period", "Period_Label", "Production_Days"]].merge(
                sales_days_m[["Period", "Sales_Days"]],
                on="Period",
                how="outer",
            )
            days_month = _fill_numeric_columns(days_month, ["Production_Days", "Sales_Days"])
            days_month["Period_Label"] = days_month["Period"].apply(
                lambda value: _period_label(value, "M")
            )
            days_month["Days_Ratio"] = days_month["Production_Days"].div(
                days_month["Sales_Days"].replace(0, pd.NA)
            )
            st.dataframe(
                days_month[["Period_Label", "Production_Days", "Sales_Days", "Days_Ratio"]],
                width="stretch",
            )

            st.markdown("**Quarterly production vs sales days**")
            days_quarter = prod_days_q[["Period", "Period_Label", "Production_Days"]].merge(
                sales_days_q[["Period", "Sales_Days"]],
                on="Period",
                how="outer",
            )
            days_quarter = _fill_numeric_columns(days_quarter, ["Production_Days", "Sales_Days"])
            days_quarter["Period_Label"] = days_quarter["Period"].apply(
                lambda value: _period_label(value, "Q")
            )
            days_quarter["Days_Ratio"] = days_quarter["Production_Days"].div(
                days_quarter["Sales_Days"].replace(0, pd.NA)
            )
            st.dataframe(
                days_quarter[["Period_Label", "Production_Days", "Sales_Days", "Days_Ratio"]],
                width="stretch",
            )

            st.markdown("**Yearly production vs sales days**")
            days_year = prod_days_y[["Period", "Period_Label", "Production_Days"]].merge(
                sales_days_y[["Period", "Sales_Days"]],
                on="Period",
                how="outer",
            )
            days_year = _fill_numeric_columns(days_year, ["Production_Days", "Sales_Days"])
            days_year["Period_Label"] = days_year["Period"].apply(
                lambda value: _period_label(value, "Y")
            )
            days_year["Days_Ratio"] = days_year["Production_Days"].div(
                days_year["Sales_Days"].replace(0, pd.NA)
            )
            st.dataframe(
                days_year[["Period_Label", "Production_Days", "Sales_Days", "Days_Ratio"]],
                width="stretch",
            )

            days_month = days_month.merge(
                monthly_summary[["Period", "Production", "Sales"]],
                on="Period",
                how="left",
            )
            days_month = _fill_numeric_columns(days_month, ["Production", "Sales"])
            prod_output_corr = _safe_corr(
                days_month["Production_Days"],
                days_month["Production"],
            )
            sales_output_corr = _safe_corr(
                days_month["Sales_Days"],
                days_month["Sales"],
            )
            day_corr = _safe_corr(days_month["Production_Days"], days_month["Sales_Days"])

            st.markdown("**Correlation insights (monthly)**")
            st.write(
                {
                    "Production days vs output": f"{prod_output_corr:.2f}" if prod_output_corr is not None else "n/a",
                    "Sales days vs sales": f"{sales_output_corr:.2f}" if sales_output_corr is not None else "n/a",
                    "Production days vs sales days": f"{day_corr:.2f}" if day_corr is not None else "n/a",
                }
            )

            low_threshold = days_month["Production_Days"].quantile(0.2) if not days_month.empty else None
            high_threshold = days_month["Production_Days"].quantile(0.8) if not days_month.empty else None
            if low_threshold is not None and high_threshold is not None:
                low_prod = days_month[days_month["Production_Days"] <= low_threshold].head(3)
                high_prod = days_month[days_month["Production_Days"] >= high_threshold].head(3)
                st.markdown("**Production days outliers**")
                st.dataframe(
                    pd.concat(
                        [
                            low_prod.assign(Flag="Low"),
                            high_prod.assign(Flag="High"),
                        ],
                        ignore_index=True,
                    )[["Period_Label", "Production_Days", "Flag"]],
                    width="stretch",
                )

            low_sales_threshold = days_month["Sales_Days"].quantile(0.2) if not days_month.empty else None
            high_sales_threshold = days_month["Sales_Days"].quantile(0.8) if not days_month.empty else None
            if low_sales_threshold is not None and high_sales_threshold is not None:
                low_sales = days_month[days_month["Sales_Days"] <= low_sales_threshold].head(3)
                high_sales = days_month[days_month["Sales_Days"] >= high_sales_threshold].head(3)
                st.markdown("**Sales days outliers**")
                st.dataframe(
                    pd.concat(
                        [
                            low_sales.assign(Flag="Low"),
                            high_sales.assign(Flag="High"),
                        ],
                        ignore_index=True,
                    )[["Period_Label", "Sales_Days", "Flag"]],
                    width="stretch",
                )

            st.markdown("**Profitability trends**")
            cost_month_summary = _period_cost_summary(raw_filtered, production_filtered, sales_filtered, "M")
            sales_amount_month = _period_totals(
                sales_filtered,
                "Date",
                "Amount",
                "M",
                "Sales_Amount",
            )
            profit_month = cost_month_summary.merge(
                sales_amount_month[["Period", "Sales_Amount"]],
                on="Period",
                how="left",
            ).fillna(0.0)
            prod_bricks_month = _period_totals(production_filtered, "Date", "No_of_Bricks", "M", "Prod_Bricks")
            profit_month = profit_month.merge(
                prod_bricks_month[["Period", "Prod_Bricks"]],
                on="Period",
                how="left",
            ).fillna(0.0)
            profit_month["Profit"] = profit_month["Sales_Amount"] - profit_month["Total_Cost"]
            profit_month["Profit_Margin"] = profit_month["Profit"].div(
                profit_month["Sales_Amount"].replace(0, pd.NA)
            )
            profit_month["Profit_per_Brick"] = profit_month["Profit"].div(
                profit_month["Prod_Bricks"].replace(0, pd.NA)
            )
            profit_month["Period_Label"] = profit_month["Period"].apply(lambda value: _period_label(value, "M"))

            st.dataframe(
                profit_month[
                    [
                        "Period_Label",
                        "Sales_Amount",
                        "Total_Cost",
                        "Profit",
                        "Profit_Margin",
                        "Profit_per_Brick",
                    ]
                ],
                width="stretch",
            )

            profit_month["Cost_Change"] = profit_month["Total_Cost"].diff()
            profit_month["Profit_Change"] = profit_month["Profit"].diff()
            mismatch = profit_month[
                (profit_month["Cost_Change"] > 0) & (profit_month["Profit_Change"] <= 0)
            ]
            if not mismatch.empty:
                st.markdown("**Cost increased but profit did not**")
                st.dataframe(
                    mismatch[["Period_Label", "Cost_Change", "Profit_Change"]],
                    width="stretch",
                )
            else:
                st.caption("No periods where cost rose while profit fell.")

            st.markdown("**Recommendation on production vs sales days**")
            if prod_output_corr is not None and prod_output_corr < 0.3:
                st.write("- Production days are not translating into output. Review downtime and shift utilization.")
            elif prod_output_corr is not None:
                st.write("- Increasing production days likely increases output. Plan extra shifts before peak demand.")
            if sales_output_corr is not None and sales_output_corr < 0.3:
                st.write("- Sales days are not translating into revenue. Improve lead tracking or customer follow-ups.")
            elif sales_output_corr is not None:
                st.write("- Additional sales days are likely to improve revenue. Expand sales coverage in peak months.")

        with kpi_tab:
            kpi_rows = []
            total_labour_days = utils.to_numeric_series(
                production_filtered.get("No_of_Labour", pd.Series(dtype=float))
            ).fillna(0.0).sum()
            bricks_per_labour = (
                total_production / total_labour_days if total_labour_days else 0.0
            )
            cost_per_brick = total_cost / total_production if total_production else 0.0
            avg_price_per_brick = (
                total_sales / total_sold_bricks if total_sold_bricks else 0.0
            )
            margin_per_brick = avg_price_per_brick - cost_per_brick
            kpi_rows.extend(
                [
                    {"KPI": "Bricks per labour-day", "Value": f"{bricks_per_labour:,.2f}"},
                    {"KPI": "Cost per brick", "Value": f"{cost_per_brick:,.2f}"},
                    {"KPI": "Avg selling price per brick", "Value": f"{avg_price_per_brick:,.2f}"},
                    {"KPI": "Margin per brick", "Value": f"{margin_per_brick:,.2f}"},
                    {"KPI": "Collection ratio", "Value": f"{collection_ratio:,.2f}"},
                ]
            )
            st.dataframe(pd.DataFrame(kpi_rows), width="stretch")

            conversion_ratio = (
                total_sold_bricks / total_production if total_production else None
            )
            profit = total_sales - total_cost
            profit_margin = (profit / total_sales) if total_sales else None
            labour_cost_share = (total_labour / total_cost) if total_cost else None
            raw_cost_share = (total_raw_cost / total_cost) if total_cost else None

            def _status(value: float | None, low: float, high: float) -> str:
                if value is None or pd.isna(value):
                    return "n/a"
                if value < low:
                    return "Low"
                if value > high:
                    return "High"
                return "Normal"

            def _format_value(value: float | None, fmt: str) -> str:
                if value is None or pd.isna(value):
                    return "n/a"
                return fmt.format(value)

            kpi_specs = [
                {
                    "name": "Production to sales ratio",
                    "value": conversion_ratio,
                    "low": 0.9,
                    "high": 1.1,
                    "format": "{:.2f}",
                    "definition": "Sales bricks divided by production bricks.",
                    "range": "0.90 - 1.10",
                    "why": "Shows if output matches demand and inventory levels.",
                    "meaning": {
                        "Low": "Production is ahead of sales; inventory is building.",
                        "Normal": "Production and sales are balanced.",
                        "High": "Sales exceed production; risk of stockouts or missing logs.",
                    },
                    "improve": {
                        "Low": "Slow production, increase sales focus, or clear inventory.",
                        "High": "Increase production days or verify production logging.",
                        "Normal": "Maintain balance with monthly review.",
                    },
                },
                {
                    "name": "Collection ratio",
                    "value": collection_ratio,
                    "low": 0.95,
                    "high": 1.0,
                    "format": "{:.2f}",
                    "definition": "Amount received divided by total sales.",
                    "range": "0.95 - 1.00",
                    "why": "Tracks cash recovery and receivables health.",
                    "meaning": {
                        "Low": "Receivables are high; cash flow risk.",
                        "Normal": "Collections are healthy.",
                        "High": "Collections exceed sales; check adjustments.",
                    },
                    "improve": {
                        "Low": "Tighten credit limits and follow-up schedule.",
                        "High": "Verify entries and reconcile receipts.",
                        "Normal": "Maintain collection discipline.",
                    },
                },
                {
                    "name": "Profit margin",
                    "value": profit_margin,
                    "low": 0.1,
                    "high": 0.25,
                    "format": "{:.1%}",
                    "definition": "Profit divided by total sales.",
                    "range": "10% - 25%",
                    "why": "Shows overall profitability after costs.",
                    "meaning": {
                        "Low": "Costs or pricing reduce profitability.",
                        "Normal": "Profitability is within target range.",
                        "High": "Strong margin; verify costing accuracy.",
                    },
                    "improve": {
                        "Low": "Negotiate raw material rates and reduce wastage.",
                        "High": "Recheck cost capture and maintain pricing discipline.",
                        "Normal": "Sustain process control and pricing.",
                    },
                },
                {
                    "name": "Labour cost share",
                    "value": labour_cost_share,
                    "low": 0.15,
                    "high": 0.35,
                    "format": "{:.1%}",
                    "definition": "Labour cost divided by total cost.",
                    "range": "15% - 35%",
                    "why": "Indicates labour efficiency and staffing balance.",
                    "meaning": {
                        "Low": "Labour costs are low or under-reported.",
                        "Normal": "Labour cost share is balanced.",
                        "High": "Labour cost is heavy; efficiency may be low.",
                    },
                    "improve": {
                        "Low": "Validate labour entries and attendance.",
                        "High": "Optimize shifts and reduce idle time.",
                        "Normal": "Keep tracking attendance and output per worker.",
                    },
                },
                {
                    "name": "Raw material cost share",
                    "value": raw_cost_share,
                    "low": 0.5,
                    "high": 0.7,
                    "format": "{:.1%}",
                    "definition": "Raw material cost divided by total cost.",
                    "range": "50% - 70%",
                    "why": "Shows procurement impact on total cost.",
                    "meaning": {
                        "Low": "Raw material share is low; check if costs are missing.",
                        "Normal": "Raw material cost share is expected.",
                        "High": "Raw materials dominate; pricing or wastage issues.",
                    },
                    "improve": {
                        "Low": "Verify raw material entries and pricing.",
                        "High": "Negotiate rates and reduce material wastage.",
                        "Normal": "Lock rates before peak months.",
                    },
                },
                {
                    "name": "Bricks per labour-day",
                    "value": bricks_per_labour,
                    "low": 800,
                    "high": 2000,
                    "format": "{:,.0f}",
                    "definition": "Total bricks divided by total labour-days.",
                    "range": "800 - 2000",
                    "why": "Indicates labour productivity.",
                    "meaning": {
                        "Low": "Productivity is low; labour under-utilized.",
                        "Normal": "Productivity is within target range.",
                        "High": "High productivity; check quality and fatigue.",
                    },
                    "improve": {
                        "Low": "Align staffing to demand and improve workflow.",
                        "High": "Sustain output while monitoring quality.",
                        "Normal": "Maintain training and batching discipline.",
                    },
                },
            ]

            diagnostic_rows = []
            for kpi in kpi_specs:
                status = _status(kpi["value"], kpi["low"], kpi["high"])
                diagnostic_rows.append(
                    {
                        "KPI": kpi["name"],
                        "Value": _format_value(kpi["value"], kpi["format"]),
                        "Ideal Range": kpi["range"],
                        "Status": status,
                        "What it means": kpi["meaning"].get(status, "n/a"),
                        "How to improve": kpi["improve"].get(status, "n/a"),
                    }
                )
            st.markdown("**Diagnostic KPI report**")
            st.dataframe(pd.DataFrame(diagnostic_rows), width="stretch")

            kpi_dictionary = [
                {
                    "KPI": kpi["name"],
                    "Definition": kpi["definition"],
                    "Ideal Range": kpi["range"],
                    "Why it matters": kpi["why"],
                }
                for kpi in kpi_specs
            ]
            st.markdown("**KPI dictionary**")
            st.dataframe(pd.DataFrame(kpi_dictionary), width="stretch")

            recommendations: list[str] = []
            if not prod_month.empty and not sales_month.empty:
                latest_ratio = (
                    monthly_summary["Conversion"].dropna().iloc[-1]
                    if monthly_summary["Conversion"].notna().any()
                    else None
                )
                if latest_ratio is not None and latest_ratio < 0.9:
                    recommendations.append(
                        "Sales are lagging production in the latest month. Slow production or boost sales to reduce inventory."
                    )
                elif latest_ratio is not None and latest_ratio > 1.1:
                    recommendations.append(
                        "Sales are ahead of production. Consider increasing output or securing inventory buffers."
                    )
            if total_cost and raw_cost / total_cost > 0.6:
                recommendations.append(
                    "Raw materials are the largest cost driver. Negotiate supplier rates and lock pricing ahead of peak months."
                )
            if labour_per_1000 > 0:
                recommendations.append(
                    f"Labour cost per 1000 bricks is {labour_per_1000:,.2f}. Monitor labour allocation and reduce idle time."
                )
            if not recommendations:
                recommendations.append(
                    "Maintain consistent production planning and review raw material wastage monthly."
                )
            st.markdown("**Actionable recommendations**")
            st.markdown("\n".join([f"- {item}" for item in recommendations]))
            st.markdown("**Additional KPIs to track**")
            st.markdown(
                "\n".join(
                    [
                        "- Customer repeat rate and average order size",
                        "- Finished goods aging (days of inventory)",
                        "- Raw material lead time and stockout rate",
                        "- Machine downtime (hours) and on-time order fulfillment",
                        "- Working capital cycle (receivables + inventory - payables days)",
                    ]
                )
            )

    st.subheader("Dashboard Diagnostics")
    with st.expander("Data quality checks", expanded=False):
        max_rows = st.slider("Rows to preview", min_value=5, max_value=100, value=20, step=5)
        invalid_records: list[dict[str, str]] = []

        def _preview(sample: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
            if sample.empty:
                return sample
            cleaned = sample.copy()
            cleaned = cleaned.where(pd.notnull(cleaned), "")
            cleaned = cleaned.astype(str)
            cleaned.insert(0, "Row_No", cleaned.index.to_series().add(2).astype(int))
            cols = ["Row_No"] + [col for col in columns if col in cleaned.columns]
            return cleaned[cols]

        def _record_issues(
            sheet: str,
            frame: pd.DataFrame,
            mask: pd.Series,
            column: str,
            issue: str,
        ) -> None:
            if not mask.any():
                return
            rows = frame.loc[mask, [column]].copy()
            rows.insert(0, "Row_No", rows.index.to_series().add(2).astype(int))
            for _, row in rows.iterrows():
                invalid_records.append(
                    {
                        "Sheet": sheet,
                        "Issue": issue,
                        "Column": column,
                        "Row_No": str(row["Row_No"]),
                        "Value": str(row[column]),
                    }
                )

        def _quality_block(label: str, frame: pd.DataFrame, date_col: str, numeric_cols: list[str]) -> None:
            st.markdown(f"**{label}**")
            if frame.empty:
                st.write("No rows.")
                return
            month_hint = frame["Month"] if "Month" in frame.columns else None
            date_series = utils.parse_date_series(
                frame.get(date_col, pd.Series(dtype=str)),
                month_hint=month_hint,
            )
            raw_dates = frame.get(date_col, pd.Series(dtype=str)).astype(str).str.strip()
            invalid_date = date_series.isna() & (raw_dates != "")
            st.write(
                {
                    "rows": len(frame),
                    "invalid_dates": int(invalid_date.sum()),
                }
            )
            if invalid_date.any():
                st.dataframe(
                    _preview(frame[invalid_date].head(max_rows), [date_col]),
                    width="stretch",
                )
                _record_issues(label, frame, invalid_date, date_col, "Invalid Date")
            for column in numeric_cols:
                numeric = utils.to_numeric_series(frame.get(column, pd.Series(dtype=str)))
                raw_values = frame.get(column, pd.Series(dtype=str)).astype(str).str.strip()
                invalid_num = numeric.isna() & (raw_values != "")
                st.write(
                    {
                        "column": column,
                        "invalid_numbers": int(invalid_num.sum()),
                    }
                )
                if invalid_num.any():
                    st.dataframe(
                        _preview(frame[invalid_num].head(max_rows), [column]),
                        width="stretch",
                    )
                    _record_issues(label, frame, invalid_num, column, "Invalid Number")

        st.markdown("**Fix checklist**")
        st.markdown(
            "\n".join(
                [
                    "- Ensure Date columns are valid (YYYY-MM-DD recommended).",
                    "- Remove extra spaces or text in numeric fields.",
                    "- Re-check rows listed above and update in Google Sheets.",
                ]
            )
        )

        _quality_block(
            "Production Log",
            production,
            "Date",
            ["No_of_Bricks", "Labour_Expense", "No_of_Labour"],
        )
        _quality_block(
            "Sales Log",
            sales,
            "Date",
            [
                "Amount",
                "Amount_Received",
                "Total_Amount",
                "No_of_Bricks",
                "GST",
                "Gst (%12)",
                "Dues",
            ],
        )
        _quality_block(
            "Raw Material Log",
            raw_materials,
            "Date",
            ["Total_Cost", "Qty", "Rate"],
        )

        if invalid_records:
            st.download_button(
                "Download invalid rows (CSV)",
                data=pd.DataFrame(invalid_records).to_csv(index=False),
                file_name="dashboard_invalid_rows.csv",
                mime="text/csv",
            )
