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


def _active_labour(labour_df: pd.DataFrame) -> pd.DataFrame:
    if labour_df.empty:
        return labour_df
    if "Active_Status" not in labour_df.columns:
        return labour_df
    active = labour_df["Active_Status"].astype(str).str.strip().str.lower() != "inactive"
    return labour_df[active]


def render() -> None:
    st.header("Labour Attendance")

    labour_df = database.read_table("Labour")
    if labour_df.empty:
        st.info("Add labour in Master Data before marking attendance.")
        return

    labour_df = utils.ensure_columns(labour_df, ["Labour_ID", "Name", "Active_Status"])
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

        new_rows = []
        for _, row in edited.iterrows():
            labour_id = str(row.get("Labour_ID", "")).strip()
            name = str(row.get("Name", "")).strip()
            if not labour_id:
                st.error("Labour_ID is required for all rows.")
                return
            status = "Present" if bool(row.get("Present")) else "Absent"
            new_rows.append(
                {
                    "Attendance_ID": database.generate_id("ATT"),
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
        st.success("Attendance saved.")
        st.rerun()

    st.subheader("Attendance Log")
    log = attendance_df[attendance_df["Date"] == date_str].copy()
    if log.empty:
        st.info("No attendance logged for this date.")
    else:
        st.dataframe(log, use_container_width=True)
