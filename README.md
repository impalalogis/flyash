# flyash

Streamlit application for managing fly-ash brick manufacturing operations using
Google Sheets as a lightweight relational backend.

## Google Sheets setup

### 1) Create the spreadsheet and tabs
Create a Google Sheet and add the following tabs (case-sensitive):

- `Suppliers`
- `Customers`
- `Labour`
- `Raw_Material_Log`
- `Production_Log`
- `Sales_Log`
- `Payments`
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
- Daily_Wage

**Raw_Material_Log**
- RM_ID
- Date
- Month
- Supplier_ID
- Material
- Qty
- Rate
- GST
- Vehicle_No
- Trip_Days
- Route_Expenses
- Diesel
- Driver_Salary
- Vehicle_Charge
- Freight
- Amount_Paid
- Material_Rate
- Total_Cost

**Production_Log**
- Prod_ID
- Date
- Month
- No_of_Bricks
- Cement_Consumption
- FlyAsh_Consumption
- No_of_Labour
- Labour_Expense
- Labour_Payment_Date
- Actual_Payment_Amount

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

## Run the app
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start Streamlit:
   - `streamlit run app.py`

## Optional: auto-generate IDs for manual sheet entry
If you add rows directly in Google Sheets, you can use Apps Script to
auto-fill ID columns. Open Extensions -> Apps Script, paste the script below,
and save it.

```javascript
const ID_CONFIG = {
  Suppliers: { column: 1, prefix: "SUP" },
  Customers: { column: 1, prefix: "CUS" },
  Labour: { column: 1, prefix: "LAB" },
  Raw_Material_Log: { column: 1, prefix: "RM" },
  Production_Log: { column: 1, prefix: "PROD" },
  Sales_Log: { column: 1, prefix: "SAL" },
  Payments: { column: 1, prefix: "PAY" },
};

function onEdit(e) {
  const sheet = e.range.getSheet();
  const config = ID_CONFIG[sheet.getName()];
  if (!config) return;
  const row = e.range.getRow();
  if (row === 1) return;
  const idCell = sheet.getRange(row, config.column);
  if (idCell.getValue()) return;
  idCell.setValue(generateId(config.prefix));
}

function generateId(prefix) {
  const date = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd");
  const token = Utilities.getUuid().replace(/-/g, "").substring(0, 6).toUpperCase();
  return `${prefix}-${date}-${token}`;
}
```