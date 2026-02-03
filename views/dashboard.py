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
    data_frame[column] = pd.to_datetime(
        data_frame[column],
        errors="coerce",
        dayfirst=True,
    ).dt.date
    return data_frame


def _filter_by_date(data_frame: pd.DataFrame, column: str, start: date, end: date) -> pd.DataFrame:
    if column not in data_frame.columns:
        return data_frame
    series = pd.to_datetime(data_frame[column], errors="coerce", dayfirst=True)
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
            "Amount",
            "Freight",
            "Total_Amount",
            "Amount_Received",
            "Due",
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

    date_range = st.date_input("Date Range", value=(min_date, max_date))
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = min_date
        end_date = max_date

    period = st.selectbox("Period", ["Monthly", "Quarterly", "Yearly"], index=0)
    with st.expander("Benchmarks", expanded=False):
        daily_capacity = st.number_input(
            "Daily Capacity (bricks)",
            min_value=0,
            step=1000,
            value=0,
        )

    raw_filtered = _filter_by_date(raw_materials, "Date", start_date, end_date)
    production_filtered = _filter_by_date(production, "Date", start_date, end_date)
    sales_filtered = _filter_by_date(sales, "Date", start_date, end_date)

    total_sales = utils.to_numeric_series(
        sales_filtered.get("Total_Amount", pd.Series(dtype=float))
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

    metric1, metric2, metric3, metric4, metric5 = st.columns(5)
    metric1.metric("Total Production", f"{total_production:,.0f}")
    metric2.metric("Total Sales", f"{total_sales:,.2f}")
    metric3.metric("Raw Material Cost", f"{total_raw_cost:,.2f}")
    metric4.metric("Labour Cost", f"{total_labour:,.2f}")
    metric5.metric("Profit", f"{profit:,.2f}")

    metric6, metric7, metric8, metric9 = st.columns(4)
    avg_price = (total_sales / total_sold_bricks) if total_sold_bricks else 0.0
    labour_per_1000 = (total_labour / total_production * 1000) if total_production else 0.0
    material_per_1000 = (total_raw_cost / total_production * 1000) if total_production else 0.0
    collection_ratio = (total_received / total_sales * 100) if total_sales else 0.0
    metric6.metric("Avg Selling Price", f"{avg_price:,.2f}")
    metric7.metric("Labour/1000 Bricks", f"{labour_per_1000:,.2f}")
    metric8.metric("Material/1000 Bricks", f"{material_per_1000:,.2f}")
    metric9.metric("Collection Ratio", f"{collection_ratio:,.1f}%")

    production_days = (
        production_filtered["Date"].dropna().nunique() if not production_filtered.empty else 0
    )
    total_capacity = production_days * daily_capacity if daily_capacity else 0
    capacity_utilization = (
        (total_production / total_capacity * 100) if total_capacity else 0.0
    )
    metric10, metric11 = st.columns(2)
    metric10.metric("Production Days", f"{production_days}")
    if daily_capacity:
        metric11.metric("Capacity Utilization", f"{capacity_utilization:,.1f}%")
    else:
        metric11.metric("Capacity Utilization", "Set capacity")

    st.subheader("Period Performance")
    if sales_filtered.empty and raw_filtered.empty and production_filtered.empty:
        st.info("No data available for the selected range.")
    else:
        sales_period = _add_period_column(sales_filtered, "Date", period)
        sales_period["Total_Amount"] = utils.to_numeric_series(
            sales_period.get("Total_Amount", pd.Series(dtype=float))
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
            sales_period.groupby("Period", dropna=False)["Total_Amount"]
            .sum()
            .reset_index()
            .rename(columns={"Total_Amount": "Sales"})
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
            sales_period.groupby("Period", dropna=False)[["Total_Amount", "Amount_Received"]]
            .sum()
            .reset_index()
            .rename(columns={"Total_Amount": "Sales", "Amount_Received": "Collected"})
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
        consumption_summary = (
            consumption_period.groupby("Period", dropna=False)[
                ["Cement_Consumption", "FlyAsh_Consumption", "StoneDust_Consumption", "No_of_Bricks"]
            ]
            .sum()
            .reset_index()
        )
        consumption_summary["Cement_per_1000"] = consumption_summary.apply(
            lambda row: (
                row["Cement_Consumption"] / row["No_of_Bricks"] * 1000
                if row["No_of_Bricks"]
                else 0.0
            ),
            axis=1,
        )
        consumption_summary["FlyAsh_per_1000"] = consumption_summary.apply(
            lambda row: (
                row["FlyAsh_Consumption"] / row["No_of_Bricks"] * 1000
                if row["No_of_Bricks"]
                else 0.0
            ),
            axis=1,
        )
        consumption_summary["StoneDust_per_1000"] = consumption_summary.apply(
            lambda row: (
                row["StoneDust_Consumption"] / row["No_of_Bricks"] * 1000
                if row["No_of_Bricks"]
                else 0.0
            ),
            axis=1,
        )
        consumption_melt = consumption_summary.melt(
            id_vars=["Period"],
            value_vars=["Cement_per_1000", "FlyAsh_per_1000", "StoneDust_per_1000"],
            var_name="Material",
            value_name="Per_1000",
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

        if daily_capacity and not labour_period.empty:
            st.subheader("Capacity Utilization Trend")
            capacity_days = (
                labour_period.groupby("Period", dropna=False)["Date"]
                .nunique()
                .reset_index()
                .rename(columns={"Date": "Production_Days"})
            )
            capacity_summary = prod_summary.merge(capacity_days, on="Period", how="left").fillna(0)
            capacity_summary["Capacity"] = capacity_summary["Production_Days"] * daily_capacity
            capacity_summary["Utilization"] = capacity_summary.apply(
                lambda row: (row["Production"] / row["Capacity"] * 100) if row["Capacity"] else 0.0,
                axis=1,
            )
            cap_base = alt.Chart(capacity_summary).encode(x="Period:O")
            cap_chart = alt.layer(
                cap_base.mark_bar(opacity=0.3).encode(
                    y=alt.Y("Production:Q", title="Bricks"),
                    tooltip=["Period", "Production", "Capacity"],
                ),
                cap_base.mark_line(point=True, color="orange").encode(
                    y=alt.Y("Capacity:Q", title="Capacity"),
                ),
            ).resolve_scale(y="independent")
            st.altair_chart(cap_chart, width="stretch")

            util_chart = (
                alt.Chart(capacity_summary)
                .mark_line(point=True)
                .encode(
                    x="Period:O",
                    y=alt.Y("Utilization:Q", title="Utilization %"),
                    tooltip=["Period", "Utilization"],
                )
            )
            st.altair_chart(util_chart, width="stretch")

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
        line = (
            alt.Chart(melt)
            .mark_line(point=True)
            .encode(
                x="Date:T",
                y="Quantity:Q",
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
        prod_sales_tab, best_tab, material_tab, cost_tab, anomaly_tab, kpi_tab = st.tabs(
            [
                "Production vs Sales",
                "Best & Worst Months",
                "Materials & Procurement",
                "Cost Optimization",
                "Data Anomalies",
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
                    {"KPI": "Collection ratio", "Value": f"{collection_ratio:,.1f}%"},
                ]
            )
            st.dataframe(pd.DataFrame(kpi_rows), width="stretch")

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

    st.subheader("Customer Outstanding and Stock")
    col1, col2 = st.columns(2)
    with col1:
        if not customers.empty:
            customer_view = customers[["Customer_ID", "Name", "Outstanding_Balance"]].copy()
            st.dataframe(customer_view, width="stretch")
        else:
            st.info("No customer data available.")

    with col2:
        if stock_log.empty:
            st.info("No stock data available.")
        else:
            stock_filtered = _filter_by_date(stock_log, "Date", start_date, end_date)
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

    st.subheader("Dashboard Diagnostics")
    with st.expander("Data quality checks", expanded=False):
        def _quality_block(label: str, frame: pd.DataFrame, date_col: str, numeric_cols: list[str]) -> None:
            st.markdown(f"**{label}**")
            if frame.empty:
                st.write("No rows.")
                return
            def _preview(sample: pd.DataFrame) -> pd.DataFrame:
                cleaned = sample.copy()
                cleaned = cleaned.where(pd.notnull(cleaned), "")
                return cleaned.astype(str)
            date_series = pd.to_datetime(frame.get(date_col, pd.Series(dtype=str)), errors="coerce", dayfirst=True)
            invalid_date = date_series.isna()
            st.write(
                {
                    "rows": len(frame),
                    "invalid_dates": int(invalid_date.sum()),
                }
            )
            if invalid_date.any():
                st.dataframe(_preview(frame[invalid_date].head(5)), width="stretch")
            for column in numeric_cols:
                numeric = utils.to_numeric_series(frame.get(column, pd.Series(dtype=str)))
                invalid_num = numeric.isna()
                st.write(
                    {
                        "column": column,
                        "invalid_numbers": int(invalid_num.sum()),
                    }
                )
                if invalid_num.any():
                    st.dataframe(_preview(frame[invalid_num].head(5)), width="stretch")

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
            ["Total_Amount", "Amount_Received", "No_of_Bricks"],
        )
        _quality_block(
            "Raw Material Log",
            raw_materials,
            "Date",
            ["Total_Cost", "Qty", "Rate"],
        )
