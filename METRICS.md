# Metrics & KPI Reference (Dashboard)

This document lists each metric/KPI shown in the app, its meaning, formula,
and the Google Sheet columns used. All calculations respect the selected
**Data scope** in the Dashboard (Full data / FY / last 6 months / etc.).

> **Units rule:**  
> - Cement quantities are **bags** (50 kg per bag).  
> - Fly Ash and Stone Dust quantities are **tons**.  
> - Production consumption fields:  
>   - `Cement_Consumption` = bags  
>   - `FlyAsh_Consumption` = tons  
>   - `StoneDust_Consumption` = tons  

---

## 1) Top KPI tiles

### Total Production
- **Meaning:** Total bricks produced in the selected scope.
- **Formula:** `SUM(Production_Log.No_of_Bricks)`
- **Sheet/Columns:** `Production_Log` → `No_of_Bricks`

### Total Sales
- **Meaning:** Total sales value (base amount) in the selected scope.
- **Formula:** `SUM(Sales_Log.Amount)`
- **Sheet/Columns:** `Sales_Log` → `Amount`

### Raw Material Cost
- **Meaning:** Total raw material cost in the selected scope.
- **Formula:** `SUM(Raw_Material_Log.Total_Cost)`
- **Sheet/Columns:** `Raw_Material_Log` → `Total_Cost`

### Labour Cost
- **Meaning:** Total labour expense in the selected scope.
- **Formula:** `SUM(Production_Log.Labour_Expense)`
- **Sheet/Columns:** `Production_Log` → `Labour_Expense`

### Operational Expense
- **Meaning:** Total non-production general expenses in the selected scope.
- **Formula:** `SUM(Expenses.Amount)`
- **Sheet/Columns:** `Expenses` → `Amount`

### Profit
- **Meaning:** Sales minus all major operating costs.
- **Formula:** `Total Sales - (Raw Material Cost + Labour Cost + Operational Expense)`
- **Sheet/Columns:** Uses metrics above.

### Available Brick Stock
- **Meaning:** Current bricks available from production minus sales.
- **Formula:** `SUM(Production_Log.No_of_Bricks) - SUM(Sales_Log.No_of_Bricks)`
- **Sheet/Columns:** `Production_Log.No_of_Bricks`, `Sales_Log.No_of_Bricks`

### Avg Selling Price
- **Meaning:** Average price per brick (excl. freight).
- **Formula:** `Total Sales / SUM(Sales_Log.No_of_Bricks)`
- **Sheet/Columns:** `Sales_Log.Amount`, `Sales_Log.No_of_Bricks`

### Collection Ratio
- **Meaning:** Cash collection efficiency.
- **Formula:** `SUM(Sales_Log.Amount_Received) / SUM(Sales_Log.Amount)`
- **Sheet/Columns:** `Sales_Log.Amount_Received`, `Sales_Log.Amount`

### Production Entries
- **Meaning:** Number of production rows (logs) in the selected scope.
- **Formula:** `COUNT(Production_Log rows)`
- **Sheet/Columns:** `Production_Log`

### Production Days
- **Meaning:** Unique production dates in the selected scope.
- **Formula:** `COUNT_DISTINCT(Production_Log.Date)`
- **Sheet/Columns:** `Production_Log.Date`

---

## 2) Cost & Profit Summary table

### Cement Used
- **Quantity:** `SUM(Production_Log.Cement_Consumption)` (bags)
- **Rate:** average `Raw_Material_Log.Material_Rate` for Cement  
- **Amount:** `Quantity * Rate`
- **Sheets:** `Production_Log`, `Raw_Material_Log`

### Fly Ash Used
- **Quantity:** `SUM(Production_Log.FlyAsh_Consumption)` (tons)
- **Rate:** average `Raw_Material_Log.Material_Rate` for Fly Ash  
- **Amount:** `Quantity * Rate`

### Stone Dust Used
- **Quantity:** `SUM(Production_Log.StoneDust_Consumption)` (tons)
- **Rate:** average `Raw_Material_Log.Material_Rate` for Stone Dust  
- **Amount:** `Quantity * Rate`

### Labour Cost
- **Quantity:** `SUM(Production_Log.No_of_Bricks)` (bricks)
- **Rate:** `Total Labour Cost / Total Production`
- **Amount:** `SUM(Production_Log.Labour_Expense)`

### Total Production Cost
- **Formula:** `Raw Material Cost + Labour Cost + Operational Expense`

### Sales Value
- **Quantity:** `SUM(Sales_Log.No_of_Bricks)`
- **Rate:** `Total Sales / Total Sold Bricks`
- **Amount:** `Total Sales`

### Total Profit
- **Formula:** `Total Sales - Total Production Cost`

### Expense category split
- **Meaning:** Expense distribution by category (e.g., office, operational, tractor, diesel, machine parts).
- **Formula:** `SUM(Expenses.Amount)` grouped by `Category`
- **Sheet/Columns:** `Expenses` → `Category`, `Amount`

---

## 3) Customer Outstanding & Stock

### Customer Outstanding
- **Meaning:** Cumulative outstanding per customer.
- **Formula:** `SUM(Sales_Log.Amount - Sales_Log.Amount_Received)` per Customer_ID
- **Sheets:** `Sales_Log` → `Amount`, `Amount_Received`, `Customer_ID`

### Stock (Raw Material)
- **Meaning:** Latest stock per material from Stock_Log.
- **Formula:** last known `Stock_Log.Closing` per Material in scope
- **Sheets:** `Stock_Log` → `Closing`, `Date`, `Material`

---

## 4) Production vs Sales (trend tabs)

### Period totals
For the chosen period (Month/Quarter/Year):
- **Production:** `SUM(Production_Log.No_of_Bricks)`
- **Sales:** `SUM(Sales_Log.No_of_Bricks)`

### Gaps / Conversion
- **Gap:** `Production - Sales`
- **Conversion Ratio:** `Sales / Production`

---

## 5) Material Consumption per 1000 Bricks

**Units consistent with logs:**
- Cement = bags  
- Fly Ash = tons  
- Stone Dust = tons  

**Formulas:**
- Cement per 1000 = `(SUM(Cement_Consumption) / SUM(No_of_Bricks)) * 1000`
- Fly Ash per 1000 = `(SUM(FlyAsh_Consumption) / SUM(No_of_Bricks)) * 1000`
- Stone Dust per 1000 = `(SUM(StoneDust_Consumption) / SUM(No_of_Bricks)) * 1000`

---

## 6) Raw Material Reconciliation (page)

### Stock Summary (tons)
For the selected range:
- Cement purchased (tons) = `SUM(Cement Qty bags * 50) / 1000`
- Cement used (tons) = `SUM(Cement_Consumption * 50) / 1000`
- Fly Ash used (tons) = `SUM(FlyAsh_Consumption)`
- Stone Dust used (tons) = `SUM(StoneDust_Consumption)`

### Usage per brick
- Cement: `SUM(Cement_Consumption) / SUM(No_of_Bricks)` (bags/brick)
- Fly Ash: `SUM(FlyAsh_Consumption) / SUM(No_of_Bricks)` (tons/brick)
- Stone Dust: `SUM(StoneDust_Consumption) / SUM(No_of_Bricks)` (tons/brick)

### Standard mix reference
- Cement: 0.20 kg/brick → `0.20 / 50` bags/brick  
  (because 1 bag = 50 kg)
- Fly Ash: 1.70 kg/brick → `1.70 / 1000` tons/brick
- Stone Dust: 1.45 kg/brick → `1.45 / 1000` tons/brick

---

## 7) KPI Diagnostic Report (Dashboard)

Each KPI shows:
- **Value**
- **Ideal range**
- **Status:** Low / Normal / High
- **Meaning:** business interpretation
- **How to improve**

KPI formulas:
- Production to sales ratio = `Total Sold Bricks / Total Production`
- Collection ratio = `SUM(Amount_Received) / SUM(Amount)`
- Profit margin = `Profit / Total Sales`
- Labour cost share = `Total Labour / Total Cost`
- Raw material cost share = `Total Raw Material / Total Cost`
- Operational expense share = `Total Operational Expense / Total Cost`
- Bricks per labour-day = `Total Production / SUM(No_of_Labour)`

---

## How to validate correctness

1. **Check scope:** confirm the selected Data scope (Full data or FY/Last 3/6 months).
2. **Confirm columns:** make sure sheets have correct column names and units.
3. **Spot-check:** take 3–5 rows from each sheet and manually compute totals.
4. **Units:** verify cement is entered in **bags**, fly ash/stone dust in **tons**.
5. **Dates:** ensure Date columns are valid and consistent.
