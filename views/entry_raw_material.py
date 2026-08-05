from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import database
import utils


def _parse_date(value: object) -> date | None:
    return utils.parse_date_value(value, dayfirst=True)


MATERIAL_TYPES = [
    "Fly Ash",
    "Cement",
    "Sand",
    "Stone Dust",
    "Diesel",
    "Transport",
    "Maintenance",
]


RAW_MATERIAL_COLUMNS = [
    "RM_ID",
    "Date",
    "Year",
    "Month",
    "Supplier_ID",
    "Material",
    "Qty",
    "Rate",
    "GST",
    "Total_Cost",
    "Amount_Paid",
    "Vehicle_No",
    "Trip_Days",
    "Route_Expenses",
    "Diesel",
    "Driver_Salary",
    "Vehicle_Charge",
    "Freight",
    "Material_Rate",
]


def _supplier_options(suppliers: pd.DataFrame) -> dict[str, str]:
    options: dict[str, str] = {}
    for _, row in suppliers.iterrows():
        supplier_id = str(row.get("Supplier_ID", "")).strip()
        name = str(row.get("Name", "")).strip()
        if supplier_id:
            label = f"{supplier_id} - {name}" if name else supplier_id
            options[label] = supplier_id
    return options


def render() -> None:
    st.header("Raw Material Entry")

    suppliers = database.read_table("Suppliers")
    if suppliers.empty:
        st.info("Add suppliers in Master Data before logging materials.")
        return

    supplier_labels = _supplier_options(suppliers)
    if not supplier_labels:
        st.info("Supplier IDs are missing. Update Master Data.")
        return

    with st.form("raw_material_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            material_date = st.date_input("Date", value=date.today())
            supplier_label = st.selectbox("Supplier", list(supplier_labels.keys()))
            supplier_id = supplier_labels[supplier_label]
            supplier_row = suppliers.loc[suppliers["Supplier_ID"] == supplier_id]
            supplier_material = ""
            if not supplier_row.empty:
                supplier_material = str(supplier_row.iloc[0].get("Material_Type", "")).strip()
            material_index = (
                MATERIAL_TYPES.index(supplier_material)
                if supplier_material in MATERIAL_TYPES
                else 0
            )
            material = st.selectbox("Material", MATERIAL_TYPES, index=material_index)
            if material == "Cement":
                st.caption("Cement Qty is in bags (1 bag = 0.05 tons).")
            elif material in {"Fly Ash", "Stone Dust"}:
                st.caption("Qty is in tons for Fly Ash and Stone Dust.")
            qty = st.number_input("Quantity", min_value=0.0, step=1.0)
            rate = st.number_input("Rate", min_value=0.0, step=1.0)
        with col2:
            gst = st.number_input("GST", min_value=0.0, step=1.0)
            vehicle_no = st.text_input("Vehicle No")
            trip_days = st.number_input("Trip Days", min_value=0, step=1)
            route_expenses = st.number_input("Route Expenses", min_value=0.0, step=1.0)
            diesel = st.number_input("Diesel", min_value=0.0, step=1.0)
        with col3:
            driver_salary = st.number_input("Driver Salary", min_value=0.0, step=1.0)
            vehicle_charge = st.number_input("Vehicle Charge", min_value=0.0, step=1.0)
            freight = st.number_input("Freight", min_value=0.0, step=1.0)
            amount_paid = st.number_input("Amount Paid", min_value=0.0, step=1.0)

        material_rate = qty * rate
        total_cost = utils.calculate_total_cost(
            qty=qty,
            rate=rate,
            gst=gst,
            route_expenses=route_expenses,
            diesel=diesel,
            driver_salary=driver_salary,
            vehicle_charge=vehicle_charge,
            freight=freight,
        )
        st.markdown("**Calculated Costs**")
        st.write(f"Material Rate: {material_rate:,.2f}")
        st.write(f"Total Cost: {total_cost:,.2f}")

        submitted = st.form_submit_button("Save Entry")

    if submitted:
        errors = []
        if qty <= 0:
            errors.append("Quantity must be greater than 0.")
        if rate <= 0:
            errors.append("Rate must be greater than 0.")
        if not material:
            errors.append("Material is required.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            existing_ids = (
                database.read_table("Raw_Material_Log")
                .get("RM_ID", pd.Series(dtype=str))
                .astype(str)
                .str.strip()
                .tolist()
            )
            rm_id = database.generate_log_id("RM", material_date, existing_ids)
            data = {
                "RM_ID": rm_id,
                "Date": material_date.isoformat(),
                "Year": material_date.strftime("%Y"),
                "Month": utils.to_month_string(material_date),
                "Supplier_ID": supplier_id,
                "Material": material,
                "Qty": qty,
                "Rate": rate,
                "GST": gst,
                "Total_Cost": total_cost,
                "Amount_Paid": amount_paid,
                "Vehicle_No": vehicle_no,
                "Trip_Days": trip_days,
                "Route_Expenses": route_expenses,
                "Diesel": diesel,
                "Driver_Salary": driver_salary,
                "Vehicle_Charge": vehicle_charge,
                "Freight": freight,
                "Material_Rate": material_rate,
            }
            data = {key: data.get(key, "") for key in RAW_MATERIAL_COLUMNS}
            database.insert_row("Raw_Material_Log", data)
            st.success("Raw material entry saved.")

    st.subheader("Raw Material Entries")
    entries = database.read_table("Raw_Material_Log")
    if entries.empty:
        st.info("No raw material entries yet.")
        return
    if "RM_ID" not in entries.columns:
        st.error("Missing RM_ID column in Raw_Material_Log.")
        return

    numeric_columns = [
        "Qty",
        "Rate",
        "GST",
        "Total_Cost",
        "Amount_Paid",
        "Trip_Days",
        "Route_Expenses",
        "Diesel",
        "Driver_Salary",
        "Vehicle_Charge",
        "Freight",
        "Material_Rate",
    ]
    entries = utils.coerce_numeric_columns(entries, numeric_columns)

    display_entries = entries.copy()
    display_entries["Delete"] = False
    display_entries = display_entries[["Delete"] + [col for col in entries.columns]]
    edited = st.data_editor(
        display_entries,
        use_container_width=True,
        disabled=[col for col in display_entries.columns if col != "Delete"],
        key="raw_material_entries",
    )

    if st.button("Delete selected", key="raw_material_delete"):
        selected = edited.loc[edited["Delete"] == True, "RM_ID"].dropna().astype(str).tolist()
        if not selected:
            st.warning("Select at least one entry to delete.")
        else:
            for rm_id in selected:
                database.delete_row("Raw_Material_Log", rm_id, recompute_stock=False)
            database.update_stock_log()
            st.success("Selected entries deleted.")
            st.rerun()

    st.subheader("Validation")
    rules = {
        "Date": {"required": True},
        "Supplier_ID": {"required": True},
        "Material": {"required": True},
        "Qty": {"numeric": True, "min": 0},
        "Rate": {"numeric": True, "min": 0},
        "GST": {"numeric": True, "min": 0},
        "Total_Cost": {"numeric": True, "min": 0},
        "Amount_Paid": {"numeric": True, "min": 0},
        "Route_Expenses": {"numeric": True, "min": 0},
        "Diesel": {"numeric": True, "min": 0},
        "Driver_Salary": {"numeric": True, "min": 0},
        "Vehicle_Charge": {"numeric": True, "min": 0},
        "Freight": {"numeric": True, "min": 0},
        "Material_Rate": {"numeric": True, "min": 0},
    }
    mask, errors = utils.build_validation_mask(entries, rules)
    qty = pd.to_numeric(entries.get("Qty", pd.Series(dtype=float)), errors="coerce")
    rate = pd.to_numeric(entries.get("Rate", pd.Series(dtype=float)), errors="coerce")
    gst = pd.to_numeric(entries.get("GST", pd.Series(dtype=float)), errors="coerce")
    route = pd.to_numeric(entries.get("Route_Expenses", pd.Series(dtype=float)), errors="coerce")
    diesel = pd.to_numeric(entries.get("Diesel", pd.Series(dtype=float)), errors="coerce")
    driver = pd.to_numeric(entries.get("Driver_Salary", pd.Series(dtype=float)), errors="coerce")
    vehicle = pd.to_numeric(entries.get("Vehicle_Charge", pd.Series(dtype=float)), errors="coerce")
    freight_val = pd.to_numeric(entries.get("Freight", pd.Series(dtype=float)), errors="coerce")
    material_rate = pd.to_numeric(
        entries.get("Material_Rate", pd.Series(dtype=float)),
        errors="coerce",
    )
    total_cost = pd.to_numeric(
        entries.get("Total_Cost", pd.Series(dtype=float)),
        errors="coerce",
    )

    calc_material_rate = qty * rate
    calc_total_cost = calc_material_rate + gst
    invalid_material_rate = (material_rate - calc_material_rate).abs() > 0.01
    invalid_total_cost = (total_cost - calc_total_cost).abs() > 0.01
    mask = utils.apply_invalid_mask(mask, "Material_Rate", invalid_material_rate)
    mask = utils.apply_invalid_mask(mask, "Total_Cost", invalid_total_cost)

    if mask.any().any():
        st.caption("Rows highlighted in red need correction.")
        st.dataframe(utils.style_invalid(entries, mask), use_container_width=True)
        invalid_rows = entries[mask.any(axis=1)].copy()
        edited_invalid = st.data_editor(
            invalid_rows,
            use_container_width=True,
            disabled=["RM_ID"],
            key="raw_material_invalid_editor",
        )
        if st.button("Save Corrections", key="raw_material_save_corrections"):
            for _, row in edited_invalid.iterrows():
                row = row.where(pd.notnull(row), "")
                row_id = str(row.get("RM_ID", "")).strip()
                if not row_id:
                    continue
                material = str(row.get("Material", "")).strip()
                qty_val = utils.safe_float(row.get("Qty", 0))
                rate_val = utils.safe_float(row.get("Rate", 0))
                gst_val = utils.safe_float(row.get("GST", 0))
                route_val = utils.safe_float(row.get("Route_Expenses", 0))
                diesel_val = utils.safe_float(row.get("Diesel", 0))
                driver_val = utils.safe_float(row.get("Driver_Salary", 0))
                vehicle_val = utils.safe_float(row.get("Vehicle_Charge", 0))
                freight_val = utils.safe_float(row.get("Freight", 0))
                material_rate_val = qty_val * rate_val
                total_cost_val = utils.calculate_total_cost(
                    qty=qty_val,
                    rate=rate_val,
                    gst=gst_val,
                    route_expenses=route_val,
                    diesel=diesel_val,
                    driver_salary=driver_val,
                    vehicle_charge=vehicle_val,
                    freight=freight_val,
                )
                entry_date = _parse_date(row.get("Date", ""))
                if entry_date:
                    row["Year"] = entry_date.strftime("%Y")
                    row["Month"] = utils.to_month_string(entry_date)
                row["Material_Rate"] = material_rate_val
                row["Total_Cost"] = total_cost_val
                database.update_row(
                    "Raw_Material_Log",
                    row_id,
                    row.to_dict(),
                    recompute_stock=False,
                )
            database.update_stock_log()
            st.success("Corrections saved.")
            st.rerun()
    else:
        st.success("No validation issues found.")

    st.subheader("Reconciliation Snapshot")
    stock_df = database.read_table("Stock_Log")
    if stock_df.empty:
        st.info("No system stock data available yet.")
        return
    stock_df = utils.ensure_columns(stock_df, ["Date", "Material", "Closing"])
    stock_df["Date"] = utils.to_datetime_series_explicit(stock_df["Date"], dayfirst=True).dt.date
    stock_df["Closing"] = utils.to_numeric_series(
        stock_df.get("Closing", pd.Series(dtype=float))
    ).fillna(0.0)
    latest_date = stock_df["Date"].dropna().max()
    if latest_date is None:
        st.info("No valid stock dates available.")
        return

    physical_df = database.read_table("Physical_Stock_Log")
    physical_df = utils.ensure_columns(
        physical_df,
        ["Date", "Material", "Physical_Stock_Tons"],
    )
    physical_df["Date"] = utils.to_datetime_series_explicit(
        physical_df.get("Date", pd.Series(dtype=str)),
        dayfirst=True,
    ).dt.date
    physical_df["Physical_Stock_Tons"] = utils.to_numeric_series(
        physical_df.get("Physical_Stock_Tons", pd.Series(dtype=float))
    ).fillna(0.0)
    physical_df["Material"] = physical_df["Material"].astype(str).str.strip().apply(
        utils.canonical_material_label
    )

    rows = []
    for material in ["Cement", "Fly Ash", "Stone Dust"]:
        material_mask = stock_df["Material"].astype(str).str.strip().str.lower() == material.lower()
        system_stock = stock_df[material_mask & (stock_df["Date"] <= latest_date)]
        system_value = system_stock.sort_values("Date").iloc[-1]["Closing"] if not system_stock.empty else 0.0

        physical_mask = physical_df["Material"].astype(str).str.lower() == material.lower()
        physical_stock = physical_df[physical_mask & (physical_df["Date"] <= latest_date)]
        physical_value = (
            physical_stock.sort_values("Date").iloc[-1]["Physical_Stock_Tons"]
            if not physical_stock.empty
            else None
        )
        variance = system_value - (physical_value if physical_value is not None else 0.0)
        variance_pct = variance / physical_value if physical_value not in (None, 0) else None
        rows.append(
            {
                "Material": material,
                "System_Stock_Tons": round(system_value, 2),
                "Physical_Stock_Tons": round(physical_value, 2) if physical_value is not None else "n/a",
                "Variance_Tons": round(variance, 2),
                "Variance_%": f"{variance_pct:.1%}" if variance_pct is not None else "n/a",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
