from __future__ import annotations

from datetime import date

import streamlit as st

import database
import utils


PRODUCTION_COLUMNS = [
    "Prod_ID",
    "Date",
    "Month",
    "No_of_Bricks",
    "Cement_Consumption",
    "FlyAsh_Consumption",
    "No_of_Labour",
    "Labour_Expense",
    "Labour_Payment_Date",
    "Actual_Payment_Amount",
]


def render() -> None:
    st.header("Production Entry")

    labour_df = database.read_table("Labour")
    avg_wage = utils.average_daily_wage(labour_df)

    with st.form("production_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            prod_date = st.date_input("Date", value=date.today())
            no_of_bricks = st.number_input("No of Bricks", min_value=0, step=1)
            cement_consumption = st.number_input("Cement Consumption", min_value=0.0, step=1.0)
            flyash_consumption = st.number_input("Fly Ash Consumption", min_value=0.0, step=1.0)
        with col2:
            no_of_labour = st.number_input("No of Labour", min_value=0, step=1)
            labour_payment_date = st.date_input(
                "Labour Payment Date",
                value=prod_date,
            )
            actual_payment_amount = st.number_input(
                "Actual Payment Amount",
                min_value=0.0,
                step=1.0,
            )

        labour_expense = utils.calculate_labour_expense(no_of_labour, avg_wage)
        st.markdown("**Calculated Labour Expense**")
        st.write(f"Average Daily Wage: {avg_wage:,.2f}")
        st.write(f"Labour Expense: {labour_expense:,.2f}")

        submitted = st.form_submit_button("Save Entry")

    if submitted:
        data = {
            "Prod_ID": database.generate_id("PROD"),
            "Date": prod_date.isoformat(),
            "Month": utils.to_month_string(prod_date),
            "No_of_Bricks": no_of_bricks,
            "Cement_Consumption": cement_consumption,
            "FlyAsh_Consumption": flyash_consumption,
            "No_of_Labour": no_of_labour,
            "Labour_Expense": labour_expense,
            "Labour_Payment_Date": labour_payment_date.isoformat(),
            "Actual_Payment_Amount": actual_payment_amount,
        }
        data = {key: data.get(key, "") for key in PRODUCTION_COLUMNS}
        database.insert_row("Production_Log", data)
        st.success("Production entry saved.")

    st.subheader("Production Entries")
    entries = database.read_table("Production_Log")
    if entries.empty:
        st.info("No production entries yet.")
        return
    if "Prod_ID" not in entries.columns:
        st.error("Missing Prod_ID column in Production_Log.")
        return

    display_entries = entries.copy()
    display_entries["Delete"] = False
    display_entries = display_entries[["Delete"] + [col for col in entries.columns]]
    edited = st.data_editor(
        display_entries,
        use_container_width=True,
        disabled=[col for col in display_entries.columns if col != "Delete"],
        key="production_entries",
    )

    if st.button("Delete selected", key="production_delete"):
        selected = edited.loc[edited["Delete"] == True, "Prod_ID"].dropna().astype(str).tolist()
        if not selected:
            st.warning("Select at least one entry to delete.")
        else:
            for prod_id in selected:
                database.delete_row("Production_Log", prod_id)
            st.success("Selected entries deleted.")
            st.rerun()
