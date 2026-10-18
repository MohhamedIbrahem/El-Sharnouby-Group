"""
Shared metric helpers for computing REAL period-over-period deltas.

All deltas compare the trailing 12-month window against the previous
12-month window, anchored at the latest month present in the data
(all datasets span Oct 2023 → Sep 2026 = 36 months).
Windows shorter than 24 months return None (delta row is hidden).
"""
from typing import Optional
import pandas as pd

from app.core.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_WINDOW = 12


def _month_period(df: pd.DataFrame, date_col: str) -> pd.Series:
    """Monthly period series from a datetime column."""
    return pd.to_datetime(df[date_col], errors="coerce").dt.to_period("M")


def _window_means(series: pd.Series, months: int = DEFAULT_WINDOW) -> tuple[Optional[float], Optional[float]]:
    """Mean of the last `months` entries vs the `months` entries before them."""
    s = series.dropna().sort_index()
    if len(s) < months * 2:
        return None, None
    last = s.iloc[-months:]
    prev = s.iloc[-months * 2:-months]
    return float(last.mean()), float(prev.mean())


def _window_sums(series: pd.Series, months: int = DEFAULT_WINDOW) -> tuple[Optional[float], Optional[float]]:
    """Sum of the last `months` entries vs the `months` entries before them."""
    s = series.dropna().sort_index()
    if len(s) < months * 2:
        return None, None
    last = s.iloc[-months:]
    prev = s.iloc[-months * 2:-months]
    return float(last.sum()), float(prev.sum())


def _pct_change(last: Optional[float], prev: Optional[float]) -> Optional[float]:
    if last is None or prev is None or prev == 0:
        return None
    return (last - prev) / abs(prev) * 100


def _pp_change(last: Optional[float], prev: Optional[float]) -> Optional[float]:
    if last is None or prev is None:
        return None
    return last - prev


def pct_change_sum(
    df: pd.DataFrame, value_col: str, date_col: str, months: int = DEFAULT_WINDOW
) -> Optional[float]:
    """% change of a summed value: trailing window vs previous window."""
    if df.empty or value_col not in df.columns or date_col not in df.columns:
        return None
    monthly = df.groupby(_month_period(df, date_col))[value_col].sum()
    return _pct_change(*_window_sums(monthly, months))


def pct_change_count(
    df: pd.DataFrame, date_col: str, months: int = DEFAULT_WINDOW, mask: Optional[pd.Series] = None
) -> Optional[float]:
    """% change of the row count (optionally filtered by a boolean mask)."""
    if df.empty or date_col not in df.columns:
        return None
    sub = df if mask is None else df.loc[mask]
    if sub.empty:
        return None
    monthly = sub.groupby(_month_period(sub, date_col)).size()
    return _pct_change(*_window_sums(monthly, months))


def pp_change_ratio(
    df: pd.DataFrame,
    numerator_col: str,
    denominator_col: str,
    date_col: str,
    months: int = DEFAULT_WINDOW,
) -> Optional[float]:
    """
    Delta in percentage points of a monthly ratio (e.g. Passed/Inspected yield,
    OTIF rate, margin). Ratio is computed month-by-month, then the average of
    the trailing window is compared to the average of the previous window.
    """
    if df.empty or any(c not in df.columns for c in (numerator_col, denominator_col, date_col)):
        return None
    denom = pd.to_numeric(df[denominator_col], errors="coerce").mask(
        df[denominator_col] == 0
    )
    numer = pd.to_numeric(df[numerator_col], errors="coerce")
    ratio = numer / denom
    monthly = ratio.groupby(_month_period(df, date_col)).mean()
    return _pp_change(*_window_means(monthly, months))


def pp_change_mean(
    df: pd.DataFrame, value_col: str, date_col: str, months: int = DEFAULT_WINDOW
) -> Optional[float]:
    """Delta of the mean of a value (e.g. efficiency %, days of cover) between windows."""
    if df.empty or value_col not in df.columns or date_col not in df.columns:
        return None
    monthly = pd.to_numeric(df[value_col], errors="coerce").groupby(_month_period(df, date_col)).mean()
    return _pp_change(*_window_means(monthly, months))


def pct_change_mean(
    df: pd.DataFrame, value_col: str, date_col: str, months: int = DEFAULT_WINDOW
) -> Optional[float]:
    """% change of the window-mean of a value (e.g. average lead time in days)."""
    if df.empty or value_col not in df.columns or date_col not in df.columns:
        return None
    monthly = pd.to_numeric(df[value_col], errors="coerce").groupby(_month_period(df, date_col)).mean()
    return _pct_change(*_window_means(monthly, months))


def pct_change_ratio_windowed(
    df: pd.DataFrame,
    numerator_col: str,
    denominator_col: str,
    date_col: str,
    months: int = DEFAULT_WINDOW,
    denominator_agg: str = "sum",
) -> Optional[float]:
    """
    % change of a window-level ratio (e.g. CAC: total spend / total orders,
    basket size: revenue / invoices). More accurate than averaging monthly ratios.
    denominator_agg: aggregation for the denominator ("sum" or "nunique").
    """
    if df.empty or any(c not in df.columns for c in (numerator_col, denominator_col, date_col)):
        return None

    periods = _month_period(df, date_col)
    # pandas 3.0 string dtype: agg("sum") on a non-numeric column concatenates
    # strings instead of counting — force numeric first.
    num_monthly = (
        pd.to_numeric(df[numerator_col], errors="coerce").groupby(periods).sum()
    )
    if denominator_agg == "nunique":
        den_monthly = df[denominator_col].groupby(periods).nunique()
    elif pd.api.types.is_numeric_dtype(df[denominator_col]):
        den_monthly = (
            pd.to_numeric(df[denominator_col], errors="coerce").groupby(periods).sum()
        )
    else:
        # Non-numeric denominator (e.g. string Invoice_ID): count occurrences
        den_monthly = df[denominator_col].groupby(periods).count()

    monthly = pd.concat([num_monthly.rename("num"), den_monthly.rename("den")], axis=1).dropna()
    monthly = monthly.mask(monthly == 0)  # avoid /0; keeps float dtype
    denom = monthly["den"]
    ratio = monthly["num"] / denom
    return _pct_change(*_window_means(ratio, months))
