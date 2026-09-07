-- PostgreSQL schema mirroring Google Sheets tabs for the fly-ash ERP workflow.
-- Generated from db/schema_definitions.py. Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS sync_metadata (
    table_name VARCHAR(128) PRIMARY KEY,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id VARCHAR(64),
    name VARCHAR(255),
    material_type VARCHAR(128),
    unit_rate NUMERIC(18, 4),
    contact VARCHAR(64),
    gst_number VARCHAR(32),
    PRIMARY KEY (supplier_id)
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id VARCHAR(64),
    name VARCHAR(255),
    gst VARCHAR(32),
    contact VARCHAR(64),
    city VARCHAR(128),
    address TEXT,
    outstanding_balance NUMERIC(18, 4),
    PRIMARY KEY (customer_id)
);

CREATE TABLE IF NOT EXISTS labour (
    labour_id VARCHAR(64),
    name VARCHAR(255),
    category VARCHAR(64),
    active_status VARCHAR(32),
    daily_wage NUMERIC(18, 4),
    PRIMARY KEY (labour_id)
);

CREATE TABLE IF NOT EXISTS raw_material_log (
    rm_id VARCHAR(64),
    date DATE,
    year INTEGER,
    month VARCHAR(32),
    supplier_id VARCHAR(64),
    material VARCHAR(128),
    qty NUMERIC(18, 4),
    rate NUMERIC(18, 4),
    gst NUMERIC(18, 4),
    total_cost NUMERIC(18, 4),
    amount_paid NUMERIC(18, 4),
    vehicle_no VARCHAR(64),
    trip_days INTEGER,
    route_expenses NUMERIC(18, 4),
    diesel NUMERIC(18, 4),
    driver_salary NUMERIC(18, 4),
    vehicle_charge NUMERIC(18, 4),
    freight NUMERIC(18, 4),
    material_rate NUMERIC(18, 4),
    PRIMARY KEY (rm_id)
);

CREATE TABLE IF NOT EXISTS production_log (
    prod_id VARCHAR(64),
    date DATE,
    month VARCHAR(32),
    no_of_bricks INTEGER,
    cement_consumption NUMERIC(18, 4),
    flyash_consumption NUMERIC(18, 4),
    stonedust_consumption NUMERIC(18, 4),
    no_of_labour INTEGER,
    labour_basis VARCHAR(64),
    contract_rate NUMERIC(18, 4),
    labour_expense NUMERIC(18, 4),
    labour_payment_date DATE,
    actual_payment_amount NUMERIC(18, 4),
    PRIMARY KEY (prod_id)
);

CREATE TABLE IF NOT EXISTS physical_stock_log (
    date DATE,
    material VARCHAR(128),
    physical_stock_tons NUMERIC(18, 4),
    notes TEXT,
    PRIMARY KEY (date, material)
);

CREATE TABLE IF NOT EXISTS stock_log (
    date DATE,
    month VARCHAR(32),
    material VARCHAR(128),
    opening NUMERIC(18, 4),
    inward NUMERIC(18, 4),
    consumed NUMERIC(18, 4),
    closing NUMERIC(18, 4),
    PRIMARY KEY (date, material)
);

CREATE TABLE IF NOT EXISTS labour_attendance (
    attendance_id VARCHAR(64),
    date DATE,
    labour_id VARCHAR(64),
    name VARCHAR(255),
    status VARCHAR(64),
    PRIMARY KEY (attendance_id)
);

CREATE TABLE IF NOT EXISTS sales_log (
    sales_id VARCHAR(64),
    date DATE,
    fiscal VARCHAR(32),
    year INTEGER,
    month VARCHAR(32),
    customer_id VARCHAR(64),
    customer_name VARCHAR(255),
    destination VARCHAR(255),
    product VARCHAR(128),
    hsn_code VARCHAR(32),
    qty INTEGER,
    sale_rate NUMERIC(18, 4),
    rate NUMERIC(18, 4),
    gst NUMERIC(18, 4),
    adjusted_rate NUMERIC(18, 4),
    adjusted_amount NUMERIC(18, 4),
    amount NUMERIC(18, 4),
    freight_rate NUMERIC(18, 4),
    freight NUMERIC(18, 4),
    transport_party VARCHAR(255),
    total_amount NUMERIC(18, 4),
    adjusted_total_amount NUMERIC(18, 4),
    freight_paid NUMERIC(18, 4),
    freight_paid_by VARCHAR(128),
    amount_received NUMERIC(18, 4),
    payment_mode VARCHAR(64),
    payment_date DATE,
    payment_id VARCHAR(64),
    dues NUMERIC(18, 4),
    old_invoice_no VARCHAR(64),
    invoice_no VARCHAR(64),
    column_32 VARCHAR(255),
    column_33 VARCHAR(255),
    column_34 VARCHAR(255),
    column_35 VARCHAR(255),
    PRIMARY KEY (sales_id)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id VARCHAR(64),
    customer_id VARCHAR(64),
    customer_name VARCHAR(255),
    invoice_no VARCHAR(64),
    amount_paid NUMERIC(18, 4),
    date DATE,
    mode VARCHAR(64),
    payment_status VARCHAR(64),
    remaining_amount NUMERIC(18, 4),
    hsn_code VARCHAR(32),
    PRIMARY KEY (payment_id)
);

CREATE TABLE IF NOT EXISTS work_week (
    week_start DATE,
    week_end DATE,
    total_days INTEGER,
    PRIMARY KEY (week_start)
);
