"""
Core Data Loader — Loads all 20 CSV files at startup, cleans, and type-casts.
The global DATA dict is accessible by all services.
"""
import pandas as pd
from pathlib import Path
from typing import Optional
from app.core.logger import setup_logger, log_function

logger = setup_logger(__name__)

# Global data store — populated on startup
DATA: dict[str, pd.DataFrame] = {}


# ── Column dtype specifications ──────────────────────────────────

DATE_COLUMNS = {
    "Sales_Transactions": ["Order_Date", "Return_Date"],
    "Customers": ["Join_Date"],
    "Quality": ["Inspection_Date"],
    "Customer_Service": ["Open_Date"],
    "Inventory_History": ["Snapshot_Month"],
    "Purchase_Orders": ["Order_Date", "Promised_Date", "Actual_Receipt_Date"],
    "Machine_Downtime": ["Date"],
    "Marketing": ["Start_Date", "End_Date"],
    "Printing_Batches": ["Print_Date"],
    "Production_Orders": ["Start_Date", "Due_Date", "Completion_Date"],
    "Web_Traffic_Daily": ["Date"],
    "Group_Operations": ["Month"],
}

CATEGORY_COLUMNS = {
    "Sales_Transactions": [
        "Channel", "Customer_Type", "Customer_Governorate",
        "Product_Family", "Size", "Payment_Method", "Returned",
        "Return_Reason", "Quality_Related_Return",
    ],
    "Customers": [
        "Customer_Type", "Governorate", "Age_Band",
        "Gender", "Acquisition_Channel", "Consent_Status",
    ],
    "Quality": ["Stage", "Defect_Type", "Root_Cause"],
    "Customer_Service": ["Channel", "Issue_Type", "Resolved"],
    "Inventory_History": ["Location_Name"],
    "Purchase_Orders": ["Material_Name", "Unit"],
    "Machine_Downtime": ["Business_Area", "Reason", "Planned"],
    "Marketing": ["Platform"],
    "Printing_Batches": ["Print_Type", "Defect_Type"],
    "Production_Orders": ["Line_ID", "Primary_Bottleneck"],
    "Product_Master": [
        "Brand", "Product_Family", "Gender",
        "Audience", "Catalog_Season",
    ],
    "Suppliers": ["Primary_Category", "Governorate", "Contracted"],
    "Materials": ["Unit", "Material_Category"],
    "Locations": ["Location_Type", "Channel", "Governorate"],
    "Business_Units": ["Function"],
}

NUMERIC_COLUMNS = {
    "Sales_Transactions": [
        "Quantity", "List_Price_EGP", "Discount_Pct",
        "Gross_Sales_EGP", "Net_Sales_EGP", "Estimated_COGS_EGP",
        "Gross_Profit_EGP", "Gross_Margin_Pct", "Refund_Value_EGP",
    ],
    "Quality": [
        "Inspected_Qty", "Passed_Qty", "Rejected_Qty", "Estimated_Loss_EGP",
    ],
    "Customer_Service": [
        "First_Response_Minutes", "Resolution_Hours", "CSAT_1_to_5",
    ],
    "Inventory_History": [
        "Opening_Stock", "Received_Qty", "Sold_Qty", "Returned_Qty",
        "Damaged_Qty", "Closing_Stock", "Avg_Daily_Sales_90D",
        "Safety_Stock_Units", "Reorder_Point_Units",
        "Supplier_Lead_Time_Days", "Days_of_Cover", "Stockout_Days_In_Month",
    ],
    "Purchase_Orders": [
        "Ordered_Qty", "Unit_Cost_EGP", "Accepted_Qty", "Rejected_Qty",
    ],
    "Machine_Downtime": ["Downtime_Hours"],
    "Marketing": [
        "Spend_EGP", "Impressions", "Clicks",
        "Landing_Page_Sessions", "Orders_Attributed",
        "Attributed_Revenue_EGP", "Discount_Pct",
    ],
    "Printing_Batches": [
        "Planned_Qty", "Printed_Qty", "Good_Qty", "Rejected_Qty",
        "Reprint_Qty", "Ink_or_Consumable_Cost_EGP", "Rework_Cost_EGP",
    ],
    "Production_Orders": [
        "Planned_Qty", "Produced_Qty", "Good_Qty", "Rejected_Qty",
        "Efficiency_Pct", "Delay_Days", "Overtime_Hours",
    ],
    "Web_Traffic_Daily": [
        "Sessions", "Users", "New_User_Pct", "Mobile_Pct",
        "Add_To_Cart_Rate", "Checkout_Rate", "Orders",
        "Conversion_Rate", "Avg_Page_Load_Sec",
    ],
    "Group_Operations": [
        "Volume", "Operational_Efficiency_Pct", "Open_Issues_Count",
    ],
    "Product_Master": ["Public_Retail_Price_EGP"],
}


@log_function
def _load_csv(filepath: Path, table_name: str) -> Optional[pd.DataFrame]:
    """Load a single CSV file with proper dtype handling."""
    try:
        df = pd.read_csv(filepath, low_memory=False)
        logger.info(f"  Loaded {table_name}: {len(df):,} rows × {len(df.columns)} cols")

        # Parse date columns
        if table_name in DATE_COLUMNS:
            for col in DATE_COLUMNS[table_name]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")

        # Cast numeric columns
        if table_name in NUMERIC_COLUMNS:
            for col in NUMERIC_COLUMNS[table_name]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

        # Cast category columns
        if table_name in CATEGORY_COLUMNS:
            for col in CATEGORY_COLUMNS[table_name]:
                if col in df.columns:
                    df[col] = df[col].astype("category")

        return df

    except Exception as e:
        logger.error(f"  ✗ Failed to load {table_name}: {e}")
        return None


@log_function
def _add_derived_columns(data: dict[str, pd.DataFrame]) -> None:
    """Add pre-computed derived columns used across multiple services."""

    # Sales_Transactions derived columns
    if "Sales_Transactions" in data:
        df = data["Sales_Transactions"]
        if "Order_Date" in df.columns:
            df["Year"] = df["Order_Date"].dt.year
            df["Month"] = df["Order_Date"].dt.month
            df["Quarter"] = df["Order_Date"].dt.quarter
            df["Month_Name"] = df["Order_Date"].dt.month_name()
            df["Year_Month"] = df["Order_Date"].dt.to_period("M").astype(str)
        if "Returned" in df.columns:
            df["Is_Return"] = df["Returned"].astype(str).str.strip().str.lower() == "yes"
        logger.info("  Added Sales_Transactions derived columns: Year, Month, Quarter, Is_Return")

    # Production_Orders derived columns
    if "Production_Orders" in data:
        df = data["Production_Orders"]
        if "Delay_Days" in df.columns:
            df["Is_Delayed"] = df["Delay_Days"] > 0
        logger.info("  Added Production_Orders derived column: Is_Delayed")

    # Purchase_Orders derived columns
    if "Purchase_Orders" in data:
        df = data["Purchase_Orders"]
        if "Actual_Receipt_Date" in df.columns and "Promised_Date" in df.columns:
            df["Days_Late"] = (df["Actual_Receipt_Date"] - df["Promised_Date"]).dt.days
        logger.info("  Added Purchase_Orders derived column: Days_Late")


@log_function
def _validate_data(data: dict[str, pd.DataFrame]) -> None:
    """Log summary statistics and null counts for key columns."""
    logger.info("=" * 60)
    logger.info("DATA VALIDATION SUMMARY")
    logger.info("=" * 60)

    key_columns = {
        "Sales_Transactions": ["Order_Date", "Net_Sales_EGP", "Gross_Profit_EGP"],
        "Customers": ["Customer_ID", "Join_Date"],
        "Quality": ["Inspection_Date", "Defect_Type"],
        "Production_Orders": ["Start_Date", "Efficiency_Pct"],
    }

    for table_name, df in data.items():
        null_info = ""
        if table_name in key_columns:
            nulls = {
                col: df[col].isna().sum()
                for col in key_columns[table_name]
                if col in df.columns and df[col].isna().sum() > 0
            }
            if nulls:
                null_info = f" | Nulls: {nulls}"
        logger.info(f"  {table_name}: {len(df):>8,} rows{null_info}")

    logger.info("=" * 60)


@log_function
def load_all_data(data_dir: Path) -> dict[str, pd.DataFrame]:
    """
    Load all 20 CSV files from the data directory.
    Returns a dict mapping table names to DataFrames.
    """
    logger.info(f"Loading data from: {data_dir}")
    data: dict[str, pd.DataFrame] = {}

    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return data

    csv_files = sorted(data_dir.glob("*.csv"))
    logger.info(f"Found {len(csv_files)} CSV files")

    for csv_path in csv_files:
        table_name = csv_path.stem  # filename without extension
        df = _load_csv(csv_path, table_name)
        if df is not None:
            data[table_name] = df

    # Add derived columns
    _add_derived_columns(data)

    # Validate
    _validate_data(data)

    logger.info(f"Data loading complete: {len(data)} tables loaded")
    return data
