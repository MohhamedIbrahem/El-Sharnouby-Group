"""
Customer 360 & Retention Service (Task 7)
RFM analysis, K-Means clustering, cohorts, retention, and geographic demand.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from typing import Optional
from app.core.models import KPICard, ChartData
from app.ai.clustering import compute_rfm_scores, segment_customers_kmeans
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED, PALETTE
)
from app.core.metrics import (
    pct_change_count, pct_change_ratio_windowed,
)
from app.core.logger import setup_logger, log_function

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)

# ── Computed-once cache (DATA is loaded once at startup and never mutates) ──
# Keyed per dataset (identity + shape) so a substituted dataset — e.g. a small
# synthetic frame in tests — cannot be served for the real data in the same process.
_RFM_SEGMENTS_CACHE: Optional[tuple[tuple, pd.DataFrame]] = None


def _get_segmented_rfm(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """RFM + K-Means segmentation computed once per dataset and cached."""
    global _RFM_SEGMENTS_CACHE
    sales = data.get("Sales_Transactions", pd.DataFrame())
    key = (id(data), len(data), sales.shape)
    if (
        _RFM_SEGMENTS_CACHE is not None
        and _RFM_SEGMENTS_CACHE[0] == key
        and not _RFM_SEGMENTS_CACHE[1].empty
    ):
        return _RFM_SEGMENTS_CACHE[1]

    rfm = compute_rfm_scores(sales)
    if not rfm.empty:
        rfm = segment_customers_kmeans(rfm)
    if not rfm.empty:  # empty results stay uncached (cheap to recompute, never poison)
        _RFM_SEGMENTS_CACHE = (key, rfm)
    return rfm


@log_function
def get_customer_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Customer 360."""
    cust = data.get("Customers", pd.DataFrame())
    sales = data.get("Sales_Transactions", pd.DataFrame())

    total_customers = len(cust) if not cust.empty else (sales["Customer_ID"].nunique() if not sales.empty else 0)
    tot_rev = sales["Net_Sales_EGP"].sum() if not sales.empty and "Net_Sales_EGP" in sales.columns else 0.0
    order_col = "Invoice_ID" if "Invoice_ID" in sales.columns else None
    tot_orders = sales[order_col].nunique() if order_col and not sales.empty else len(sales)

    avg_clv = (tot_rev / total_customers) if total_customers > 0 else 0.0
    avg_order_value = (tot_rev / tot_orders) if tot_orders > 0 else 0.0

    # REAL active rate: customers who purchased within the last 365 days
    active_pct = None
    at_risk_pct = None
    rfm = _get_segmented_rfm(data)
    if not rfm.empty and "Recency" in rfm.columns:
        active_pct = float((rfm["Recency"] <= 365).mean() * 100)
        if "Segment" in rfm.columns:
            at_risk_count = rfm["Segment"].str.contains("Risk", case=False).sum()
            at_risk_pct = (at_risk_count / len(rfm) * 100) if len(rfm) > 0 else None

    # REAL deltas: trailing 12-month window vs previous window
    base_delta = pct_change_count(cust, "Join_Date") if not cust.empty else None
    clv_delta = (
        pct_change_ratio_windowed(sales, "Net_Sales_EGP", "Customer_ID", "Order_Date", denominator_agg="nunique")
        if not sales.empty and "Customer_ID" in sales.columns else None
    )
    aov_delta = (
        pct_change_ratio_windowed(sales, "Net_Sales_EGP", order_col, "Order_Date")
        if not sales.empty and order_col else None
    )

    return [
        KPICard(
            title="Total Customer Base",
            value=format_number_ar(total_customers),
            raw_value=float(total_customers),
            delta=round(base_delta, 1) if base_delta is not None else None,
            delta_label="New customers " + PERIOD_LABEL,
            color="orange"
        ),
        KPICard(
            title="Active Customer Rate",
            value=f"{active_pct:.1f}%" if active_pct is not None else "—",
            raw_value=float(active_pct) if active_pct is not None else 0.0,
            delta=None,
            delta_label="Active in the last 365 days",
            color="teal"
        ),
        KPICard(
            title="Average Lifetime Value (CLV)",
            value=format_currency_ar(avg_clv),
            raw_value=float(avg_clv),
            delta=round(clv_delta, 1) if clv_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="navy"
        ),
        KPICard(
            title="Average Order Value (AOV)",
            value=format_currency_ar(avg_order_value),
            raw_value=float(avg_order_value),
            delta=round(aov_delta, 1) if aov_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange"
        ),
        KPICard(
            title="Customers At Risk",
            value=f"{at_risk_pct:.1f}%" if at_risk_pct is not None else "—",
            raw_value=float(at_risk_pct) if at_risk_pct is not None else 0.0,
            delta=None,
            delta_label="AI classification (K-Means)",
            color="teal"
        ),
    ]

@log_function
def get_rfm_scatter(data: dict[str, pd.DataFrame]) -> ChartData:
    """Scatter plot: Recency vs Monetary, bubble size = Frequency, color = Segment."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    segmented = _get_segmented_rfm(data)
    if not segmented.empty:
        sample_df = segmented.sample(min(800, len(segmented)), random_state=42)

        color_map = {
            "Champions": PRIMARY_ORANGE,
            "Loyal Customers": SECONDARY_TEAL,
            "At Risk": ACCENT_RED,
            "Lost": "#64748b",
        }

        for seg, color in color_map.items():
            sub = sample_df[sample_df["Segment"] == seg]
            if not sub.empty:
                fig.add_trace(go.Scatter(
                    x=sub["Recency"],
                    y=sub["Monetary"],
                    mode="markers",
                    name=seg,
                    marker=dict(
                        color=color,
                        size=sub["Frequency"].clip(lower=4, upper=25),
                        opacity=0.7
                    ),
                    hovertemplate="<b>%{data.name}</b><br>Recency: %{x} days<br>Total spend: %{y:,.0f} EGP<extra></extra>"
                ))

        fig.update_layout(
            xaxis=dict(title="Recency of last purchase (days - lower is better)"),
            yaxis=dict(title="Total Spend (EGP)")
        )

    return create_chart_data(
        fig,
        chart_id="chart_rfm_scatter",
        title="AI Customer Segmentation (RFM Matrix)",
        height=400,
        description="Customers classified by recency, frequency, and monetary value with K-Means clustering"
    )

@log_function
def get_customer_segments(data: dict[str, pd.DataFrame]) -> ChartData:
    """Donut chart: Distribution of AI Customer Segments."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    segmented = _get_segmented_rfm(data)
    if not segmented.empty:
        counts = segmented["Segment"].value_counts().reset_index()
        counts.columns = ["Segment", "Count"]

        fig.add_trace(go.Pie(
            labels=counts["Segment"],
            values=counts["Count"],
            hole=0.6,
            marker=dict(colors=[PRIMARY_ORANGE, SECONDARY_TEAL, ACCENT_RED, DARK_NAVY]),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>Customers: %{value:,} (%{percent})<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_customer_segments_donut",
        title="Customer Segment Distribution",
        height=380,
        description="Share of each strategic segment in the group's total customer base"
    )

@log_function
def get_cohort_retention_heatmap(data: dict[str, pd.DataFrame]) -> ChartData:
    """Cohort retention heatmap (Join month × Activity months)."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Customer_ID" in sales.columns and "Order_Date" in sales.columns:
        df = sales.dropna(subset=["Customer_ID", "Order_Date"]).copy()
        df["Order_Month"] = df["Order_Date"].dt.to_period("M")
        first_month = df.groupby("Customer_ID")["Order_Month"].min().reset_index()
        first_month.columns = ["Customer_ID", "Cohort_Month"]
        df = df.merge(first_month, on="Customer_ID")
        df["Cohort_Index"] = (df["Order_Month"].dt.year - df["Cohort_Month"].dt.year) * 12 + (df["Order_Month"].dt.month - df["Cohort_Month"].dt.month)

        cohort_data = df.groupby(["Cohort_Month", "Cohort_Index"])["Customer_ID"].nunique().reset_index()
        cohort_pivot = cohort_data.pivot(index="Cohort_Month", columns="Cohort_Index", values="Customer_ID").fillna(0)
        cohort_pivot = cohort_pivot.tail(8)
        cols = [c for c in range(min(6, len(cohort_pivot.columns)))]
        cohort_pivot = cohort_pivot[cols]
        retention = cohort_pivot.divide(cohort_pivot.iloc[:, 0].replace(0, 1), axis=0) * 100

        fig.add_trace(go.Heatmap(
            z=retention.values,
            x=[f"Month {i}" for i in retention.columns],
            y=[str(c) for c in retention.index],
            colorscale="Blues",
            text=retention.map(lambda v: f"{v:.0f}%" if v > 0 else "").values,
            texttemplate="%{text}",
            colorbar=dict(title="Retention %"),
            hovertemplate="Cohort: <b>%{y}</b><br>%{x}<br>Retention: %{z:.1f}%<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_cohort_retention",
        title="Cohort Retention Matrix",
        height=380,
        description="Share of customers still purchasing in each month after their first transaction"
    )

@log_function
def get_aov_distribution(data: dict[str, pd.DataFrame]) -> ChartData:
    """Histogram: Average Order Value distribution."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Invoice_ID" in sales.columns and "Net_Sales_EGP" in sales.columns:
        order_totals = sales.groupby("Invoice_ID")["Net_Sales_EGP"].sum().clip(upper=15000).dropna()

        # Pre-bin server-side: sending all ~180k raw values made this chart ~1.9 MB.
        counts, edges = np.histogram(order_totals, bins=30, range=(0.0, 15000.0))
        centers = (edges[:-1] + edges[1:]) / 2
        labels = [f"{lo:,.0f} – {hi:,.0f} EGP" for lo, hi in zip(edges[:-1], edges[1:])]

        fig.add_trace(go.Bar(
            x=centers,
            y=counts,
            width=float(edges[1] - edges[0]),
            marker_color=SECONDARY_TEAL,
            customdata=labels,
            hovertemplate="Basket value: %{customdata}<br>Order count: %{y:,.0f}<extra></extra>"
        ))
        fig.update_layout(
            xaxis=dict(title="Order Value (EGP)"),
            yaxis=dict(title="Order Frequency")
        )

    return create_chart_data(
        fig,
        chart_id="chart_aov_histogram",
        title="Basket Size Distribution",
        height=380,
        description="Price concentration of invoice values to identify the most attractive price ranges"
    )

@log_function
def get_new_vs_returning_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Stacked area: Monthly new customers vs returning customers."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Order_Date" in sales.columns and "Customer_ID" in sales.columns:
        df = sales.sort_values("Order_Date").copy()
        df["First_Order"] = df.groupby("Customer_ID")["Order_Date"].transform("min")
        df["Is_New"] = df["Order_Date"].dt.to_period("M") == df["First_Order"].dt.to_period("M")
        df["Year_Month"] = df["Order_Date"].dt.to_period("M").astype(str)

        m = df.groupby(["Year_Month", "Is_New"])["Customer_ID"].nunique().unstack(fill_value=0).reset_index()

        fig.add_trace(go.Bar(
            x=m["Year_Month"],
            y=m.get(True, pd.Series(0, index=m.index)),
            name="New customers",
            marker_color=PRIMARY_ORANGE,
            hovertemplate="<b>%{x}</b><br>New customers: %{y:,}<extra></extra>"
        ))

        fig.add_trace(go.Bar(
            x=m["Year_Month"],
            y=m.get(False, pd.Series(0, index=m.index)),
            name="Repeat customers",
            marker_color=DARK_NAVY,
            hovertemplate="<b>%{x}</b><br>Repeat customers: %{y:,}<extra></extra>"
        ))

        fig.update_layout(barmode="stack", yaxis=dict(title="Active Customers"))

    return create_chart_data(
        fig,
        chart_id="chart_new_vs_returning",
        title="New vs Repeat Customer Growth by Month",
        height=380,
        description="Balance between acquiring new customers and deepening the loyalty of existing ones"
    )

@log_function
def get_customer_geography(data: dict[str, pd.DataFrame]) -> ChartData:
    """Horizontal bar: Customer distribution across Egyptian governorates."""
    cust = data.get("Customers", pd.DataFrame())
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    gov_col = "Governorate" if "Governorate" in cust.columns else ("Customer_Governorate" if "Customer_Governorate" in sales.columns else None)
    df_src = cust if gov_col == "Governorate" else sales

    if not df_src.empty and gov_col in df_src.columns:
        gov_counts = df_src[gov_col].value_counts().head(10).iloc[::-1]

        fig.add_trace(go.Bar(
            y=gov_counts.index.astype(str),
            x=gov_counts.values,
            orientation="h",
            marker=dict(
                color=gov_counts.values,
                colorscale=[[0, LIGHT_TEAL], [1, SECONDARY_TEAL]],
                showscale=False
            ),
            text=gov_counts.values,
            textposition="outside",
            hovertemplate="<b>%{y}</b>: %{x:,} customers<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_customer_geography",
        title="Geographic Distribution of the Customer Base in Egypt",
        height=400,
        description="Governorates with the highest customer concentration, for targeting campaigns and distribution outlets"
    )
