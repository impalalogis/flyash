from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database
import utils


ATTENDANCE_COLUMNS = [
    "Attendance_ID",
    "Date",
    "Labour_ID",
    "Name",
    "Status",
]

PRODUCTION_COLUMNS = [
    "Prod_ID",
    "Date",
    "Month",
    "No_of_Bricks",
    "Cement_Consumption",
    "FlyAsh_Consumption",
    "StoneDust_Consumption",
    "No_of_Labour",
    "Labour_Basis",
    "Contract_Rate",
    "Labour_Expense",
    "Labour_Payment_Date",
    "Actual_Payment_Amount",
]


def _active_labour(labour_df: pd.DataFrame) -> pd.DataFrame:
    if labour_df.empty:
        return labour_df
    if "Active_Status" not in labour_df.columns:
        return labour_df
    status = labour_df["Active_Status"].astype(str).str.strip().str.lower()
    active = status == "active"
    return labour_df[active]


def _sync_production_log(
    attendance_date: date,
    present_count: int,
    labour_df: pd.DataFrame,
) -> tuple[bool, int]:
    if present_count <= 0:
        return False, 0

    production_df = database.read_table("Production_Log")
    if production_df.empty:
        production_df = pd.DataFrame(columns=PRODUCTION_COLUMNS)
    production_df = utils.ensure_columns(production_df, PRODUCTION_COLUMNS)
    prod_dates = utils.to_datetime_series_explicit(production_df["Date"]).dt.date
    day_rows = production_df[prod_dates == attendance_date]

    avg_wage = utils.average_daily_wage(labour_df)
    labour_expense = utils.calculate_labour_expense(present_count, avg_wage)
    production_config = st.secrets.get("production", {})
    payment_range_weeks = utils.safe_int(
        production_config.get("payment_week_range_weeks"),
        default=1,
    )
    _, _, payment_range_label = utils.payment_week_range(
        attendance_date,
        max(1, payment_range_weeks),
    )
    date_str = attendance_date.isoformat()

    if day_rows.empty:
        existing_ids = (
            production_df.get("Prod_ID", pd.Series(dtype=str)).astype(str).str.strip().tolist()
        )
        prod_id = database.generate_log_id("PROD", attendance_date, existing_ids)
        data = {
            "Prod_ID": prod_id,
            "Date": date_str,
            "Month": utils.to_month_string(attendance_date),
            "No_of_Bricks": 0,
            "Cement_Consumption": 0,
            "FlyAsh_Consumption": 0,
            "StoneDust_Consumption": 0,
            "No_of_Labour": present_count,
            "Labour_Basis": "Day",
            "Contract_Rate": 0,
            "Labour_Expense": labour_expense,
            "Labour_Payment_Date": payment_range_label,
            "Actual_Payment_Amount": 0,
        }
        data = {key: data.get(key, "") for key in PRODUCTION_COLUMNS}
        database.insert_row("Production_Log", data)
        return True, 1

    updated_rows = 0
    for _, row in day_rows.iterrows():
        prod_id = str(row.get("Prod_ID", "")).strip()
        if not prod_id:
            continue
        basis = str(row.get("Labour_Basis", "")).strip().lower()
        is_contract = basis.startswith("contract")
        update_data = {"No_of_Labour": present_count}
        if not is_contract:
            update_data["Labour_Basis"] = "Day"
            update_data["Labour_Expense"] = labour_expense
        if not str(row.get("Labour_Payment_Date", "")).strip():
            update_data["Labour_Payment_Date"] = payment_range_label
        database.update_row(
            "Production_Log",
            prod_id,
            update_data,
            recompute_stock=False,
        )
        updated_rows += 1
    if updated_rows:
        database.update_stock_log()
    return False, updated_rows


def render() -> None:
    st.header("Labour Attendance")

    labour_df = database.read_table("Labour")
    if labour_df.empty:
        st.info("Add labour in Master Data before marking attendance.")
        return

    labour_df = utils.ensure_columns(
        labour_df,
        ["Labour_ID", "Name", "Active_Status", "Daily_Wage"],
    )
    active_labour = _active_labour(labour_df)
    if active_labour.empty:
        st.info("No active labour found. Update Active Status in Master Data.")
        return

    attendance_date = st.date_input("Attendance Date", value=date.today())
    attendance_df = database.read_table("Labour_Attendance")
    if attendance_df.empty:
        attendance_df = pd.DataFrame(columns=ATTENDANCE_COLUMNS)
    attendance_df = utils.ensure_columns(attendance_df, ATTENDANCE_COLUMNS)

    date_str = attendance_date.isoformat()
    existing = attendance_df[attendance_df["Date"] == date_str]
    status_map = (
        existing.set_index("Labour_ID")["Status"].astype(str).str.strip().to_dict()
        if not existing.empty
        else {}
    )

    grid_rows = []
    for _, row in active_labour.iterrows():
        labour_id = str(row.get("Labour_ID", "")).strip()
        name = str(row.get("Name", "")).strip()
        if not labour_id:
            continue
        status = status_map.get(labour_id, "")
        grid_rows.append(
            {
                "Labour_ID": labour_id,
                "Name": name,
                "Present": status.lower() == "present",
            }
        )

    grid_df = pd.DataFrame(grid_rows)
    edited = st.data_editor(
        grid_df,
        use_container_width=True,
        disabled=["Labour_ID", "Name"],
        column_config={
            "Present": st.column_config.CheckboxColumn("Present"),
        },
        key="labour_attendance_grid",
    )

    present_count = int(edited["Present"].sum()) if not edited.empty else 0
    st.caption(f"Present count: {present_count}")

    if st.button("Save Attendance", key="save_attendance"):
        if edited.empty:
            st.error("No labour rows to save.")
            return

        existing_ids = (
            attendance_df.get("Attendance_ID", pd.Series(dtype=str))
            .astype(str)
            .str.strip()
            .tolist()
        )
        new_rows = []
        for _, row in edited.iterrows():
            labour_id = str(row.get("Labour_ID", "")).strip()
            name = str(row.get("Name", "")).strip()
            if not labour_id:
                st.error("Labour_ID is required for all rows.")
                return
            status = "Present" if bool(row.get("Present")) else "Absent"
            attendance_id = database.generate_log_id("ATT", attendance_date, existing_ids)
            existing_ids.append(attendance_id)
            new_rows.append(
                {
                    "Attendance_ID": attendance_id,
                    "Date": date_str,
                    "Labour_ID": labour_id,
                    "Name": name,
                    "Status": status,
                }
            )

        updated = attendance_df[attendance_df["Date"] != date_str].copy()
        updated = pd.concat([updated, pd.DataFrame(new_rows)], ignore_index=True)
        updated = utils.ensure_columns(updated, ATTENDANCE_COLUMNS)
        database.replace_table("Labour_Attendance", updated)
        created, updated_count = _sync_production_log(
            attendance_date=attendance_date,
            present_count=present_count,
            labour_df=active_labour,
        )
        if created:
            st.success("Attendance saved and production log created.")
        elif updated_count:
            st.success("Attendance saved and production log updated.")
        else:
            st.success("Attendance saved.")
        st.rerun()

    st.subheader("Attendance Log")
    log = attendance_df[attendance_df["Date"] == date_str].copy()
    if log.empty:
        st.info("No attendance logged for this date.")
    else:
        st.dataframe(log, use_container_width=True)
