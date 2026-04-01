from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database
import utils
from views import dashboard as dashboard_view


def render() -> None:
    st.header("Dashboard-1")

    raw_materials = dashboard_view._parse_dates(database.read_table("Raw_Material_Log"), "Date")
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

    production = dashboard_view._parse_dates(database.read_table("Production_Log"), "Date")
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

    sales = dashboard_view._parse_dates(database.read_table("Sales_Log"), "Date")
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
    expenses = dashboard_view._parse_dates(database.read_table("Expenses"), "Date")
    expenses = utils.coerce_numeric_columns(
        expenses,
        [
            "Amount",
            "GST",
            "Total_Amount",
        ],
    )
    if "Verified" in expenses.columns:
        expenses["Verified"] = expenses["Verified"].astype(str)

    st.subheader("FY Reconciliation Summary")
    all_dates = []
    for frame in [raw_materials, production, sales, expenses]:
        if not frame.empty and "Date" in frame.columns:
            all_dates.extend(
                [value for value in frame["Date"].dropna().tolist() if isinstance(value, date)]
            )
    fy_years = dashboard_view._fy_years_from_dates(all_dates)
    fy_labels = [dashboard_view._fy_label(year) for year in fy_years]
    default_year = 2023 if 2023 in fy_years else fy_years[-1]
    default_index = fy_years.index(default_year)
    fy_choice = st.selectbox(
        "Financial year",
        fy_labels,
        index=default_index,
        key="recon_fy_dashboard_1",
    )
    fy_start_year = fy_years[fy_labels.index(fy_choice)]
    month_windows = dashboard_view._fy_month_windows(fy_start_year)
    if month_windows:
        st.caption(
            f"{dashboard_view._fy_label(fy_start_year)} period: "
            f"{month_windows[0]['start']:%d %b %Y} - {month_windows[-1]['end']:%d %b %Y}"
        )
    st.caption(
        "Counts show number of records with numeric values. "
        "Totals are sums for each month. Tables use full log data."
    )

    st.markdown("**Sales Log**")
    sales_recon = dashboard_view._reconciliation_monthly_table(
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
    production_recon = dashboard_view._reconciliation_monthly_table(
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
    raw_recon = dashboard_view._reconciliation_raw_material_table(raw_materials, month_windows)
    st.dataframe(raw_recon, width="stretch")

    st.markdown("**Expenses Log**")
    expense_recon = dashboard_view._reconciliation_monthly_table(
        expenses,
        "Date",
        [
            ("Amount", "Amount"),
            ("GST", "GST"),
            ("Total_Amount", "Total_Amount"),
        ],
        month_windows,
    )
    st.dataframe(expense_recon, width="stretch")

    if "Verified" in expenses.columns and not expenses.empty:
        verified_clean = expenses["Verified"].astype(str).str.strip()
        verified_yes = verified_clean.str.lower().str.startswith("yes")
        st.markdown("**Expenses Verification Summary**")
        ver_col1, ver_col2 = st.columns(2)
        ver_col1.metric("Verified Expense Rows", int(verified_yes.sum()))
        ver_col2.metric("Unverified Expense Rows", int((~verified_yes).sum()))

    st.subheader("Dashboard Diagnostics")
    with st.expander("Data quality checks", expanded=False):
        max_rows = st.slider(
            "Rows to preview",
            min_value=5,
            max_value=100,
            value=20,
            step=5,
            key="diag_rows_dashboard_1",
        )
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
        _quality_block(
            "Expenses",
            expenses,
            "Date",
            ["Amount", "GST", "Total_Amount"],
        )

        if invalid_records:
            st.download_button(
                "Download invalid rows (CSV)",
                data=pd.DataFrame(invalid_records).to_csv(index=False),
                file_name="dashboard_invalid_rows.csv",
                mime="text/csv",
                key="diag_download_dashboard_1",
            )
