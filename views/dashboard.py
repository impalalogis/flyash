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
    data_frame[column] = pd.to_datetime(data_frame[column], errors="coerce").dt.date
    return data_frame


def _filter_by_date(data_frame: pd.DataFrame, column: str, start: date, end: date) -> pd.DataFrame:
    if column not in data_frame.columns:
        return data_frame
    series = pd.to_datetime(data_frame[column], errors="coerce")
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)
    return data_frame[(series >= start_ts) & (series <= end_ts)]


def _add_period_column(data_frame: pd.DataFrame, column: str, period: str) -> pd.DataFrame:
    if column not in data_frame.columns:
        return data_frame
    freq = {"Monthly": "M", "Quarterly": "Q", "Yearly": "Y"}[period]
    data_frame = data_frame.copy()
    dt = pd.to_datetime(data_frame[column], errors="coerce")
    data_frame["Period"] = dt.dt.to_period(freq).astype(str)
    data_frame = data_frame[data_frame["Period"] != "NaT"]
    return data_frame


def render() -> None:
    st.header("Dashboard")

    raw_materials = _parse_dates(database.read_table("Raw_Material_Log"), "Date")
    production = _parse_dates(database.read_table("Production_Log"), "Date")
    sales = _parse_dates(database.read_table("Sales_Log"), "Date")
    stock_log = _parse_dates(database.read_table("Stock_Log"), "Date")
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

    raw_filtered = _filter_by_date(raw_materials, "Date", start_date, end_date)
    production_filtered = _filter_by_date(production, "Date", start_date, end_date)
    sales_filtered = _filter_by_date(sales, "Date", start_date, end_date)

    total_sales = pd.to_numeric(
        sales_filtered.get("Total_Amount", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    total_raw_cost = pd.to_numeric(
        raw_filtered.get("Total_Cost", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    total_labour = pd.to_numeric(
        production_filtered.get("Labour_Expense", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    total_production = pd.to_numeric(
        production_filtered.get("No_of_Bricks", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    profit = total_sales - (total_raw_cost + total_labour)
    total_sold_bricks = pd.to_numeric(
        sales_filtered.get("No_of_Bricks", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    total_received = pd.to_numeric(
        sales_filtered.get("Amount_Received", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()

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

    st.subheader("Monthly Revenue vs Cost")
    if sales_filtered.empty and raw_filtered.empty and production_filtered.empty:
        st.info("No data available for the selected range.")
    else:
        sales_period = _add_period_column(sales_filtered, "Date", period)
        sales_period["Total_Amount"] = pd.to_numeric(
            sales_period.get("Total_Amount", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)
        sales_period["No_of_Bricks"] = pd.to_numeric(
            sales_period.get("No_of_Bricks", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)
        sales_period["Amount_Received"] = pd.to_numeric(
            sales_period.get("Amount_Received", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)

        raw_period = _add_period_column(raw_filtered, "Date", period)
        raw_period["Total_Cost"] = pd.to_numeric(
            raw_period.get("Total_Cost", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)

        labour_period = _add_period_column(production_filtered, "Date", period)
        labour_period["Labour_Expense"] = pd.to_numeric(
            labour_period.get("Labour_Expense", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)
        labour_period["No_of_Bricks"] = pd.to_numeric(
            labour_period.get("No_of_Bricks", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)

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
            use_container_width=True,
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
        st.altair_chart(cost_chart, use_container_width=True)

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
        st.altair_chart(avg_price_chart, use_container_width=True)

    st.subheader("Production Efficiency")
    if production_filtered.empty:
        st.info("No production data available.")
    else:
        efficiency = production_filtered.copy()
        efficiency["Efficiency"] = (
            pd.to_numeric(efficiency.get("No_of_Bricks", pd.Series(dtype=float)), errors="coerce")
            / pd.to_numeric(efficiency.get("No_of_Labour", pd.Series(dtype=float)), errors="coerce")
        )
        efficiency_chart = (
            alt.Chart(efficiency)
            .mark_bar()
            .encode(
                x="Date:T",
                y="Efficiency:Q",
                tooltip=["Date", "No_of_Bricks", "No_of_Labour", "Efficiency"],
            )
        )
        st.altair_chart(efficiency_chart, use_container_width=True)

    st.subheader("Material Consumption vs Output")
    if production_filtered.empty:
        st.info("No production data available.")
    else:
        consumption = production_filtered.copy()
        consumption = consumption.rename(
            columns={
                "Cement_Consumption": "Cement",
                "FlyAsh_Consumption": "Fly Ash",
            }
        )
        consumption["No_of_Bricks"] = pd.to_numeric(
            consumption.get("No_of_Bricks", pd.Series(dtype=float)), errors="coerce"
        )
        melt = consumption.melt(
            id_vars=["Date", "No_of_Bricks"],
            value_vars=["Cement", "Fly Ash"],
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
        st.altair_chart((line + bricks).resolve_scale(y="independent"), use_container_width=True)

    if not customers.empty:
        st.subheader("Customer Outstanding Balances")
        customer_view = customers[["Customer_ID", "Name", "Outstanding_Balance"]].copy()
        st.dataframe(customer_view, use_container_width=True)

    st.subheader("Stock by Material")
    if stock_log.empty:
        st.info("No stock data available.")
        return

    stock_filtered = _filter_by_date(stock_log, "Date", start_date, end_date)
    stock_filtered["Closing"] = pd.to_numeric(
        stock_filtered.get("Closing", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0.0)

    latest_stock = (
        stock_filtered.sort_values("Date")
        .groupby("Material", as_index=False)
        .tail(1)
        .sort_values("Material")
    )
    st.dataframe(latest_stock, use_container_width=True)

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
    st.altair_chart(stock_chart, use_container_width=True)
