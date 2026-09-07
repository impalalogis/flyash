-- Upgrade script for databases created before the flyash_ table prefix.
-- Safe to run once on existing deployments; new installs should use schema.sql.

-- Column type adjustments
ALTER TABLE flyash_sales_log ALTER COLUMN destination TYPE TEXT;

ALTER TABLE flyash_payments ALTER COLUMN customer_name TYPE TEXT;
ALTER TABLE flyash_payments ALTER COLUMN invoice_no TYPE VARCHAR(255);
ALTER TABLE flyash_payments ALTER COLUMN mode TYPE VARCHAR(128);
ALTER TABLE flyash_payments ALTER COLUMN payment_status TYPE VARCHAR(128);

-- Table renames (skip any statement that already ran)
ALTER TABLE IF EXISTS sync_metadata RENAME TO flyash_sync_metadata;
ALTER TABLE IF EXISTS suppliers RENAME TO flyash_suppliers;
ALTER TABLE IF EXISTS customers RENAME TO flyash_customers;
ALTER TABLE IF EXISTS labour RENAME TO flyash_labour;
ALTER TABLE IF EXISTS raw_material_log RENAME TO flyash_raw_material_log;
ALTER TABLE IF EXISTS production_log RENAME TO flyash_production_log;
ALTER TABLE IF EXISTS physical_stock_log RENAME TO flyash_physical_stock_log;
ALTER TABLE IF EXISTS stock_log RENAME TO flyash_stock_log;
ALTER TABLE IF EXISTS labour_attendance RENAME TO flyash_labour_attendance;
ALTER TABLE IF EXISTS sales_log RENAME TO flyash_sales_log;
ALTER TABLE IF EXISTS payments RENAME TO flyash_payments;
ALTER TABLE IF EXISTS work_week RENAME TO flyash_work_week;
