"""
Inventory & Demand Planning Service (Task 9)
ABC/XYZ matrix classification, Days of Cover, Stockout risk, Demand forecasting.
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from typing import Optional
from app.core.models import KPICard, ChartData
from app.ai.forecasting import forecast_demand
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED, ACCENT_GREEN, PALETTE
)
from app.core.metrics import pct_change_sum, pct_change_count, pct_change_mean
from app.core.logger import setup_logger, log_function

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)

# ── Computed-once cache (DATA is loaded once at startup and never mutates) ──
_ABC_XYZ_CACHE: Optional[pd.DataFrame] = None


def get_inventory_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Inventory & Demand Planning."""
    inv = data.get("Inventory_History", pd.DataFrame())

    closing_stock = inv["Closing_Stock"].sum() if not inv.empty and "Closing_Stock" in inv.columns else 0
    avg_doc = inv["Days_of_Cover"].median() if not inv.empty and "Days_of_Cover" in inv.columns else 0.0
    stockout_skus = (
        inv.loc[inv["Stockout_Days_In_Month"] > 0, "Product_ID"].nunique()
        if not inv.empty and {"Stockout_Days_In_Month", "Product_ID"}.issubset(inv.columns) else 0
    )
    overstock_skus = (
        inv.loc[inv["Days_of_Cover"] > 90, "Product_ID"].nunique()
        if not inv.empty and {"Days_of_Cover", "Product_ID"}.issubset(inv.columns) else 0
    )

    # Annualized turnover = trailing-12-month units sold ÷ average monthly total
    # stock. (36 months of sales ÷ per-row stock mean overstated it ~500x.)
    turnover = 0.0
    if not inv.empty and {"Snapshot_Month", "Sold_Qty", "Closing_Stock"}.issubset(inv.columns):
        monthly = (
            inv.assign(_Month=pd.to_datetime(inv["Snapshot_Month"], errors="coerce").dt.to_period("M"))
            .groupby("_Month")
            .agg(sold=("Sold_Qty", "sum"), stock=("Closing_Stock", "sum"))
            .sort_index()
            .tail(12)
        )
        avg_stock = float(monthly["stock"].mean())
        if avg_stock > 0:
            turnover = float(monthly["sold"].sum() / avg_stock)

    # REAL deltas: latest 12 snapshots vs the previous 12 snapshots
    stock_delta = pct_change_sum(inv, "Closing_Stock", "Snapshot_Month") if not inv.empty else None
    doc_delta = pct_change_mean(inv, "Days_of_Cover", "Snapshot_Month") if not inv.empty else None
    stockout_delta = (
        # ponytail: stockout/overstock deltas stay row-count trends; values are unique products.
        pct_change_count(inv, "Snapshot_Month", mask=inv["Stockout_Days_In_Month"] > 0)
        if not inv.empty and "Stockout_Days_In_Month" in inv.columns else None
    )
    overstock_delta = (
        pct_change_count(inv, "Snapshot_Month", mask=inv["Days_of_Cover"] > 90)
        if not inv.empty and "Days_of_Cover" in inv.columns else None
    )

    return [
        KPICard(
            title="Units in Stock",
            value=format_number_ar(closing_stock),
            raw_value=float(closing_stock),
            delta=round(stock_delta, 1) if stock_delta is not None else None,
            delta_label=PERIOD_LABEL,
            neutral_delta=True,
            color="orange"
        ),
        KPICard(
            title="Average Days of Cover",
            value=f"{avg_doc:.0f} days",
            raw_value=float(avg_doc),
            delta=round(doc_delta, 1) if doc_delta is not None else None,
            delta_label=PERIOD_LABEL,
            neutral_delta=True,
            color="teal"
        ),
        KPICard(
            title="Stockout-Risk Products",
            value=f"{stockout_skus:,.0f} SKUs",
            raw_value=float(stockout_skus),
            delta=round(stockout_delta, 1) if stockout_delta is not None else None,
            delta_label=PERIOD_LABEL,
            favorable=False,
            color="navy"
        ),
        KPICard(
            title="Overstocked Items",
            value=f"{overstock_skus:,.0f} SKUs",
            raw_value=float(overstock_skus),
            delta=round(overstock_delta, 1) if overstock_delta is not None else None,
            delta_label=PERIOD_LABEL,
            favorable=False,
            color="orange"
        ),
        KPICard(
            title="Inventory Turnover",
            value=f"{turnover:.1f}x",
            raw_value=float(turnover),
            delta=None,
            delta_label="Annualized, trailing 12 months",
            color="teal"
        ),
    ]

@log_function
def classify_abc_xyz(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Classifies SKUs into ABC (Revenue) and XYZ (Demand Volatility). Cached after first run."""
    global _ABC_XYZ_CACHE
    if _ABC_XYZ_CACHE is not None:
        return _ABC_XYZ_CACHE.copy()

    sales = data.get("Sales_Transactions", pd.DataFrame())
    if sales.empty or "Product_ID" not in sales.columns:
        return pd.DataFrame()

    sku_rev = sales.groupby("Product_ID").agg(
        Revenue=("Net_Sales_EGP", "sum"),
        Units=("Quantity", "sum")
    ).reset_index().sort_values("Revenue", ascending=False)

    sku_rev["Cum_Rev"] = sku_rev["Revenue"].cumsum()
    tot_rev = sku_rev["Revenue"].sum()
    sku_rev["Cum_Pct"] = (sku_rev["Cum_Rev"] / tot_rev * 100) if tot_rev > 0 else 100

    sku_rev["ABC"] = pd.cut(
        sku_rev["Cum_Pct"],
        bins=[-1, 80, 95, 101],
        labels=["A", "B", "C"]
    )

    if "Year_Month" in sales.columns:
        m_sales = sales.groupby(["Product_ID", "Year_Month"])["Quantity"].sum().unstack(fill_value=0)
        cv = m_sales.std(axis=1) / (m_sales.mean(axis=1) + 1e-5)
        cv_df = cv.reset_index()
        cv_df.columns = ["Product_ID", "CV"]

        sku_rev = sku_rev.merge(cv_df, on="Product_ID", how="left")
        sku_rev["XYZ"] = pd.cut(
            sku_rev["CV"].fillna(1.0),
            bins=[-1, 0.5, 1.0, 999],
            labels=["X", "Y", "Z"]
        )
    else:
        sku_rev["XYZ"] = "Y"

    sku_rev["ABC_XYZ"] = sku_rev["ABC"].astype(str) + sku_rev["XYZ"].astype(str)
    _ABC_XYZ_CACHE = sku_rev.copy()
    return sku_rev

@log_function
def get_abc_xyz_matrix(data: dict[str, pd.DataFrame]) -> ChartData:
    """3x3 Heatmap showing SKU distribution and value across AX to CZ."""
    matrix_df = classify_abc_xyz(data)
    fig = go.Figure()

    if not matrix_df.empty:
        grid = matrix_df.groupby(["ABC", "XYZ"], observed=False).agg(
            SKU_Count=("Product_ID", "count"),
            Value=("Revenue", "sum")
        ).reset_index()

        p_counts = grid.pivot(index="ABC", columns="XYZ", values="SKU_Count").fillna(0)
        p_vals = grid.pivot(index="ABC", columns="XYZ", values="Value").fillna(0)

        p_counts = p_counts.reindex(index=["A", "B", "C"], columns=["X", "Y", "Z"]).fillna(0)
        p_vals = p_vals.reindex(index=["A", "B", "C"], columns=["X", "Y", "Z"]).fillna(0)

        text_grid = []
        for r in ["A", "B", "C"]:
            row_t = []
            for c in ["X", "Y", "Z"]:
                cnt = int(p_counts.loc[r, c])
                v = p_vals.loc[r, c]
                row_t.append(f"{cnt} SKUs<br>{format_currency_ar(v)}")
            text_grid.append(row_t)

        fig.add_trace(go.Heatmap(
            z=p_vals.values / 1000,
            x=["X (Stable demand)", "Y (Moderate variation)", "Z (Erratic demand)"],
            y=["A (80% of value)", "B (15% of value)", "C (5% of value)"],
            text=text_grid,
            texttemplate="%{text}",
            colorscale="YlOrBr",
            hovertemplate="Class: <b>%{y} / %{x}</b><br>Total value: %{z:,.1f}K EGP<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_abc_xyz_matrix",
        title="ABC/XYZ Inventory Matrix",
        height=400,
        description="Financial importance crossed with demand-pattern stability to drive purchasing and stocking strategies"
    )

@log_function
def get_stock_turns(data: dict[str, pd.DataFrame]) -> ChartData:
    """Bar chart: Turnover ratio by location."""
    inv = data.get("Inventory_History", pd.DataFrame())
    fig = go.Figure()

    if not inv.empty and "Location_Name" in inv.columns and "Sold_Qty" in inv.columns and "Closing_Stock" in inv.columns:
        loc = inv.groupby("Location_Name").agg(
            Sold=("Sold_Qty", "sum"),
            Stock=("Closing_Stock", "mean")
        ).reset_index()
        loc["Turnover"] = (loc["Sold"] / loc["Stock"].clip(lower=1)).round(1)

        fig.add_trace(go.Bar(
            x=loc["Location_Name"],
            y=loc["Turnover"],
            marker_color=SECONDARY_TEAL,
            text=loc["Turnover"].apply(lambda v: f"{v:.1f}x"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Turnover: %{y:.1f}x<extra></extra>"
        ))
        fig.update_layout(yaxis=dict(title="Annual Turnover"))

    return create_chart_data(
        fig,
        chart_id="chart_stock_turns",
        title="Inventory Turnover by Branch & Warehouse",
        height=380,
        description="How quickly goods sell through and are replenished at each logistics location"
    )

@log_function
def get_days_of_cover(data: dict[str, pd.DataFrame]) -> ChartData:
    """Box plot of Days of Cover across locations."""
    inv = data.get("Inventory_History", pd.DataFrame())
    fig = go.Figure()

    if not inv.empty and "Location_Name" in inv.columns and "Days_of_Cover" in inv.columns:
        for loc in inv["Location_Name"].unique()[:5]:
            sub = inv[inv["Location_Name"] == loc]
            fig.add_trace(go.Box(
                y=sub["Days_of_Cover"].clip(upper=120),
                name=str(loc),
                marker_color=PRIMARY_ORANGE,
                boxmean=True
            ))
        fig.update_layout(yaxis=dict(title="Days of Cover"))

    return create_chart_data(
        fig,
        chart_id="chart_days_of_cover_box",
        title="Days of Cover Spread Across Locations",
        height=380,
        description="Distribution of stock-sufficiency periods, exposing overstock or severe shortage"
    )

@log_function
def get_stockout_overstock(data: dict[str, pd.DataFrame]) -> ChartData:
    """Scatter: Days of Cover vs Closing Stock identifying critical risks."""
    inv = data.get("Inventory_History", pd.DataFrame())
    fig = go.Figure()

    if not inv.empty and "Days_of_Cover" in inv.columns and "Closing_Stock" in inv.columns:
        sample_df = inv.sample(min(500, len(inv)), random_state=42)

        colors = [ACCENT_RED if doc < 15 else (SECONDARY_TEAL if doc > 90 else ACCENT_GREEN) for doc in sample_df["Days_of_Cover"]]

        fig.add_trace(go.Scatter(
            x=sample_df["Closing_Stock"],
            y=sample_df["Days_of_Cover"],
            mode="markers",
            marker=dict(size=8, color=colors, opacity=0.7),
            hovertemplate="Stock on hand: %{x:,} units<br>Days of cover: %{y:.0f} days<extra></extra>"
        ))
        fig.add_hline(y=15, line_dash="dash", line_color=ACCENT_RED, annotation_text="Risk threshold (stockout)", annotation_position="top left")
        fig.add_hline(y=90, line_dash="dash", line_color=SECONDARY_TEAL, annotation_text="Overstock", annotation_position="top left")
        fig.update_layout(
            xaxis=dict(title="Stock on Hand (units)"),
            yaxis=dict(title="Days of Cover")
        )

    return create_chart_data(
        fig,
        chart_id="chart_stockout_risk_scatter",
        title="Stockout vs Overstock Risk Map",
        height=380,
        description="Red points are items at risk of stockout, orange marks overstocked capital, and green is healthy coverage"
    )

@log_function
def get_demand_forecast(data: dict[str, pd.DataFrame], horizons: list = [30, 60, 90]) -> ChartData:
    """Historical demand + 90-day AI forecast with confidence intervals."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Order_Date" in sales.columns and "Quantity" in sales.columns:
        hist_weekly = sales.groupby(pd.Grouper(key="Order_Date", freq="W-MON"))["Quantity"].sum().reset_index().tail(20)

        fig.add_trace(go.Scatter(
            x=hist_weekly["Order_Date"],
            y=hist_weekly["Quantity"],
            mode="lines+markers",
            name="Actual historical demand",
            line=dict(color=DARK_NAVY, width=2.5),
            hovertemplate="<b>Historical</b>: %{x|%Y-%m-%d}<br>Demand: %{y:,} units<extra></extra>"
        ))

        fc = forecast_demand(sales, horizon_days=90)
        if not fc.empty:
            fig.add_trace(go.Scatter(
                x=fc["Date"],
                y=fc["Upper_Bound"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="none"
            ))
            fig.add_trace(go.Scatter(
                x=fc["Date"],
                y=fc["Lower_Bound"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(232, 114, 12, 0.15)",
                name="95% confidence band",
                hoverinfo="none"
            ))
            fig.add_trace(go.Scatter(
                x=fc["Date"],
                y=fc["Forecast"],
                mode="lines+markers",
                name="AI forecast",
                line=dict(color=PRIMARY_ORANGE, width=3, dash="dash"),
                hovertemplate="<b>Forecast</b>: %{x|%Y-%m-%d}<br>Expected: %{y:,.0f} units<extra></extra>"
            ))

        fig.update_layout(yaxis=dict(title="Demand (units)"))

    return create_chart_data(
        fig,
        chart_id="chart_ai_demand_forecast",
        title="AI Demand Forecast (Next 90 Days)",
        height=400,
        description="Weekly demand forecast model with a 95% confidence interval"
    )
