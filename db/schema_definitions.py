"""PostgreSQL table schemas mirroring Google Sheets tabs.

Each table definition lists sheet column names (as used in the app) and maps them
to PostgreSQL-safe column names with explicit data types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ColumnDef:
    sheet_name: str
    db_name: str
    pg_type: str


@dataclass(frozen=True)
class TableDef:
    sheet_name: str
    table_name: str
    columns: tuple[ColumnDef, ...]
    primary_key: tuple[str, ...]
    id_column: str | None = None

    @property
    def sheet_columns(self) -> list[str]:
        return [column.sheet_name for column in self.columns]

    @property
    def db_columns(self) -> list[str]:
        return [column.db_name for column in self.columns]

    def sheet_to_db_map(self) -> dict[str, str]:
        return {column.sheet_name: column.db_name for column in self.columns}

    def db_to_sheet_map(self) -> dict[str, str]:
        return {column.db_name: column.sheet_name for column in self.columns}


def _col(sheet_name: str, db_name: str, pg_type: str) -> ColumnDef:
    return ColumnDef(sheet_name=sheet_name, db_name=db_name, pg_type=pg_type)


SALES_LOG = TableDef(
    sheet_name="Sales_Log",
    table_name="sales_log",
    id_column="Sales_ID",
    primary_key=("sales_id",),
    columns=(
        _col("Sales_ID", "sales_id", "VARCHAR(64)"),
        _col("Date", "date", "DATE"),
        _col("Fiscal", "fiscal", "VARCHAR(32)"),
        _col("Year", "year", "INTEGER"),
        _col("Month", "month", "VARCHAR(32)"),
        _col("Customer_ID", "customer_id", "VARCHAR(64)"),
        _col("Customer_Name", "customer_name", "VARCHAR(255)"),
        _col("Destination", "destination", "VARCHAR(255)"),
        _col("Product", "product", "VARCHAR(128)"),
        _col("HSN Code", "hsn_code", "VARCHAR(32)"),
        _col("Qty", "qty", "INTEGER"),
        _col("Sale rate", "sale_rate", "NUMERIC(18, 4)"),
        _col("Rate", "rate", "NUMERIC(18, 4)"),
        _col("GST(%12)", "gst", "NUMERIC(18, 4)"),
        _col("Adjusted_Rate", "adjusted_rate", "NUMERIC(18, 4)"),
        _col("Adjusted_Amount", "adjusted_amount", "NUMERIC(18, 4)"),
        _col("Amount", "amount", "NUMERIC(18, 4)"),
        _col("Freight_rate", "freight_rate", "NUMERIC(18, 4)"),
        _col("Freight", "freight", "NUMERIC(18, 4)"),
        _col("Transport_Party", "transport_party", "VARCHAR(255)"),
        _col("Total_Amount", "total_amount", "NUMERIC(18, 4)"),
        _col("Adjusted_Total_amount", "adjusted_total_amount", "NUMERIC(18, 4)"),
        _col("Freight_Paid", "freight_paid", "NUMERIC(18, 4)"),
        _col("Freight_Paid_By", "freight_paid_by", "VARCHAR(128)"),
        _col("Amount_Received", "amount_received", "NUMERIC(18, 4)"),
        _col("Payment_Mode", "payment_mode", "VARCHAR(64)"),
        _col("Payment_Date", "payment_date", "DATE"),
        _col("Payment_ID", "payment_id", "VARCHAR(64)"),
        _col("Dues", "dues", "NUMERIC(18, 4)"),
        _col("old_Invoice_No", "old_invoice_no", "VARCHAR(64)"),
        _col("Invoice_No", "invoice_no", "VARCHAR(64)"),
        _col("Column_32", "column_32", "VARCHAR(255)"),
        _col("Column_33", "column_33", "VARCHAR(255)"),
        _col("Column_34", "column_34", "VARCHAR(255)"),
        _col("Column_35", "column_35", "VARCHAR(255)"),
    ),
)

PAYMENTS = TableDef(
    sheet_name="Payments",
    table_name="payments",
    id_column="Payment_ID",
    primary_key=("payment_id",),
    columns=(
        _col("Payment_ID", "payment_id", "VARCHAR(64)"),
        _col("Customer_ID", "customer_id", "VARCHAR(64)"),
        _col("Customer_Name", "customer_name", "VARCHAR(255)"),
        _col("Invoice_No", "invoice_no", "VARCHAR(64)"),
        _col("Amount_Paid", "amount_paid", "NUMERIC(18, 4)"),
        _col("Date", "date", "DATE"),
        _col("Mode", "mode", "VARCHAR(64)"),
        _col("Payment_Status", "payment_status", "VARCHAR(64)"),
        _col("Remaining_Amount", "remaining_amount", "NUMERIC(18, 4)"),
        _col("HSN_Code", "hsn_code", "VARCHAR(32)"),
    ),
)

RAW_MATERIAL_LOG = TableDef(
    sheet_name="Raw_Material_Log",
    table_name="raw_material_log",
    id_column="RM_ID",
    primary_key=("rm_id",),
    columns=(
        _col("RM_ID", "rm_id", "VARCHAR(64)"),
        _col("Date", "date", "DATE"),
        _col("Year", "year", "INTEGER"),
        _col("Month", "month", "VARCHAR(32)"),
        _col("Supplier_ID", "supplier_id", "VARCHAR(64)"),
        _col("Material", "material", "VARCHAR(128)"),
        _col("Qty", "qty", "NUMERIC(18, 4)"),
        _col("Rate", "rate", "NUMERIC(18, 4)"),
        _col("GST", "gst", "NUMERIC(18, 4)"),
        _col("Total_Cost", "total_cost", "NUMERIC(18, 4)"),
        _col("Amount_Paid", "amount_paid", "NUMERIC(18, 4)"),
        _col("Vehicle_No", "vehicle_no", "VARCHAR(64)"),
        _col("Trip_Days", "trip_days", "INTEGER"),
        _col("Route_Expenses", "route_expenses", "NUMERIC(18, 4)"),
        _col("Diesel", "diesel", "NUMERIC(18, 4)"),
        _col("Driver_Salary", "driver_salary", "NUMERIC(18, 4)"),
        _col("Vehicle_Charge", "vehicle_charge", "NUMERIC(18, 4)"),
        _col("Freight", "freight", "NUMERIC(18, 4)"),
        _col("Material_Rate", "material_rate", "NUMERIC(18, 4)"),
    ),
)

CUSTOMERS = TableDef(
    sheet_name="Customers",
    table_name="customers",
    id_column="Customer_ID",
    primary_key=("customer_id",),
    columns=(
        _col("Customer_ID", "customer_id", "VARCHAR(64)"),
        _col("Name", "name", "VARCHAR(255)"),
        _col("GST", "gst", "VARCHAR(32)"),
        _col("Contact", "contact", "VARCHAR(64)"),
        _col("City", "city", "VARCHAR(128)"),
        _col("Address", "address", "TEXT"),
        _col("Outstanding_Balance", "outstanding_balance", "NUMERIC(18, 4)"),
    ),
)

SUPPLIERS = TableDef(
    sheet_name="Suppliers",
    table_name="suppliers",
    id_column="Supplier_ID",
    primary_key=("supplier_id",),
    columns=(
        _col("Supplier_ID", "supplier_id", "VARCHAR(64)"),
        _col("Name", "name", "VARCHAR(255)"),
        _col("Material_Type", "material_type", "VARCHAR(128)"),
        _col("Unit_Rate", "unit_rate", "NUMERIC(18, 4)"),
        _col("Contact", "contact", "VARCHAR(64)"),
        _col("GST_Number", "gst_number", "VARCHAR(32)"),
    ),
)

PRODUCTION_LOG = TableDef(
    sheet_name="Production_Log",
    table_name="production_log",
    id_column="Prod_ID",
    primary_key=("prod_id",),
    columns=(
        _col("Prod_ID", "prod_id", "VARCHAR(64)"),
        _col("Date", "date", "DATE"),
        _col("Month", "month", "VARCHAR(32)"),
        _col("No_of_Bricks", "no_of_bricks", "INTEGER"),
        _col("Cement_Consumption", "cement_consumption", "NUMERIC(18, 4)"),
        _col("FlyAsh_Consumption", "flyash_consumption", "NUMERIC(18, 4)"),
        _col("StoneDust_Consumption", "stonedust_consumption", "NUMERIC(18, 4)"),
        _col("No_of_Labour", "no_of_labour", "INTEGER"),
        _col("Labour_Basis", "labour_basis", "VARCHAR(64)"),
        _col("Contract_Rate", "contract_rate", "NUMERIC(18, 4)"),
        _col("Labour_Expense", "labour_expense", "NUMERIC(18, 4)"),
        _col("Labour_Payment_Date", "labour_payment_date", "DATE"),
        _col("Actual_Payment_Amount", "actual_payment_amount", "NUMERIC(18, 4)"),
    ),
)

PHYSICAL_STOCK_LOG = TableDef(
    sheet_name="Physical_Stock_Log",
    table_name="physical_stock_log",
    id_column=None,
    primary_key=("date", "material"),
    columns=(
        _col("Date", "date", "DATE"),
        _col("Material", "material", "VARCHAR(128)"),
        _col("Physical_Stock_Tons", "physical_stock_tons", "NUMERIC(18, 4)"),
        _col("Notes", "notes", "TEXT"),
    ),
)

STOCK_LOG = TableDef(
    sheet_name="Stock_Log",
    table_name="stock_log",
    id_column=None,
    primary_key=("date", "material"),
    columns=(
        _col("Date", "date", "DATE"),
        _col("Month", "month", "VARCHAR(32)"),
        _col("Material", "material", "VARCHAR(128)"),
        _col("Opening", "opening", "NUMERIC(18, 4)"),
        _col("Inward", "inward", "NUMERIC(18, 4)"),
        _col("Consumed", "consumed", "NUMERIC(18, 4)"),
        _col("Closing", "closing", "NUMERIC(18, 4)"),
    ),
)

LABOUR_ATTENDANCE = TableDef(
    sheet_name="Labour_Attendance",
    table_name="labour_attendance",
    id_column="Attendance_ID",
    primary_key=("attendance_id",),
    columns=(
        _col("Attendance_ID", "attendance_id", "VARCHAR(64)"),
        _col("Date", "date", "DATE"),
        _col("Labour_ID", "labour_id", "VARCHAR(64)"),
        _col("Name", "name", "VARCHAR(255)"),
        _col("Status", "status", "VARCHAR(64)"),
    ),
)

LABOUR = TableDef(
    sheet_name="Labour",
    table_name="labour",
    id_column="Labour_ID",
    primary_key=("labour_id",),
    columns=(
        _col("Labour_ID", "labour_id", "VARCHAR(64)"),
        _col("Name", "name", "VARCHAR(255)"),
        _col("Category", "category", "VARCHAR(64)"),
        _col("Active_Status", "active_status", "VARCHAR(32)"),
        _col("Daily_Wage", "daily_wage", "NUMERIC(18, 4)"),
    ),
)

WORK_WEEK = TableDef(
    sheet_name="Work_Week",
    table_name="work_week",
    id_column=None,
    primary_key=("week_start",),
    columns=(
        _col("Week_Start", "week_start", "DATE"),
        _col("Week_End", "week_end", "DATE"),
        _col("Total_Days", "total_days", "INTEGER"),
    ),
)

TABLE_DEFINITIONS: dict[str, TableDef] = {
    table.sheet_name: table
    for table in (
        SALES_LOG,
        PAYMENTS,
        RAW_MATERIAL_LOG,
        CUSTOMERS,
        SUPPLIERS,
        PRODUCTION_LOG,
        PHYSICAL_STOCK_LOG,
        STOCK_LOG,
        LABOUR_ATTENDANCE,
        LABOUR,
        WORK_WEEK,
    )
}

MIGRATION_TABLE_ORDER: tuple[str, ...] = (
    "Suppliers",
    "Customers",
    "Labour",
    "Raw_Material_Log",
    "Production_Log",
    "Physical_Stock_Log",
    "Stock_Log",
    "Labour_Attendance",
    "Sales_Log",
    "Payments",
    "Work_Week",
)


def get_table_definition(sheet_name: str) -> TableDef:
    if sheet_name not in TABLE_DEFINITIONS:
        raise KeyError(f"No PostgreSQL schema defined for sheet: {sheet_name}")
    return TABLE_DEFINITIONS[sheet_name]


def iter_table_definitions(names: Iterable[str] | None = None) -> list[TableDef]:
    if names is None:
        return [TABLE_DEFINITIONS[name] for name in MIGRATION_TABLE_ORDER]
    return [get_table_definition(name) for name in names]
