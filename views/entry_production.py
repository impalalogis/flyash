from __future__ import annotations

from datetime import date

import pandas as pd
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
    "StoneDust_Consumption",
    "No_of_Labour",
    "Labour_Basis",
    "Contract_Rate",
    "Labour_Expense",
    "Labour_Payment_Date",
    "Actual_Payment_Amount",
]

DEFAULT_STONE_DUST_PER_BRICK = 1.38
DEFAULT_FLYASH_PER_BRICK = 1.84
DEFAULT_PAYMENT_WEEK_RANGE = 1


def _get_production_config() -> dict[str, float]:
    config = st.secrets.get("production", {})
    flyash_per_brick = utils.safe_float(
        config.get("flyash_per_brick"),
        default=DEFAULT_FLYASH_PER_BRICK,
    )
    if flyash_per_brick <= 0:
        flyash_per_brick = DEFAULT_FLYASH_PER_BRICK
    stone_dust_per_brick = utils.safe_float(
        config.get("stone_dust_per_brick"),
        default=DEFAULT_STONE_DUST_PER_BRICK,
    )
    if stone_dust_per_brick <= 0:
        stone_dust_per_brick = DEFAULT_STONE_DUST_PER_BRICK
    contract_rate = utils.safe_float(config.get("contract_rate"), default=0.0)
    if contract_rate < 0:
        contract_rate = 0.0
    payment_week_range = utils.safe_int(
        config.get("payment_week_range_weeks"),
        default=DEFAULT_PAYMENT_WEEK_RANGE,
    )
    if payment_week_range < 1:
        payment_week_range = DEFAULT_PAYMENT_WEEK_RANGE
    return {
        "flyash_per_brick": flyash_per_brick,
        "stone_dust_per_brick": stone_dust_per_brick,
        "contract_rate": contract_rate,
        "payment_week_range_weeks": payment_week_range,
    }


def _attendance_count(attendance_df, prod_date: date) -> tuple[int, bool]:
    if attendance_df.empty or "Date" not in attendance_df.columns:
        return 0, False
    date_str = prod_date.isoformat()
    day = attendance_df[attendance_df["Date"] == date_str]
    if day.empty:
        return 0, False
    status = day.get("Status")
    if status is None:
        return 0, False
    present = status.astype(str).str.strip().str.lower() == "present"
    return int(present.sum()), True


def render() -> None:
    st.header("Production Entry")

    production_config = _get_production_config()
    flyash_per_brick = production_config["flyash_per_brick"]
    stone_dust_per_brick = production_config["stone_dust_per_brick"]
    contract_rate_default = production_config["contract_rate"]
    payment_week_range_weeks = int(production_config["payment_week_range_weeks"])

    labour_df = database.read_table("Labour")
    avg_wage = utils.average_daily_wage(labour_df)
    attendance_df = database.read_table("Labour_Attendance")

    with st.form("production_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            prod_date = st.date_input("Date", value=date.today(), key="production_date")
            no_of_bricks = st.number_input("No of Bricks", min_value=0, step=1)
            cement_consumption = st.number_input("Cement Consumption", min_value=0.0, step=1.0)
            flyash_consumption = round(no_of_bricks * flyash_per_brick, 2)
            st.number_input(
                "Fly Ash Consumption (auto)",
                min_value=0.0,
                value=flyash_consumption,
                step=0.01,
                format="%.2f",
                disabled=True,
            )
            stone_dust_consumption = round(no_of_bricks * stone_dust_per_brick, 2)
            st.number_input(
                "Stone Dust Consumption (auto)",
                min_value=0.0,
                value=stone_dust_consumption,
                step=0.01,
                format="%.2f",
                disabled=True,
            )
        with col2:
            attendance_count, has_attendance = _attendance_count(attendance_df, prod_date)
            labour_basis = st.radio(
                "Labour Expense Basis",
                ["Day", "Contract"],
                horizontal=True,
            )
            no_of_labour = st.number_input(
                "No of Labour",
                min_value=0,
                step=1,
                key="production_no_of_labour",
            )
            if labour_basis == "Day":
                if has_attendance:
                    st.caption(f"Attendance count for date: {attendance_count} (reference)")
                else:
                    st.caption("No attendance logged for this date.")
            contract_rate = st.number_input(
                "Contract Rate (per brick)",
                min_value=0.0,
                value=contract_rate_default,
                step=0.01,
                disabled=labour_basis != "Contract",
            )
            if labour_basis != "Contract":
                contract_rate = 0.0
            _, _, payment_range_label = utils.payment_week_range(
                prod_date,
                payment_week_range_weeks,
            )
            labour_payment_date = st.text_input(
                "Labour Payment Date",
                value=payment_range_label,
                disabled=True,
                help="Auto-filled based on the configured week window.",
            )
            actual_payment_amount = st.number_input(
                "Actual Payment Amount",
                min_value=0.0,
                step=1.0,
            )

        labour_expense = utils.calculate_labour_expense(
            no_of_labour,
            avg_wage,
            basis=labour_basis,
            no_of_bricks=no_of_bricks,
            contract_rate=contract_rate,
        )
        st.markdown("**Calculated Labour Expense**")
        if labour_basis == "Contract":
            st.write(f"Contract Rate: {contract_rate:,.2f}")
            st.write(f"Bricks: {no_of_bricks:,.0f}")
        else:
            st.write(f"Average Daily Wage: {avg_wage:,.2f}")
            st.write(f"No of Labour: {no_of_labour:,.0f}")
        st.write(f"Labour Expense: {labour_expense:,.2f}")

        submitted = st.form_submit_button("Save Entry")

    if submitted:
        errors = []
        if no_of_bricks <= 0:
            errors.append("No of Bricks must be greater than 0.")
        if labour_basis == "Day" and no_of_labour <= 0:
            errors.append("No of Labour must be greater than 0 for day basis.")
        if labour_basis == "Contract" and contract_rate <= 0:
            errors.append("Contract Rate must be greater than 0 for contract basis.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            existing_ids = (
                database.read_table("Production_Log")
                .get("Prod_ID", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .tolist()
            )
            prod_id = database.generate_log_id("PROD", prod_date, existing_ids)
            data = {
                "Prod_ID": prod_id,
                "Date": prod_date.isoformat(),
                "Month": utils.to_month_string(prod_date),
                "No_of_Bricks": no_of_bricks,
                "Cement_Consumption": cement_consumption,
                "FlyAsh_Consumption": flyash_consumption,
                "StoneDust_Consumption": stone_dust_consumption,
                "No_of_Labour": no_of_labour,
                "Labour_Basis": labour_basis,
                "Contract_Rate": contract_rate,
                "Labour_Expense": labour_expense,
                "Labour_Payment_Date": labour_payment_date,
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

    numeric_columns = [
        "No_of_Bricks",
        "Cement_Consumption",
        "FlyAsh_Consumption",
        "StoneDust_Consumption",
        "No_of_Labour",
        "Contract_Rate",
        "Labour_Expense",
        "Actual_Payment_Amount",
    ]
    entries = utils.coerce_numeric_columns(entries, numeric_columns)

    display_entries = entries.copy()
    display_entries["Delete"] = False
    display_entries = display_entries[["Delete"] + [col for col in entries.columns]]
    edited = st.data_editor(
        display_entries,
        width="stretch",
        disabled=[col for col in display_entries.columns if col != "Delete"],
        key="production_entries",
    )

    if st.button("Delete selected", key="production_delete"):
        selected = edited.loc[edited["Delete"] == True, "Prod_ID"].dropna().astype(str).tolist()
        if not selected:
            st.warning("Select at least one entry to delete.")
        else:
            for prod_id in selected:
                database.delete_row("Production_Log", prod_id, recompute_stock=False)
            database.update_stock_log()
            st.success("Selected entries deleted.")
            st.rerun()

    st.subheader("Validation")
    rules = {
        "Date": {"required": True},
        "No_of_Bricks": {"numeric": True, "min": 0},
        "Cement_Consumption": {"numeric": True, "min": 0},
        "FlyAsh_Consumption": {"numeric": True, "min": 0},
        "StoneDust_Consumption": {"numeric": True, "min": 0},
        "No_of_Labour": {"numeric": True, "min": 0},
        "Labour_Expense": {"numeric": True, "min": 0},
        "Actual_Payment_Amount": {"numeric": True, "min": 0},
    }
    mask, errors = utils.build_validation_mask(entries, rules)
    bricks = pd.to_numeric(entries.get("No_of_Bricks", pd.Series(dtype=float)), errors="coerce")
    flyash = pd.to_numeric(
        entries.get("FlyAsh_Consumption", pd.Series(dtype=float)),
        errors="coerce",
    )
    stone_dust = pd.to_numeric(
        entries.get("StoneDust_Consumption", pd.Series(dtype=float)),
        errors="coerce",
    )
    expected_flyash = bricks * flyash_per_brick
    expected_stone_dust = bricks * stone_dust_per_brick
    invalid_flyash = (flyash - expected_flyash).abs() > 0.01
    invalid_stone_dust = (stone_dust - expected_stone_dust).abs() > 0.01
    mask = utils.apply_invalid_mask(mask, "FlyAsh_Consumption", invalid_flyash)
    mask = utils.apply_invalid_mask(mask, "StoneDust_Consumption", invalid_stone_dust)
    basis = entries.get("Labour_Basis", pd.Series(dtype=str)).astype(str).str.strip().str.lower()
    contract_rate = pd.to_numeric(
        entries.get("Contract_Rate", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0.0)
    contract_mask = basis.str.startswith("contract")
    invalid_contract_rate = contract_mask & (contract_rate <= 0)
    mask = utils.apply_invalid_mask(mask, "Contract_Rate", invalid_contract_rate)
    if mask.any().any():
        st.caption("Rows highlighted in red need correction.")
        st.dataframe(utils.style_invalid(entries, mask), width="stretch")
        invalid_rows = entries[mask.any(axis=1)].copy()
        edited_invalid = st.data_editor(
            invalid_rows,
            width="stretch",
            disabled=["Prod_ID"],
            key="production_invalid_editor",
        )
        if st.button("Save Corrections", key="production_save_corrections"):
            for _, row in edited_invalid.iterrows():
                row = row.where(pd.notnull(row), "")
                row_id = str(row.get("Prod_ID", "")).strip()
                if not row_id:
                    continue
                database.update_row(
                    "Production_Log",
                    row_id,
                    row.to_dict(),
                    recompute_stock=False,
                )
            database.update_stock_log()
            st.success("Corrections saved.")
            st.rerun()
    else:
        st.success("No validation issues found.")

    st.subheader("Maintenance")
    with st.expander("Backfill computed columns (overwrite)", expanded=False):
        st.write(
            "Overwrites FlyAsh_Consumption, StoneDust_Consumption, Labour_Basis, "
            "Contract_Rate, Labour_Expense, and Labour_Payment_Date using current "
            "configuration for the selected date range."
        )
        backfill_col1, backfill_col2 = st.columns(2)
        with backfill_col1:
            backfill_flyash_per_brick = st.number_input(
                "Backfill Fly Ash per brick",
                min_value=0.0,
                value=flyash_per_brick,
                step=0.01,
                key="backfill_flyash_per_brick",
            )
            backfill_stone_dust_per_brick = st.number_input(
                "Backfill Stone Dust per brick",
                min_value=0.0,
                value=stone_dust_per_brick,
                step=0.01,
                key="backfill_stone_dust_per_brick",
            )
        with backfill_col2:
            backfill_basis = st.selectbox(
                "Backfill Labour Basis",
                ["Day", "Contract"],
                index=0,
                key="backfill_labour_basis",
            )
            backfill_contract_rate = st.number_input(
                "Backfill Contract Rate (per brick)",
                min_value=0.0,
                value=contract_rate_default,
                step=0.01,
                key="backfill_contract_rate",
                disabled=backfill_basis != "Contract",
            )
        if backfill_basis != "Contract":
            backfill_contract_rate = 0.0

        date_series = pd.to_datetime(
            entries.get("Date", pd.Series(dtype=str)),
            errors="coerce",
        ).dt.date
        valid_dates = date_series.dropna()
        if valid_dates.empty:
            st.info("No valid production dates available for backfill.")
        else:
            min_date = valid_dates.min()
            max_date = valid_dates.max()
            backfill_range = st.date_input(
                "Backfill date range",
                value=(min_date, max_date),
                key="production_backfill_range",
            )
            if isinstance(backfill_range, tuple) and len(backfill_range) == 2:
                start_date, end_date = backfill_range
            else:
                start_date = min_date
                end_date = max_date

            if st.button("Overwrite computed fields", key="production_backfill"):
                production_df = database.read_table("Production_Log")
                if production_df.empty:
                    st.info("No production entries available to update.")
                else:
                    updated = production_df.copy()
                    for column in PRODUCTION_COLUMNS:
                        if column not in updated.columns:
                            updated[column] = ""

                    dates = pd.to_datetime(
                        updated.get("Date", pd.Series(dtype=str)),
                        errors="coerce",
                    ).dt.date
                    in_range = (dates >= start_date) & (dates <= end_date)
                    in_range = in_range.fillna(False)
                    if not in_range.any():
                        st.info("No production entries found in the selected range.")
                        return

                    bricks = pd.to_numeric(
                        updated.get("No_of_Bricks", pd.Series(dtype=float)),
                        errors="coerce",
                    ).fillna(0.0)
                    updated.loc[in_range, "FlyAsh_Consumption"] = (
                        bricks * backfill_flyash_per_brick
                    ).round(2)
                    updated.loc[in_range, "StoneDust_Consumption"] = (
                        bricks * backfill_stone_dust_per_brick
                    ).round(2)

                    basis_is_contract = backfill_basis == "Contract"
                    updated.loc[in_range, "Labour_Basis"] = backfill_basis
                    updated.loc[in_range, "Contract_Rate"] = (
                        backfill_contract_rate if basis_is_contract else 0.0
                    )

                    labour_count = pd.to_numeric(
                        updated.get("No_of_Labour", pd.Series(dtype=float)),
                        errors="coerce",
                    ).fillna(0.0)
                    day_expense = labour_count * avg_wage
                    contract_expense = bricks * float(backfill_contract_rate)
                    labour_expense = day_expense.where(~basis_is_contract, contract_expense)
                    updated.loc[in_range, "Labour_Expense"] = labour_expense

                    def _range_label(value: object) -> str:
                        if pd.isna(value):
                            return ""
                        return utils.payment_week_range(value, payment_week_range_weeks)[2]

                    updated.loc[in_range, "Labour_Payment_Date"] = dates.apply(_range_label)

                    database.replace_table("Production_Log", updated)
                    st.success("Production log updated.")
