"""
Marketing Effectiveness Service (Task 10)
Analyzes campaigns, ROAS, web conversion funnel, CTR trends, and spend efficiency.
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from app.core.models import KPICard, ChartData
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED, ACCENT_GREEN, ACCENT_BLUE, PALETTE
)
from app.core.metrics import (
    pct_change_sum, pct_change_ratio_windowed, pp_change_mean,
)
from app.core.logger import setup_logger, log_function

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)


@log_function
def get_marketing_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Marketing Effectiveness."""
    mkt = data.get("Marketing", pd.DataFrame())
    web = data.get("Web_Traffic_Daily", pd.DataFrame())

    total_spend = 0.0
    total_revenue = 0.0
    roas = 0.0
    cac = 0.0
    conv_rate = 0.0

    if not mkt.empty and "Spend_EGP" in mkt.columns:
        total_spend = float(mkt["Spend_EGP"].sum())
        total_revenue = float(mkt["Attributed_Revenue_EGP"].sum()) if "Attributed_Revenue_EGP" in mkt.columns else 0.0
        roas = (total_revenue / total_spend) if total_spend > 0 else 0.0
        total_orders = float(mkt["Orders_Attributed"].sum()) if "Orders_Attributed" in mkt.columns else 0.0
        cac = (total_spend / total_orders) if total_orders > 0 else 0.0

    if not web.empty and "Conversion_Rate" in web.columns:
        conv_rate = float(web["Conversion_Rate"].mean() * 100)
    elif not web.empty and "Sessions" in web.columns:
        s_sum = web["Sessions"].sum()
        conv_rate = float((web["Orders"].sum() / s_sum * 100) if "Orders" in web.columns and s_sum > 0 else 0.0)

    # REAL deltas: trailing 12-month window vs previous 12-month window
    spend_delta = pct_change_sum(mkt, "Spend_EGP", "Start_Date") if not mkt.empty else None
    revenue_delta = pct_change_sum(mkt, "Attributed_Revenue_EGP", "Start_Date") if not mkt.empty else None
    roas_delta = (
        pct_change_ratio_windowed(mkt, "Attributed_Revenue_EGP", "Spend_EGP", "Start_Date")
        if not mkt.empty else None
    )
    cac_delta = (
        pct_change_ratio_windowed(mkt, "Spend_EGP", "Orders_Attributed", "Start_Date")
        if not mkt.empty else None
    )
    conv_delta = pp_change_mean(web, "Conversion_Rate", "Date") if not web.empty else None
    if conv_delta is not None:
        conv_delta *= 100  # column is a fraction (0-1) -> percentage points

    return [
        KPICard(
            title="Total Ad Spend",
            value=format_currency_ar(total_spend),
            raw_value=float(total_spend),
            delta=round(spend_delta, 1) if spend_delta is not None else None,
            delta_label=PERIOD_LABEL,
            neutral_delta=True,
            color="orange",
        ),
        KPICard(
            title="Attributed Revenue",
            value=format_currency_ar(total_revenue),
            raw_value=float(total_revenue),
            delta=round(revenue_delta, 1) if revenue_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="teal",
        ),
        KPICard(
            title="Return on Ad Spend (ROAS)",
            value=f"{roas:.2f}x",
            raw_value=float(roas),
            delta=round(roas_delta, 1) if roas_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="teal" if roas >= 2.0 else "orange",
        ),
        KPICard(
            title="Customer Acquisition Cost (CAC)",
            value=format_currency_ar(cac),
            raw_value=float(cac),
            delta=round(cac_delta, 1) if cac_delta is not None else None,
            delta_label=PERIOD_LABEL,
            favorable=False,
            color="navy",
        ),
        KPICard(
            title="Digital Conversion Rate",
            value=f"{conv_rate:.2f}%",
            raw_value=float(conv_rate),
            delta=round(conv_delta, 2) if conv_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="teal",
        ),
    ]


@log_function
def get_roas_by_platform(data: dict[str, pd.DataFrame]) -> ChartData:
    """Bar chart: ROAS comparison by advertising platform."""
    mkt = data.get("Marketing", pd.DataFrame())
    fig = go.Figure()

    if not mkt.empty and "Platform" in mkt.columns and "Spend_EGP" in mkt.columns and "Attributed_Revenue_EGP" in mkt.columns:
        grp = mkt.groupby("Platform", observed=False).agg({
            "Spend_EGP": "sum",
            "Attributed_Revenue_EGP": "sum"
        }).reset_index()
        grp["ROAS"] = grp["Attributed_Revenue_EGP"] / grp["Spend_EGP"].replace(0, np.nan)
        grp = grp.sort_values("ROAS", ascending=False)

        colors = [PRIMARY_ORANGE if r >= 2.5 else SECONDARY_TEAL for r in grp["ROAS"]]

        fig.add_trace(go.Bar(
            x=grp["Platform"],
            y=grp["ROAS"],
            text=[f"{v:.2f}x" for v in grp["ROAS"]],
            textposition="auto",
            marker=dict(color=colors, line=dict(color=DARK_NAVY, width=1)),
            name="ROAS"
        ))

        fig.add_hline(
            y=2.5, line_dash="dash", line_color=ACCENT_RED,
            annotation_text="Target (2.5x)", annotation_position="top right"
        )

    fig.update_layout(
        title="ROAS by Platform",
        xaxis_title="Ad platform",
        yaxis_title="ROAS multiple",
    )
    return create_chart_data(fig, "roas_by_platform", "ROAS by Platform", height=380)


@log_function
def get_spend_vs_revenue(data: dict[str, pd.DataFrame]) -> ChartData:
    """Bubble scatter: Spend vs Revenue with bubble size as Orders."""
    mkt = data.get("Marketing", pd.DataFrame())
    fig = go.Figure()

    if not mkt.empty and "Spend_EGP" in mkt.columns and "Attributed_Revenue_EGP" in mkt.columns:
        platforms = mkt["Platform"].unique()
        color_map = {
            "Meta": PRIMARY_ORANGE,
            "Google": SECONDARY_TEAL,
            "TikTok": "#ff0050",
            "Snapchat": "#fffc00",
            "Instagram": "#c13584"
        }

        for p in platforms:
            df_p = mkt[mkt["Platform"] == p]
            color = color_map.get(str(p), PRIMARY_ORANGE)
            sizes = np.clip(df_p["Orders_Attributed"].fillna(10) / 3, 8, 35)

            fig.add_trace(go.Scatter(
                x=df_p["Spend_EGP"],
                y=df_p["Attributed_Revenue_EGP"],
                mode="markers",
                name=str(p),
                marker=dict(
                    size=sizes,
                    color=color,
                    opacity=0.75,
                    line=dict(color="#ffffff", width=1)
                ),
                text=df_p["Campaign_Name"],
                hovertemplate="<b>%{text}</b><br>Spend: %{x:,.0f} EGP<br>Revenue: %{y:,.0f} EGP<extra></extra>"
            ))

    fig.update_layout(
        title="Campaign Efficiency: Spend vs Attributed Revenue",
        xaxis_title="Spend (EGP)",
        yaxis_title="Attributed Revenue (EGP)",
    )
    return create_chart_data(fig, "spend_vs_revenue", "Campaign Efficiency: Spend vs Revenue", height=420)


@log_function
def get_ctr_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Multi-line: Monthly CTR trend by Platform."""
    mkt = data.get("Marketing", pd.DataFrame()).copy()
    fig = go.Figure()

    if not mkt.empty and "Start_Date" in mkt.columns and "Clicks" in mkt.columns and "Impressions" in mkt.columns:
        mkt["Start_Date"] = pd.to_datetime(mkt["Start_Date"], errors="coerce")
        mkt["Month"] = mkt["Start_Date"].dt.to_period("M").astype(str)
        mkt = mkt.dropna(subset=["Month"])

        grp = mkt.groupby(["Month", "Platform"], observed=False).agg({
            "Clicks": "sum",
            "Impressions": "sum"
        }).reset_index()
        grp["CTR"] = (grp["Clicks"] / grp["Impressions"].replace(0, np.nan)) * 100

        platforms = grp["Platform"].unique()
        colors = [PRIMARY_ORANGE, SECONDARY_TEAL, ACCENT_BLUE, LIGHT_ORANGE, "#8b5cf6"]

        for idx, p in enumerate(platforms):
            sub = grp[grp["Platform"] == p].sort_values("Month")
            fig.add_trace(go.Scatter(
                x=sub["Month"],
                y=sub["CTR"],
                mode="lines+markers",
                name=str(p),
                line=dict(color=colors[idx % len(colors)], width=2.5),
                marker=dict(size=6)
            ))

    fig.update_layout(
        title="CTR Evolution by Month",
        xaxis_title="Month",
        yaxis_title="CTR (%)",
    )
    return create_chart_data(fig, "ctr_trend", "CTR Evolution Across Platforms", height=380)


@log_function
def get_budget_allocation(data: dict[str, pd.DataFrame]) -> ChartData:
    """Donut chart: Advertising budget allocation across platforms."""
    mkt = data.get("Marketing", pd.DataFrame())
    fig = go.Figure()

    if not mkt.empty and "Platform" in mkt.columns and "Spend_EGP" in mkt.columns:
        alloc = mkt.groupby("Platform", observed=False)["Spend_EGP"].sum().reset_index()
        alloc = alloc.sort_values("Spend_EGP", ascending=False)

        fig.add_trace(go.Pie(
            labels=alloc["Platform"],
            values=alloc["Spend_EGP"],
            hole=0.55,
            marker=dict(colors=[PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL]),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>Spend: %{value:,.0f} EGP (%{percent})<extra></extra>"
        ))

    fig.update_layout(
        title="Ad Budget Allocation by Platform",
        showlegend=True
    )
    return create_chart_data(fig, "budget_allocation", "Ad Budget Allocation by Platform", height=380)


@log_function
def get_web_funnel(data: dict[str, pd.DataFrame]) -> ChartData:
    """Funnel chart: Digital website funnel from Sessions to Orders."""
    web = data.get("Web_Traffic_Daily", pd.DataFrame())
    fig = go.Figure()

    if not web.empty and "Sessions" in web.columns:
        total_sessions = int(web["Sessions"].sum())
        avg_cart_rate = web["Add_To_Cart_Rate"].mean() if "Add_To_Cart_Rate" in web.columns else 0.12
        avg_checkout_rate = web["Checkout_Rate"].mean() if "Checkout_Rate" in web.columns else 0.06
        total_orders = int(web["Orders"].sum()) if "Orders" in web.columns else int(total_sessions * 0.03)

        cart_sessions = int(total_sessions * avg_cart_rate)
        checkout_sessions = int(total_sessions * avg_checkout_rate)

        stages = ["1. Sessions", "2. Add to Cart", "3. Checkout Started", "4. Orders Completed"]
        values = [total_sessions, cart_sessions, checkout_sessions, total_orders]

        fig.add_trace(go.Funnel(
            y=stages,
            x=values,
            textinfo="value+percent previous",
            texttemplate="%{value:,.0f} (%{percentPrevious:.1%})",
            marker=dict(color=[DARK_NAVY, PRIMARY_ORANGE, LIGHT_ORANGE, SECONDARY_TEAL])
        ))

    fig.update_layout(
        title="Digital Conversion Funnel",
    )
    return create_chart_data(fig, "web_funnel", "Digital Funnel: From Visit to Purchase", height=420)


@log_function
def get_campaign_table(data: dict[str, pd.DataFrame], n: int = 15) -> list[dict]:
    """Sortable campaign performance table data."""
    mkt = data.get("Marketing", pd.DataFrame())
    if mkt.empty or "Campaign_Name" not in mkt.columns:
        return []

    df = mkt.copy()
    if "Spend_EGP" in df.columns and "Attributed_Revenue_EGP" in df.columns:
        df["ROAS"] = df["Attributed_Revenue_EGP"] / df["Spend_EGP"].replace(0, np.nan)
        df["ROAS"] = df["ROAS"].round(2)
        df = df.sort_values("Attributed_Revenue_EGP", ascending=False).head(n)

    records = []
    for _, row in df.iterrows():
        records.append({
            "campaign_id": str(row.get("Campaign_ID", "")),
            "campaign_name": str(row.get("Campaign_Name", "")),
            "platform": str(row.get("Platform", "")),
            "spend": f"{float(row.get('Spend_EGP', 0)):,.0f} EGP",
            "revenue": f"{float(row.get('Attributed_Revenue_EGP', 0)):,.0f} EGP",
            "roas": f"{float(row.get('ROAS', 0)):.2f}x",
            "orders": f"{int(row.get('Orders_Attributed', 0)):,}",
            "clicks": f"{int(row.get('Clicks', 0)):,}",
        })
    return records
