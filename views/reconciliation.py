from __future__ import annotations

from datetime import date, datetime
import re

import pandas as pd
import streamlit as st

import database
import utils


BANK_COLUMNS = [
    "Txn_ID",
    "Date",
    "Narration",
    "Debit",
    "Credit",
    "Balance",
    "Reference",
    "Counterparty",
]


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value is None or value == "":
        return None
    try:
        return pd.to_datetime(str(value), errors="coerce", dayfirst=True).date()
    except Exception:
        return None


def _parse_payment_range(value: object) -> date | None:
    if value is None or value == "":
        return None
    value_str = str(value).strip()
    if " - " in value_str:
        value_str = value_str.split(" - ", 1)[0].strip()
    try:
        return pd.to_datetime(value_str, errors="coerce", dayfirst=True).date()
    except Exception:
        return None


def _normalize_text(value: object) -> str:
    return str(value or "").strip().lower()


def _bank_text(row: pd.Series) -> str:
    return " ".join(
        [
            _normalize_text(row.get("Narration")),
            _normalize_text(row.get("Reference")),
            _normalize_text(row.get("Counterparty")),
        ]
    ).strip()


def _find_keyword_match(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords if keyword)


def _match_amount_date(
    expected: pd.DataFrame,
    amount: float,
    txn_date: date | None,
    *,
    amount_col: str,
    date_col: str,
    tolerance: float,
    window_days: int,
) -> pd.DataFrame:
    if txn_date is None:
        return pd.DataFrame(columns=expected.columns)
    delta = pd.to_timedelta(window_days, unit="D")
    dates = pd.to_datetime(expected[date_col], errors="coerce")
    amount_match = expected[amount_col].between(amount - tolerance, amount + tolerance)
    date_match = (dates >= pd.Timestamp(txn_date) - delta) & (dates <= pd.Timestamp(txn_date) + delta)
    return expected[amount_match & date_match].copy()


def render() -> None:
    st.header("Bank Reconciliation")

    st.markdown(
        "Use this page to reconcile bank statements with sales invoices, "
        "supplier payments, and labour payouts."
    )

    st.subheader("Bank Statement")
    st.caption(
        "Ensure you have a `Bank_Statement` tab in Google Sheets with the columns below."
    )
    st.code(", ".join(BANK_COLUMNS))

    try:
        bank_df = database.read_table("Bank_Statement")
    except Exception as exc:  # noqa: BLE001
        st.error("Bank_Statement sheet not found.")
        st.caption(str(exc))
        st.stop()

    if bank_df.empty:
        bank_df = pd.DataFrame(columns=BANK_COLUMNS)
    bank_df = utils.ensure_columns(bank_df, BANK_COLUMNS)

    edited = st.data_editor(
        bank_df,
        num_rows="dynamic",
        width="stretch",
        key="bank_statement_editor",
    )

    if st.button("Save Bank Statement", key="save_bank_statement"):
        updated = edited.copy()
        updated = updated.replace("", pd.NA)
        updated = updated.dropna(how="all", subset=[col for col in BANK_COLUMNS if col != "Txn_ID"])
        existing_ids = (
            updated.get("Txn_ID", pd.Series(dtype=str)).astype(str).str.strip().tolist()
        )
        for idx in updated.index:
            current = str(updated.at[idx, "Txn_ID"]).strip()
            if current:
                continue
            entry_date = _parse_date(updated.at[idx, "Date"]) or date.today()
            new_id = database.generate_log_id("BANK", entry_date, existing_ids)
            updated.at[idx, "Txn_ID"] = new_id
            existing_ids.append(new_id)
        updated = updated.fillna("")
        updated = utils.ensure_columns(updated, BANK_COLUMNS)
        database.replace_table("Bank_Statement", updated, recompute_stock=False)
        st.success("Bank statement updated.")

    st.divider()
    st.subheader("Reconciliation Settings")
    settings_col1, settings_col2 = st.columns(2)
    with settings_col1:
        date_window_days = st.number_input(
            "Date window (days)",
            min_value=0,
            max_value=30,
            value=5,
            step=1,
        )
    with settings_col2:
        amount_tolerance = st.number_input(
            "Amount tolerance",
            min_value=0.0,
            value=0.0,
            step=1.0,
        )
    match_by_reference = st.checkbox("Match by invoice/reference in narration", value=True)

    bank_clean = bank_df.copy()
    bank_clean = utils.coerce_numeric_columns(bank_clean, ["Debit", "Credit", "Balance"])
    bank_clean["Date"] = pd.to_datetime(bank_clean["Date"], errors="coerce", dayfirst=True).dt.date
    bank_clean["Text"] = bank_clean.apply(_bank_text, axis=1)

    sales_df = database.read_table("Sales_Log")
    sales_df = utils.ensure_columns(
        sales_df,
        ["Sales_ID", "Date", "Customer_ID", "Invoice_No", "Total_Amount", "No_of_Bricks"],
    )
    sales_df["Date"] = pd.to_datetime(sales_df["Date"], errors="coerce", dayfirst=True).dt.date
    sales_df["Total_Amount"] = utils.to_numeric_series(
        sales_df.get("Total_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    sales_df["Invoice_Key"] = sales_df["Invoice_No"].astype(str).str.strip()
    sales_df.loc[sales_df["Invoice_Key"] == "", "Invoice_Key"] = sales_df["Sales_ID"].astype(str)
    sales_expected = sales_df[sales_df["Invoice_Key"].astype(str).str.strip() != ""].copy()

    raw_df = database.read_table("Raw_Material_Log")
    raw_df = utils.ensure_columns(
        raw_df,
        ["RM_ID", "Date", "Supplier_ID", "Material", "Amount_Paid"],
    )
    raw_df["Date"] = pd.to_datetime(raw_df["Date"], errors="coerce", dayfirst=True).dt.date
    raw_df["Amount_Paid"] = utils.to_numeric_series(
        raw_df.get("Amount_Paid", pd.Series(dtype=float))
    ).fillna(0.0)
    supplier_expected = raw_df[raw_df["Amount_Paid"] > 0].copy()

    suppliers = database.read_table("Suppliers")
    suppliers = utils.ensure_columns(suppliers, ["Supplier_ID", "Name"])
    supplier_name_map = (
        suppliers.set_index("Supplier_ID")["Name"].astype(str).str.strip().to_dict()
        if not suppliers.empty
        else {}
    )
    supplier_expected["Supplier_Name"] = supplier_expected["Supplier_ID"].map(supplier_name_map).fillna("")

    production_df = database.read_table("Production_Log")
    production_df = utils.ensure_columns(
        production_df,
        ["Prod_ID", "Date", "Labour_Payment_Date", "Actual_Payment_Amount"],
    )
    production_df["Actual_Payment_Amount"] = utils.to_numeric_series(
        production_df.get("Actual_Payment_Amount", pd.Series(dtype=float))
    ).fillna(0.0)
    production_df["Payment_Date"] = production_df["Labour_Payment_Date"].apply(_parse_payment_range)
    production_df.loc[production_df["Payment_Date"].isna(), "Payment_Date"] = pd.to_datetime(
        production_df["Date"],
        errors="coerce",
        dayfirst=True,
    ).dt.date
    labour_expected = production_df[production_df["Actual_Payment_Amount"] > 0].copy()

    bank_credits = bank_clean[bank_clean["Credit"] > 0].copy()
    bank_debits = bank_clean[bank_clean["Debit"] > 0].copy()

    bank_credits["Matched_Key"] = ""
    bank_credits["Match_Method"] = ""
    invoice_keys = sales_expected["Invoice_Key"].astype(str).str.strip().tolist()

    for idx, row in bank_credits.iterrows():
        text = row["Text"]
        matched = ""
        method = ""
        if match_by_reference:
            for invoice in invoice_keys:
                if invoice and invoice.lower() in text:
                    matched = invoice
                    method = "Reference"
                    break
        if not matched:
            candidates = _match_amount_date(
                sales_expected,
                float(row["Credit"]),
                row["Date"],
                amount_col="Total_Amount",
                date_col="Date",
                tolerance=amount_tolerance,
                window_days=date_window_days,
            )
            if not candidates.empty:
                candidates = candidates.assign(
                    date_diff=(pd.to_datetime(candidates["Date"]) - pd.Timestamp(row["Date"])).abs()
                )
                matched = candidates.sort_values("date_diff").iloc[0]["Invoice_Key"]
                method = "Amount+Date"
        bank_credits.at[idx, "Matched_Key"] = matched
        bank_credits.at[idx, "Match_Method"] = method

    bank_debits["Matched_Key"] = ""
    bank_debits["Match_Type"] = ""
    bank_debits["Match_Method"] = ""

    supplier_names = supplier_expected["Supplier_Name"].astype(str).str.strip().tolist()

    for idx, row in bank_debits.iterrows():
        text = row["Text"]
        matched_id = ""
        match_type = ""
        method = ""
        matched_supplier = ""
        for name in supplier_names:
            if name and name.lower() in text:
                matched_supplier = name
                break
        supplier_candidates = supplier_expected
        if matched_supplier:
            supplier_candidates = supplier_expected[
                supplier_expected["Supplier_Name"].astype(str).str.lower() == matched_supplier.lower()
            ]
        candidates = _match_amount_date(
            supplier_candidates,
            float(row["Debit"]),
            row["Date"],
            amount_col="Amount_Paid",
            date_col="Date",
            tolerance=amount_tolerance,
            window_days=date_window_days,
        )
        if not candidates.empty:
            candidates = candidates.assign(
                date_diff=(pd.to_datetime(candidates["Date"]) - pd.Timestamp(row["Date"])).abs()
            )
            chosen = candidates.sort_values("date_diff").iloc[0]
            matched_id = str(chosen.get("RM_ID", ""))
            match_type = "Supplier Payment"
            method = "Reference" if matched_supplier else "Amount+Date"
        bank_debits.at[idx, "Matched_Key"] = matched_id
        bank_debits.at[idx, "Match_Type"] = match_type
        bank_debits.at[idx, "Match_Method"] = method

    salary_keywords = ["salary", "labour", "labor", "wages", "payroll"]
    for idx, row in bank_debits[bank_debits["Matched_Key"] == ""].iterrows():
        text = row["Text"]
        if not _find_keyword_match(text, salary_keywords):
            continue
        candidates = _match_amount_date(
            labour_expected,
            float(row["Debit"]),
            row["Date"],
            amount_col="Actual_Payment_Amount",
            date_col="Payment_Date",
            tolerance=amount_tolerance,
            window_days=date_window_days,
        )
        if not candidates.empty:
            chosen = candidates.iloc[0]
            bank_debits.at[idx, "Matched_Key"] = str(chosen.get("Prod_ID", ""))
            bank_debits.at[idx, "Match_Type"] = "Salary"
            bank_debits.at[idx, "Match_Method"] = "Amount+Date"

    matched_sales = bank_credits[bank_credits["Matched_Key"] != ""].copy()
    matched_sales = matched_sales.merge(
        sales_expected[["Invoice_Key", "Customer_ID", "Total_Amount", "Date"]],
        left_on="Matched_Key",
        right_on="Invoice_Key",
        how="left",
    )
    matched_sales["Match_Type"] = "Sales Receipt"

    matched_supplier = bank_debits[bank_debits["Match_Type"] == "Supplier Payment"].copy()
    matched_supplier = matched_supplier.merge(
        supplier_expected[["RM_ID", "Supplier_ID", "Supplier_Name", "Amount_Paid", "Date"]],
        left_on="Matched_Key",
        right_on="RM_ID",
        how="left",
    )

    matched_salary = bank_debits[bank_debits["Match_Type"] == "Salary"].copy()

    matched_transactions = pd.concat(
        [
            matched_sales,
            matched_supplier,
            matched_salary,
        ],
        ignore_index=True,
    )

    def _categorize(row: pd.Series) -> str:
        if row.get("Match_Type") == "Sales Receipt":
            return "Sales receipt"
        if row.get("Match_Type") == "Supplier Payment":
            return "Supplier payment"
        if row.get("Match_Type") == "Salary":
            return "Salary"
        text = row.get("Text", "")
        if row.get("Credit", 0) > 0 and _find_keyword_match(
            text, ["invoice", "sale", "customer", "inv-"]
        ):
            return "Sales receipt"
        if row.get("Debit", 0) > 0 and _find_keyword_match(
            text, ["supplier", "cement", "fly ash", "stone dust", "sand"]
        ):
            return "Supplier payment"
        if _find_keyword_match(text, ["electric", "power", "mseb"]):
            return "Electricity"
        if _find_keyword_match(text, ["transport", "freight", "diesel"]):
            return "Transport"
        if _find_keyword_match(text, ["atm", "cash"]):
            return "Cash withdrawal"
        return "Unknown"

    matched_transactions["Category"] = matched_transactions.apply(_categorize, axis=1)

    unmatched_bank = bank_clean.merge(
        matched_transactions[["Txn_ID"]],
        on="Txn_ID",
        how="left",
        indicator=True,
    )
    unmatched_bank = unmatched_bank[unmatched_bank["_merge"] == "left_only"].drop(columns=["_merge"])

    sales_summary = sales_expected.copy()
    sales_matched = matched_sales.groupby("Matched_Key")["Credit"].sum().to_dict()
    sales_summary["Matched_Amount"] = sales_summary["Invoice_Key"].map(sales_matched).fillna(0.0)
    sales_summary["Status"] = "Missing"
    sales_summary.loc[sales_summary["Matched_Amount"] > 0, "Status"] = "Partial"
    sales_summary.loc[
        sales_summary["Matched_Amount"] >= sales_summary["Total_Amount"] - 0.01,
        "Status",
    ] = "Matched"
    sales_summary.loc[
        sales_summary["Matched_Amount"] > sales_summary["Total_Amount"] + 0.01,
        "Status",
    ] = "Overpayment"

    supplier_summary = supplier_expected.copy()
    supplier_matched = matched_supplier.groupby("Matched_Key")["Debit"].sum().to_dict()
    supplier_summary["Matched_Amount"] = supplier_summary["RM_ID"].map(supplier_matched).fillna(0.0)
    supplier_summary["Status"] = "Missing"
    supplier_summary.loc[supplier_summary["Matched_Amount"] > 0, "Status"] = "Partial"
    supplier_summary.loc[
        supplier_summary["Matched_Amount"] >= supplier_summary["Amount_Paid"] - 0.01,
        "Status",
    ] = "Matched"
    supplier_summary.loc[
        supplier_summary["Matched_Amount"] > supplier_summary["Amount_Paid"] + 0.01,
        "Status",
    ] = "Overpayment"

    st.subheader("Reconciliation Report")
    matched_view = matched_transactions[
        [
            "Txn_ID",
            "Date",
            "Narration",
            "Debit",
            "Credit",
            "Match_Type",
            "Matched_Key",
            "Match_Method",
            "Category",
        ]
    ].copy()
    st.markdown("**Matched transactions**")
    st.dataframe(matched_view, width="stretch")

    st.markdown("**Unmatched bank transactions**")
    if unmatched_bank.empty:
        st.info("No unmatched bank entries.")
    else:
        unmatched_bank["Category"] = unmatched_bank.apply(_categorize, axis=1)
        st.dataframe(
            unmatched_bank[
                ["Txn_ID", "Date", "Narration", "Debit", "Credit", "Category"]
            ],
            width="stretch",
        )

    st.markdown("**Pending receipts (Sales invoices)**")
    pending_receipts = sales_summary[sales_summary["Status"].isin(["Missing", "Partial"])].copy()
    if pending_receipts.empty:
        st.info("No pending receipts.")
    else:
        st.dataframe(
            pending_receipts[
                ["Invoice_Key", "Customer_ID", "Total_Amount", "Matched_Amount", "Status"]
            ],
            width="stretch",
        )

    st.markdown("**Pending payments (Suppliers)**")
    pending_payments = supplier_summary[supplier_summary["Status"].isin(["Missing", "Partial"])].copy()
    if pending_payments.empty:
        st.info("No pending supplier payments.")
    else:
        st.dataframe(
            pending_payments[
                ["RM_ID", "Supplier_ID", "Amount_Paid", "Matched_Amount", "Status"]
            ],
            width="stretch",
        )

    st.markdown("**Suspicious entries**")
    suspicious = pd.concat(
        [
            sales_summary[sales_summary["Status"].isin(["Overpayment", "Missing"])][
                ["Invoice_Key", "Total_Amount", "Matched_Amount", "Status"]
            ].assign(Type="Sales Invoice"),
            supplier_summary[supplier_summary["Status"].isin(["Overpayment", "Missing"])][
                ["RM_ID", "Amount_Paid", "Matched_Amount", "Status"]
            ].rename(columns={"RM_ID": "Invoice_Key", "Amount_Paid": "Total_Amount"}).assign(Type="Supplier Payment"),
        ],
        ignore_index=True,
    )
    if suspicious.empty:
        st.info("No suspicious entries found.")
    else:
        st.dataframe(
            suspicious[["Type", "Invoice_Key", "Total_Amount", "Matched_Amount", "Status"]],
            width="stretch",
        )

    st.subheader("Recommendations to improve reconciliation accuracy")
    st.markdown(
        "\n".join(
            [
                "- Use consistent invoice numbers (e.g., `INV-2026-0001`) in both sales logs and bank narration.",
                "- Include invoice number + customer/supplier code in bank narration for all transfers.",
                "- Record every receipt in the Payments tab on the same day it hits the bank.",
                "- Avoid entering lump-sum payments without invoice references; split by invoice if possible.",
                "- Reconcile weekly to catch missing or duplicate entries early.",
            ]
        )
    )
