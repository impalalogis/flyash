import sys
import os
sys.path.append(os.path.dirname(__file__))

import database
import pandas as pd
import utils

# Update Dues for all sales
df = database.read_table('Sales_Log')
print('Before update, Dues sample:', df['Dues'].head(5).tolist())

# Ensure Adjusted_Total_amount is calculated
# First, apply adjusted columns
sales_df = df.copy()
for column in ["Adjusted_Rate", "Adjusted_Amount", "Adjusted_Total_amount"]:
    if column not in sales_df.columns:
        sales_df[column] = ""

empty = pd.Series("", index=sales_df.index, dtype=object)
bricks = utils.to_numeric_series(sales_df.get("Qty", empty)).fillna(0.0)
amount = utils.to_numeric_series(sales_df.get("Amount", empty)).fillna(0.0)
freight = utils.to_numeric_series(sales_df.get("Freight", empty)).fillna(0.0)
gst_source = sales_df.get("GST(%12)")
if gst_source is None:
    gst_source = sales_df.get("Gst (%12)")
if gst_source is None:
    gst_source = sales_df.get("GST", empty)
gst = utils.to_numeric_series(gst_source).fillna(0.0)

adjusted_rate = pd.Series(0.0, index=sales_df.index, dtype=float)
valid_bricks = bricks > 0
adjusted_rate.loc[valid_bricks] = (amount.loc[valid_bricks] + freight.loc[valid_bricks]) / bricks.loc[valid_bricks]
adjusted_amount = adjusted_rate * bricks
adjusted_total = adjusted_amount + gst

sales_df["Adjusted_Rate"] = adjusted_rate.apply(utils.round_down_2)
sales_df["Adjusted_Amount"] = adjusted_amount.apply(utils.round_down_2)
sales_df["Adjusted_Total_amount"] = adjusted_total.apply(utils.round_down_0)

# Recalculate Dues
adjusted_total = utils.to_numeric_series(sales_df.get('Adjusted_Total_amount', pd.Series(dtype=float))).fillna(0.0)
amount_received = utils.to_numeric_series(sales_df.get('Amount_Received', pd.Series(dtype=float))).fillna(0.0)
sales_df['Dues'] = (adjusted_total - amount_received).apply(utils.round_down_2)

database.replace_table('Sales_Log', sales_df)
print('Updated Adjusted columns and Dues for all sales records')