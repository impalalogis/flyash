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

    supplier_filter = st.multiselect(
        "Supplier",
        sorted(
            raw_materials.get("Supplier_ID", pd.Series(dtype=str))
            .dropna()
            .unique()
            .tolist()
        ),
    )
    material_filter = st.multiselect(
        "Material",
        sorted(raw_materials.get("Material", pd.Series(dtype=str)).dropna().unique().tolist()),
    )
    customer_filter = st.multiselect(
        "Customer",
        sorted(sales.get("Customer_ID", pd.Series(dtype=str)).dropna().unique().tolist()),
    )

    raw_filtered = _filter_by_date(raw_materials, "Date", start_date, end_date)
    if supplier_filter:
        raw_filtered = raw_filtered[raw_filtered["Supplier_ID"].isin(supplier_filter)]
    if material_filter:
        raw_filtered = raw_filtered[raw_filtered["Material"].isin(material_filter)]

    production_filtered = _filter_by_date(production, "Date", start_date, end_date)
    sales_filtered = _filter_by_date(sales, "Date", start_date, end_date)
    if customer_filter:
        sales_filtered = sales_filtered[sales_filtered["Customer_ID"].isin(customer_filter)]

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

    metric1, metric2, metric3, metric4, metric5 = st.columns(5)
    metric1.metric("Total Production", f"{total_production:,.0f}")
    metric2.metric("Total Sales", f"{total_sales:,.2f}")
    metric3.metric("Raw Material Cost", f"{total_raw_cost:,.2f}")
    metric4.metric("Labour Cost", f"{total_labour:,.2f}")
    metric5.metric("Profit", f"{profit:,.2f}")

    st.subheader("Monthly Revenue vs Cost")
    if sales_filtered.empty and raw_filtered.empty and production_filtered.empty:
        st.info("No data available for the selected range.")
    else:
        sales_month = sales_filtered.copy()
        if "Month" not in sales_month.columns:
            sales_month["Month"] = sales_month["Date"].apply(
                lambda value: utils.to_month_string(value) if pd.notnull(value) else ""
            )
        sales_month["Total_Amount"] = pd.to_numeric(
            sales_month.get("Total_Amount", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)
        cost_month = raw_filtered.copy()
        if "Month" not in cost_month.columns:
            cost_month["Month"] = cost_month["Date"].apply(
                lambda value: utils.to_month_string(value) if pd.notnull(value) else ""
            )
        cost_month["Total_Cost"] = pd.to_numeric(
            cost_month.get("Total_Cost", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)
        labour_month = production_filtered.copy()
        if "Month" not in labour_month.columns:
            labour_month["Month"] = labour_month["Date"].apply(
                lambda value: utils.to_month_string(value) if pd.notnull(value) else ""
            )
        labour_month["Labour_Expense"] = pd.to_numeric(
            labour_month.get("Labour_Expense", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)

        sales_summary = (
            sales_month.groupby("Month", dropna=False)["Total_Amount"]
            .sum()
            .reset_index()
            .rename(columns={"Total_Amount": "Sales"})
        )
        raw_summary = (
            cost_month.groupby("Month", dropna=False)["Total_Cost"]
            .sum()
            .reset_index()
            .rename(columns={"Total_Cost": "Raw_Material_Cost"})
        )
        labour_summary = (
            labour_month.groupby("Month", dropna=False)["Labour_Expense"]
            .sum()
            .reset_index()
            .rename(columns={"Labour_Expense": "Labour_Cost"})
        )

        summary = sales_summary.merge(raw_summary, on="Month", how="outer").merge(
            labour_summary, on="Month", how="outer"
        )
        summary = summary.fillna(0)
        summary["Total_Cost"] = summary["Raw_Material_Cost"] + summary["Labour_Cost"]

        chart_data = summary.melt(
            id_vars=["Month"],
            value_vars=["Sales", "Total_Cost"],
            var_name="Metric",
            value_name="Amount",
        )
        chart = (
            alt.Chart(chart_data)
            .mark_line(point=True)
            .encode(
                x="Month",
                y="Amount:Q",
                color="Metric",
                tooltip=["Month", "Metric", "Amount"],
            )
        )
        st.altair_chart(chart, use_container_width=True)

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

    st.subheader("Outstanding Aging Report")
    if sales_filtered.empty:
        st.info("No sales data available.")
    else:
        aging = sales_filtered.copy()
        aging["Date"] = pd.to_datetime(aging["Date"], errors="coerce")
        aging["Due"] = pd.to_numeric(
            aging.get("Due", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0)
        aging["Age_Days"] = (pd.Timestamp.today() - aging["Date"]).dt.days

        bins = [-1, 30, 60, 90, 10000]
        labels = ["0-30", "31-60", "61-90", "90+"]
        aging["Bucket"] = pd.cut(aging["Age_Days"], bins=bins, labels=labels)
        aging_summary = aging.groupby("Bucket")["Due"].sum().reset_index()
        st.dataframe(aging_summary, use_container_width=True)

    if not customers.empty:
        st.subheader("Customer Outstanding Balances")
        customer_view = customers[["Customer_ID", "Name", "Outstanding_Balance"]].copy()
        st.dataframe(customer_view, use_container_width=True)

    st.subheader("Stock by Material")
    if stock_log.empty:
        st.info("No stock data available.")
        return

    stock_filtered = _filter_by_date(stock_log, "Date", start_date, end_date)
    if material_filter:
        stock_filtered = stock_filtered[stock_filtered["Material"].isin(material_filter)]

    latest_stock = (
        stock_filtered.sort_values("Date")
        .groupby("Material", as_index=False)
        .tail(1)
        .sort_values("Material")
    )
    st.dataframe(latest_stock, use_container_width=True)
