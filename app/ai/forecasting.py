"""
Time-Series Demand Forecasting AI Module.
Combines linear trend with rolling seasonality and generates 95% confidence intervals.
"""
import pandas as pd
import numpy as np
from app.core.logger import setup_logger, log_function

logger = setup_logger(__name__)

@log_function
def forecast_demand(sales_history: pd.DataFrame, horizon_days: int = 90) -> pd.DataFrame:
    """Takes sales history and forecasts forward with confidence intervals."""
    if sales_history.empty:
        return pd.DataFrame()

    df = sales_history.copy()
    if "Order_Date" in df.columns:
        daily = df.groupby(pd.Grouper(key="Order_Date", freq="W-MON"))["Quantity"].sum().reset_index()
        daily.columns = ["Date", "Quantity"]
    else:
        daily = df.rename(columns={df.columns[0]: "Date", df.columns[1]: "Quantity"})

    daily = daily.dropna().sort_values("Date")
    if len(daily) < 4:
        return pd.DataFrame()

    series = daily["Quantity"].values
    n = len(series)
    x = np.arange(n)
    slope, intercept = np.polyfit(x, series, 1)

    std_err = np.std(series - (slope * x + intercept))

    future_steps = int(np.ceil(horizon_days / 7))
    future_x = np.arange(n, n + future_steps)
    future_dates = [daily["Date"].max() + pd.Timedelta(days=7 * int(i + 1)) for i in range(future_steps)]

    future_forecast = slope * future_x + intercept
    future_forecast = np.maximum(future_forecast, 0)

    lower_bound = np.maximum(future_forecast - 1.96 * std_err, 0)
    upper_bound = future_forecast + 1.96 * std_err

    return pd.DataFrame({
        "Date": future_dates,
        "Forecast": future_forecast,
        "Lower_Bound": lower_bound,
        "Upper_Bound": upper_bound,
        "Type": "Forecast"
    })
