# flyash

Streamlit application for managing fly-ash brick manufacturing operations using
Google Sheets as a lightweight relational backend.

## Google Sheets setup

### 1) Create the spreadsheet and tabs
Create a Google Sheet and add the following tabs (case-sensitive):

- `Suppliers`
- `Customers`
- `Labour`
- `Labour_Attendance`
- `Stock_Log`
- `Raw_Material_Log`
- `Production_Log`
- `Sales_Log`
- `Payments`
- `Bank_Statement`
- `Work_Week`
- `Holidays`
- `Planning_Config`
- `Physical_Stock_Log`
- `Daily_Summary` (optional)

### 2) Add headers to each tab
Add the following header row (row 1) for each tab:

**Suppliers**
- Supplier_ID
- Name
- Material_Type
- Unit_Rate
- Contact
- GST_Number

**Customers**
- Customer_ID
- Name
- Contact
- Address
- Outstanding_Balance
- Credit_Limit

**Labour**
- Labour_ID
- Name
- Category
- Active_Status
- Daily_Wage

**Labour_Attendance**
- Attendance_ID
- Date
- Labour_ID
- Name
- Status

**Stock_Log**
- Date
- Month
- Material
- Opening
- Inward
- Consumed
- Closing

**Raw_Material_Log**
- RM_ID
- Date
- Year
- Month
- Supplier_ID
- Material
- Qty
- Rate
- GST
- Total_Cost
- Amount_Paid
- Vehicle_No
- Trip_Days
- Route_Expenses
- Diesel
- Driver_Salary
- Vehicle_Charge
- Freight
- Material_Rate
- Stock_In_Tons

**Production_Log**
- Prod_ID
- Date
- Month
- No_of_Bricks
- Cement_Consumption
- FlyAsh_Consumption
- StoneDust_Consumption
- No_of_Labour
- Labour_Basis
- Contract_Rate
- Labour_Expense
- Labour_Payment_Date
- Actual_Payment_Amount

Notes:
- Fly ash consumption defaults to 1.84 per brick (configurable via `production.flyash_per_brick`).
- Stone dust consumption defaults to 1.38 per brick (configurable via `production.stone_dust_per_brick`).
- Labour_Basis supports Day or Contract. For Day, Labour_Expense = avg daily wage * No_of_Labour.
  For Contract, Labour_Expense = No_of_Bricks * Contract_Rate.
- Contract rate default is configurable via `production.contract_rate`.
- For Day basis, No_of_Labour is auto-filled from Labour_Attendance for the date.
- Labour payment date range is configurable via `production.payment_week_range_weeks`.

**Sales_Log**
- Sales_ID
- Date
- Month
- Customer_ID
- Destination
- No_of_Bricks
- Rate
- Amount
- Freight
- Transport_Party
- Total_Amount
- Freight_Paid
- Freight_Paid_By
- Amount_Received
- Payment_Mode
- Payment_Date
- Due
- Invoice_No

**Payments**
- Payment_ID
- Customer_ID
- Invoice_No
- Amount_Paid
- Date
- Mode
- Payment_Status

**Bank_Statement**
- Txn_ID
- Date
- Narration
- Debit
- Credit
- Balance
- Reference
- Counterparty

**Physical_Stock_Log**
- Date
- Material
- Physical_Stock_Tons
- Notes

**Work_Week**
- Week_Start
- Week_End
- Total_Days

**Holidays**
- Date
- Name

**Planning_Config**
- Key
- Value
- Notes

Suggested keys:
- history_window_days
- min_target_pct / ideal_target_pct / stretch_target_pct
- buffer_pct
- cement_per_brick / flyash_per_brick / stone_dust_per_brick
- electricity_per_week / transport_per_week / maintenance_per_week / misc_per_week

**Daily_Summary (optional)**
- Date
- Total_Production
- Total_Raw_Material_Cost
- Total_Labour_Cost
- Total_Sales
- Profit

### 3) Create a Google service account
1. Create or select a GCP project.
2. Enable the Google Sheets API and Google Drive API.
3. Create a service account and generate a JSON key.

### 4) Share the sheet with the service account
Open your Google Sheet and share it with the service account email
from the JSON key (the `client_email` field).

## Configure secrets
1. Copy the template:
   - `.streamlit/secrets.toml.template` -> `.streamlit/secrets.toml`
2. Paste the JSON fields from the service account into
   `gcp_service_account` in `secrets.toml`.
3. Set either `gsheets.spreadsheet_id` or `gsheets.spreadsheet_url`.
4. Keep `private_key` on a single line with `\n` for new lines.

### Production settings (optional)
You can configure production defaults in Streamlit secrets:

```
[production]
flyash_per_brick = 1.84
stone_dust_per_brick = 1.38
contract_rate = 0.0
payment_week_range_weeks = 1
```

## Dashboard insights (business + technical)
The Dashboard includes analytics that translate your logs into operational and financial guidance:

**Business insights**
- Production vs Sales comparisons (monthly/quarterly/yearly), gaps, and conversion ratios.
- Best & worst months for production, sales, and conversion.
- Raw material usage trends (cement, fly ash, stone dust) with procurement calendar hints.
- Cost breakdown (labour, raw materials, freight/transport, maintenance) and cost per brick.
- Actionable recommendations to improve profit, efficiency, and inventory balance.

**Operational diagnostics**
- Data anomaly detection: negative stock, sales > production, usage mismatches, sales spikes,
  and cost spikes with likely causes + corrective actions.
- Production vs sales days analysis with correlations and outlier months.
- Profitability trends with profit margin and profit per brick.

**KPI tools**
- Diagnostic KPI report (like a medical test): current value, ideal range, status,
  business meaning, and practical steps to improve.
- KPI dictionary: definitions, why they matter, and target ranges.

Tip: The quality of insights depends on accurate data entry for dates, quantities,
and costs in the Google Sheets tabs.

## Bank reconciliation
The **Reconciliation** page matches bank credits/debits with sales invoices and
supplier payments. To use it:
- Maintain the `Bank_Statement` tab and keep narration/reference accurate.
- Use invoice numbers in bank narration for faster matching.
- Reconcile weekly to catch missing or duplicate entries early.

## Weekly planner
The **Weekly Planner** page uses Work_Week, Holidays, and Planning_Config to
produce a weekly production, procurement, sales, and budget plan:
- Available production days (holiday-adjusted).
- Minimum/ideal/stretch production targets based on historical averages.
- Raw material requirements vs current stock and purchase timing.
- Weekly sales targets based on velocity + inventory.
- Weekly budget with expected revenue and profit.

## Raw material reconciliation
The **Raw Material Reconciliation** page compares system stock with physical
stock counts and reconciles expected vs actual consumption in **tons**:
- System stock vs Physical_Stock_Log (variance and % variance).
- Expected usage vs actual usage for cement, fly ash, and stone dust.
- Material cost per brick and variance alerts (overconsumption, high variance).

## Deploying on Streamlit Cloud
1. Open your app settings in Streamlit Cloud.
2. In "Secrets", paste the same content you would place in
   `.streamlit/secrets.toml`.
3. Ensure the `gsheets` block includes `spreadsheet_id` or `spreadsheet_url`.
4. Re-deploy the app after saving secrets.

## Invoice branding (one-time setup)
You can set invoice branding in Streamlit secrets so users don't re-upload it.
Add this block under secrets:

```
[invoice]
company_name = "Fly-Ash Brick Unit"
company_address = "Your address"
company_contact = "99999 99999"
company_gst = "GSTIN"
brand_color = "#1F4E79"
logo_base64 = "BASE64_STRING"
signature_base64 = "BASE64_STRING"
font_ttf_base64 = "BASE64_STRING"
watermark_text = "Fly-Ash Brick Unit"
upi_id = "your@upi"
bank_name = "Bank Name"
account_no = "1234567890"
ifsc = "IFSC0000"
payment_label = "Payment Details"
payment_note = "Pay within 7 days."
qr_data = ""
terms = "Goods once sold will not be taken back."
```

To get base64:
```
python - <<'PY'
import base64
with open("logo.png", "rb") as f:
    print(base64.b64encode(f.read()).decode())
PY
```

For Hindi/Unicode text, use a font such as **NotoSansDevanagari.ttf**:
```
python - <<'PY'
import base64
with open("NotoSansDevanagari-Regular.ttf", "rb") as f:
    print(base64.b64encode(f.read()).decode())
PY
```

## Run the app
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start Streamlit:
   - `streamlit run app.py`

## ID formats
- Customers: `CUST-FIRST-LAST-001`
- Suppliers: `SUP-FIRST-LAST-001`
- Labour: `LAB-FIRST-LAST-001`
- Logs (RM/PROD/SAL/PAY/ATT): `PREFIX-dd-mm-yy-HHMMSS-001`

## Optional: auto-generate IDs for manual sheet entry
If you add rows directly in Google Sheets, you can use Apps Script to
auto-fill IDs or rebuild them for all historical records.
Open Extensions -> Apps Script, paste the script below, and save it.

```javascript
const ID_RULES = {
  Suppliers: { idCol: 1, type: "named", prefix: "SUP", nameCol: 2 },
  Customers: { idCol: 1, type: "named", prefix: "CUST", nameCol: 2 },
  Labour: { idCol: 1, type: "named", prefix: "LAB", nameCol: 2 },
  Raw_Material_Log: { idCol: 1, type: "log", prefix: "RM", dateCol: 2 },
  Production_Log: { idCol: 1, type: "log", prefix: "PROD", dateCol: 2 },
  Sales_Log: { idCol: 1, type: "log", prefix: "SAL", dateCol: 2 },
  Payments: { idCol: 1, type: "log", prefix: "PAY", dateCol: 2 },
  Labour_Attendance: { idCol: 1, type: "log", prefix: "ATT", dateCol: 2 },
};

function onEdit(e) {
  const sheet = e.range.getSheet();
  const rule = ID_RULES[sheet.getName()];
  if (!rule) return;
  const row = e.range.getRow();
  if (row === 1) return;
  const idCell = sheet.getRange(row, rule.idCol);
  if (idCell.getValue()) return;

  const rowValues = sheet.getRange(row, 1, 1, sheet.getLastColumn()).getValues()[0];
  const counters = {};
  idCell.setValue(buildId(rule, rowValues, counters));
}

// Run this to update all IDs (set force=true to rewrite every row).
function normalizeAllIds(force = false) {
  const ss = SpreadsheetApp.getActive();
  Object.keys(ID_RULES).forEach((sheetName) => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    const rule = ID_RULES[sheetName];
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    if (lastRow < 2) return;

    const data = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
    const counters = {};

    // First pass: register existing IDs to keep numbering stable.
    data.forEach((row) => {
      const id = row[rule.idCol - 1];
      if (!id) return;
      const base = getBase(rule, id);
      if (!base) return;
      const suffix = getSuffix(id);
      if (suffix !== null) {
        counters[base] = Math.max(counters[base] || 0, suffix);
      }
    });

    // Second pass: generate IDs.
    data.forEach((row) => {
      const id = row[rule.idCol - 1];
      if (id && !force) return;
      row[rule.idCol - 1] = buildId(rule, row, counters);
    });

    sheet.getRange(2, 1, data.length, lastCol).setValues(data);
  });
}

function buildId(rule, rowValues, counters) {
  if (rule.type === "named") {
    const name = rowValues[rule.nameCol - 1];
    const base = `${rule.prefix}-${nameToken(name, 0)}-${nameToken(name, -1)}`;
    const next = nextCounter(base, counters);
    return `${base}-${pad3(next)}`;
  }
  const dateValue = rowValues[rule.dateCol - 1];
  const datePart = formatDatePart(dateValue);
  const base = `${rule.prefix}-${datePart}`;
  const next = nextCounter(base, counters);
  const timePart = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "HHmmss");
  return `${base}-${timePart}-${pad3(next)}`;
}

function nameToken(value, index) {
  const cleaned = String(value || "")
    .replace(/[^A-Za-z0-9 ]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter((t) => t);
  if (!cleaned.length) return "NAME";
  const token = index === 0 ? cleaned[0] : cleaned[cleaned.length - 1];
  return token.toUpperCase();
}

function formatDatePart(value) {
  const date = value instanceof Date ? value : new Date(value);
  return Utilities.formatDate(date, Session.getScriptTimeZone(), "dd-MM-yy");
}

function nextCounter(base, counters) {
  const next = (counters[base] || 0) + 1;
  counters[base] = next;
  return next;
}

function getSuffix(id) {
  const parts = String(id || "").split("-");
  const last = parts[parts.length - 1];
  return /^\d+$/.test(last) ? parseInt(last, 10) : null;
}

function getBase(rule, id) {
  const parts = String(id || "").split("-");
  if (rule.type === "named" && parts.length >= 3) {
    return parts.slice(0, 3).join("-");
  }
  if (rule.type === "log" && parts.length >= 4) {
    return parts.slice(0, 4).join("-");
  }
  return "";
}

function pad3(value) {
  return String(value).padStart(3, "0");
}
```