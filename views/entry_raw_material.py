from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database
import utils


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
    "Month",
    "Supplier_ID",
    "Material",
    "Qty",
    "Rate",
    "GST",
    "Vehicle_No",
    "Trip_Days",
    "Route_Expenses",
    "Diesel",
    "Driver_Salary",
    "Vehicle_Charge",
    "Freight",
    "Amount_Paid",
    "Material_Rate",
    "Total_Cost",
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
                "Month": utils.to_month_string(material_date),
                "Supplier_ID": supplier_id,
                "Material": material,
                "Qty": qty,
                "Rate": rate,
                "GST": gst,
                "Vehicle_No": vehicle_no,
                "Trip_Days": trip_days,
                "Route_Expenses": route_expenses,
                "Diesel": diesel,
                "Driver_Salary": driver_salary,
                "Vehicle_Charge": vehicle_charge,
                "Freight": freight,
                "Amount_Paid": amount_paid,
                "Material_Rate": material_rate,
                "Total_Cost": total_cost,
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
        "Trip_Days",
        "Route_Expenses",
        "Diesel",
        "Driver_Salary",
        "Vehicle_Charge",
        "Freight",
        "Amount_Paid",
        "Material_Rate",
        "Total_Cost",
    ]
    entries = utils.coerce_numeric_columns(entries, numeric_columns)

    display_entries = entries.copy()
    display_entries["Delete"] = False
    display_entries = display_entries[["Delete"] + [col for col in entries.columns]]
    edited = st.data_editor(
        display_entries,
        width="stretch",
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
        "Route_Expenses": {"numeric": True, "min": 0},
        "Diesel": {"numeric": True, "min": 0},
        "Driver_Salary": {"numeric": True, "min": 0},
        "Vehicle_Charge": {"numeric": True, "min": 0},
        "Freight": {"numeric": True, "min": 0},
        "Amount_Paid": {"numeric": True, "min": 0},
        "Material_Rate": {"numeric": True, "min": 0},
        "Total_Cost": {"numeric": True, "min": 0},
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
    calc_total_cost = (
        calc_material_rate + gst + route + diesel + driver + vehicle + freight_val
    )
    invalid_material_rate = (material_rate - calc_material_rate).abs() > 0.01
    invalid_total_cost = (total_cost - calc_total_cost).abs() > 0.01
    mask = utils.apply_invalid_mask(mask, "Material_Rate", invalid_material_rate)
    mask = utils.apply_invalid_mask(mask, "Total_Cost", invalid_total_cost)

    if mask.any().any():
        st.caption("Rows highlighted in red need correction.")
        st.dataframe(utils.style_invalid(entries, mask), width="stretch")
        invalid_rows = entries[mask.any(axis=1)].copy()
        edited_invalid = st.data_editor(
            invalid_rows,
            width="stretch",
            disabled=["RM_ID"],
            key="raw_material_invalid_editor",
        )
        if st.button("Save Corrections", key="raw_material_save_corrections"):
            for _, row in edited_invalid.iterrows():
                row = row.where(pd.notnull(row), "")
                row_id = str(row.get("RM_ID", "")).strip()
                if not row_id:
                    continue
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
