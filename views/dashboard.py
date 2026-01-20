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
        st.altair_chart(collection_chart, use_container_width=True)

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
        st.altair_chart(productivity_chart, use_container_width=True)

        st.subheader("Material Consumption per 1000 Bricks")
        consumption_period = _add_period_column(production_filtered, "Date", period)
        consumption_period["Cement_Consumption"] = utils.to_numeric_series(
            consumption_period.get("Cement_Consumption", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption_period["FlyAsh_Consumption"] = utils.to_numeric_series(
            consumption_period.get("FlyAsh_Consumption", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption_period["No_of_Bricks"] = utils.to_numeric_series(
            consumption_period.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0)
        consumption_summary = (
            consumption_period.groupby("Period", dropna=False)[
                ["Cement_Consumption", "FlyAsh_Consumption", "No_of_Bricks"]
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
        consumption_melt = consumption_summary.melt(
            id_vars=["Period"],
            value_vars=["Cement_per_1000", "FlyAsh_per_1000"],
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
        st.altair_chart(consumption_chart, use_container_width=True)

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
        st.altair_chart(freight_chart, use_container_width=True)

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
            st.altair_chart(cap_chart, use_container_width=True)

            util_chart = (
                alt.Chart(capacity_summary)
                .mark_line(point=True)
                .encode(
                    x="Period:O",
                    y=alt.Y("Utilization:Q", title="Utilization %"),
                    tooltip=["Period", "Utilization"],
                )
            )
            st.altair_chart(util_chart, use_container_width=True)

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
        consumption["No_of_Bricks"] = utils.to_numeric_series(
            consumption.get("No_of_Bricks", pd.Series(dtype=float))
        ).fillna(0.0)
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

    st.subheader("Customer Outstanding and Stock")
    col1, col2 = st.columns(2)
    with col1:
        if not customers.empty:
            customer_view = customers[["Customer_ID", "Name", "Outstanding_Balance"]].copy()
            st.dataframe(customer_view, use_container_width=True)
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
            st.dataframe(latest_stock, use_container_width=True)

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
        st.altair_chart(stock_chart, use_container_width=True)

    st.subheader("Dashboard Diagnostics")
    with st.expander("Data quality checks", expanded=False):
        def _quality_block(label: str, frame: pd.DataFrame, date_col: str, numeric_cols: list[str]) -> None:
            st.markdown(f"**{label}**")
            if frame.empty:
                st.write("No rows.")
                return
            date_series = pd.to_datetime(frame.get(date_col, pd.Series(dtype=str)), errors="coerce", dayfirst=True)
            invalid_date = date_series.isna()
            st.write(
                {
                    "rows": len(frame),
                    "invalid_dates": int(invalid_date.sum()),
                }
            )
            if invalid_date.any():
                st.dataframe(frame[invalid_date].head(5), use_container_width=True)
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
                    st.dataframe(frame[invalid_num].head(5), use_container_width=True)

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
