from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database


def render() -> None:
    st.header("Stock")

    if st.button("Recalculate Stock", key="recalc_stock"):
        database.update_stock_log()
        st.success("Stock log recalculated.")

    stock_df = database.read_table("Stock_Log")
    if stock_df.empty:
        st.info("No stock data available.")
        return

    stock_df["Date"] = pd.to_datetime(stock_df["Date"], errors="coerce").dt.date
    stock_df = stock_df.dropna(subset=["Date"])

    materials = sorted(stock_df["Material"].astype(str).dropna().unique().tolist())
    min_date = stock_df["Date"].min() if not stock_df.empty else date.today()
    max_date = stock_df["Date"].max() if not stock_df.empty else date.today()

    date_range = st.date_input("Date Range", value=(min_date, max_date))
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = min_date
        end_date = max_date

    material_filter = st.multiselect("Material", materials)

    filtered = stock_df[(stock_df["Date"] >= start_date) & (stock_df["Date"] <= end_date)]
    if material_filter:
        filtered = filtered[filtered["Material"].isin(material_filter)]

    st.subheader("Latest Stock by Material")
    latest = (
        filtered.sort_values("Date")
        .groupby("Material", as_index=False)
        .tail(1)
        .sort_values("Material")
    )
    st.dataframe(latest, width="stretch")

    st.subheader("Stock Log")
    st.dataframe(filtered.sort_values(["Date", "Material"]), width="stretch")
