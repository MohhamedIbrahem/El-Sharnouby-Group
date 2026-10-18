"""
Branch & Channel Performance Service (Task 8)
Retail, Online, Wholesale comparison, return rates, regional demand.
"""
import pandas as pd
import plotly.graph_objects as go
from app.core.models import KPICard, ChartData
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED, PALETTE
)
from app.core.metrics import pct_change_sum, pct_change_ratio_windowed
from app.core.logger import setup_logger, log_function

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)

CHANNEL_AR = {
    "Retail": "Retail Branches",
    "Online": "Online Store",
    "Wholesale": "Wholesale"
}

@log_function
def get_channel_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 4 KPIs for Branch & Channel Performance."""
    sales = data.get("Sales_Transactions", pd.DataFrame())

    retail_rev = 0.0
    online_rev = 0.0
    wholesale_rev = 0.0
    avg_basket = 0.0
    deltas: dict[str, float | None] = {"Retail": None, "Online": None, "Wholesale": None}
    basket_delta = None

    if not sales.empty and "Channel" in sales.columns and "Net_Sales_EGP" in sales.columns:
        ch_rev = sales.groupby("Channel", observed=False)["Net_Sales_EGP"].sum()
        retail_rev = ch_rev.get("Retail", 0.0)
        online_rev = ch_rev.get("Online", 0.0)
        wholesale_rev = ch_rev.get("Wholesale", 0.0)

        for ch in deltas:
            deltas[ch] = pct_change_sum(
                sales[sales["Channel"] == ch], "Net_Sales_EGP", "Order_Date"
            )

        # REAL basket size = window revenue / window invoices, % change vs previous window
        order_col = "Invoice_ID" if "Invoice_ID" in sales.columns else None
        if order_col:
            basket_delta = pct_change_ratio_windowed(
                sales, "Net_Sales_EGP", order_col, "Order_Date"
            )
            tot_orders = sales[order_col].nunique()
            avg_basket = sales["Net_Sales_EGP"].sum() / max(1, tot_orders)

    return [
        KPICard(
            title="Retail Branches Sales",
            value=format_currency_ar(retail_rev),
            raw_value=float(retail_rev),
            delta=round(deltas["Retail"], 1) if deltas["Retail"] is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange"
        ),
        KPICard(
            title="Online Store Sales",
            value=format_currency_ar(online_rev),
            raw_value=float(online_rev),
            delta=round(deltas["Online"], 1) if deltas["Online"] is not None else None,
            delta_label=PERIOD_LABEL,
            color="teal"
        ),
        KPICard(
            title="Wholesale Sales",
            value=format_currency_ar(wholesale_rev),
            raw_value=float(wholesale_rev),
            delta=round(deltas["Wholesale"], 1) if deltas["Wholesale"] is not None else None,
            delta_label=PERIOD_LABEL,
            color="navy"
        ),
        KPICard(
            title="Average Basket Value",
            value=format_currency_ar(avg_basket),
            raw_value=float(avg_basket),
            delta=round(basket_delta, 1) if basket_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange"
        ),
    ]

@log_function
def get_channel_comparison(data: dict[str, pd.DataFrame]) -> ChartData:
    """Grouped bar comparing Revenue, Gross Profit, and Units per channel."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Channel" in sales.columns:
        m = sales.groupby("Channel", observed=False).agg(
            Revenue=("Net_Sales_EGP", "sum"),
            Profit=("Gross_Profit_EGP", "sum"),
            Units=("Quantity", "sum")
        ).reset_index()
        m["Channel_AR"] = m["Channel"].map(lambda x: CHANNEL_AR.get(str(x), str(x)))

        fig.add_trace(go.Bar(
            x=m["Channel_AR"],
            y=m["Revenue"],
            name="Net Revenue",
            marker_color=PRIMARY_ORANGE,
            text=m["Revenue"].apply(format_currency_ar),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Revenue: %{y:,.0f} EGP<extra></extra>"
        ))

        fig.add_trace(go.Bar(
            x=m["Channel_AR"],
            y=m["Profit"],
            name="Gross Profit",
            marker_color=SECONDARY_TEAL,
            text=m["Profit"].apply(format_currency_ar),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Profit: %{y:,.0f} EGP<extra></extra>"
        ))

        fig.update_layout(barmode="group", yaxis=dict(title="Value (EGP)"))

    return create_chart_data(
        fig,
        chart_id="chart_channel_comparison",
        title="Financial & Profit Comparison Across Sales Channels",
        height=380,
        description="Direct comparison of revenue and gross profit achieved in each sales channel"
    )

@log_function
def get_channel_growth_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Multi-line: Monthly revenue trend per channel."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Year_Month" in sales.columns and "Channel" in sales.columns:
        trend = sales.groupby(["Year_Month", "Channel"], observed=False)["Net_Sales_EGP"].sum().unstack(fill_value=0).reset_index()

        color_map = {"Retail": PRIMARY_ORANGE, "Online": SECONDARY_TEAL, "Wholesale": DARK_NAVY}

        for ch in ["Retail", "Online", "Wholesale"]:
            if ch in trend.columns:
                fig.add_trace(go.Scatter(
                    x=trend["Year_Month"],
                    y=trend[ch],
                    mode="lines+markers",
                    name=CHANNEL_AR.get(ch, ch),
                    line=dict(color=color_map.get(ch, PRIMARY_ORANGE), width=3),
                    hovertemplate=f"<b>{CHANNEL_AR.get(ch, ch)}</b><br>%{{x}}: %{{y:,.0f}} EGP<extra></extra>"
                ))

    return create_chart_data(
        fig,
        chart_id="chart_channel_growth_trend",
        title="Monthly Revenue Growth Trend by Channel",
        height=380,
        description="Tracking online sales acceleration against the stability of branches and wholesale"
    )

@log_function
def get_returns_by_channel(data: dict[str, pd.DataFrame]) -> ChartData:
    """Stacked bar: Return Rate % across Channels."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Channel" in sales.columns and "Is_Return" in sales.columns:
        ret = sales.groupby("Channel", observed=False).agg(
            Total=("Quantity", "sum"),
            Returns=("Is_Return", lambda x: (x == True).sum())
        ).reset_index()
        ret["Return_Rate"] = (ret["Returns"] / ret["Total"] * 100).fillna(0)
        ret["Channel_AR"] = ret["Channel"].map(lambda x: CHANNEL_AR.get(str(x), str(x)))

        fig.add_trace(go.Bar(
            x=ret["Channel_AR"],
            y=ret["Return_Rate"],
            marker_color=[PRIMARY_ORANGE if r > 10 else SECONDARY_TEAL for r in ret["Return_Rate"]],
            text=ret["Return_Rate"].apply(lambda v: f"{v:.1f}%"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Return rate: %{y:.1f}%<extra></extra>"
        ))
        fig.update_layout(yaxis=dict(title="Return Rate (%)", range=[0, max(25, ret["Return_Rate"].max() * 1.3)]))

    return create_chart_data(
        fig,
        chart_id="chart_returns_by_channel",
        title="Return Rates by Sales Channel",
        height=380,
        description="Identifying channels with elevated return rates (typically online, size-related)"
    )

@log_function
def get_geographic_demand(data: dict[str, pd.DataFrame]) -> ChartData:
    """Grouped bar: Revenue by Governorate split by Channel."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Customer_Governorate" in sales.columns and "Channel" in sales.columns:
        top_govs = sales.groupby("Customer_Governorate")["Net_Sales_EGP"].sum().nlargest(7).index

        sub = sales[sales["Customer_Governorate"].isin(top_govs)]
        p = sub.pivot_table(index="Customer_Governorate", columns="Channel", values="Net_Sales_EGP", aggfunc="sum", fill_value=0)

        for ch in ["Retail", "Online", "Wholesale"]:
            if ch in p.columns:
                fig.add_trace(go.Bar(
                    x=list(p.index),
                    y=p[ch],
                    name=CHANNEL_AR.get(ch, ch),
                    marker_color={"Retail": PRIMARY_ORANGE, "Online": SECONDARY_TEAL, "Wholesale": DARK_NAVY}.get(ch),
                    hovertemplate=f"<b>{CHANNEL_AR.get(ch, ch)}</b><br>%{{x}}: %{{y:,.0f}} EGP<extra></extra>"
                ))

        fig.update_layout(barmode="stack", yaxis=dict(title="Sales (EGP)"))

    return create_chart_data(
        fig,
        chart_id="chart_geo_demand",
        title="Regional Demand in Top Governorates by Channel",
        height=400,
        description="How physical branches and online delivery complement each other in each governorate"
    )

@log_function
def get_channel_mix_evolution(data: dict[str, pd.DataFrame]) -> ChartData:
    """100% stacked area: Channel revenue share over time."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Year_Month" in sales.columns and "Channel" in sales.columns:
        p = sales.pivot_table(index="Year_Month", columns="Channel", values="Net_Sales_EGP", aggfunc="sum", fill_value=0)
        p_pct = p.divide(p.sum(axis=1), axis=0) * 100

        for ch in ["Retail", "Online", "Wholesale"]:
            if ch in p_pct.columns:
                fig.add_trace(go.Scatter(
                    x=list(p_pct.index),
                    y=p_pct[ch],
                    mode="lines",
                    stackgroup="one",
                    name=CHANNEL_AR.get(ch, ch),
                    line=dict(color={"Retail": PRIMARY_ORANGE, "Online": SECONDARY_TEAL, "Wholesale": DARK_NAVY}.get(ch)),
                    hovertemplate=f"<b>{CHANNEL_AR.get(ch, ch)}</b><br>%{{x}}: %{{y:.1f}}%<extra></extra>"
                ))
        fig.update_layout(yaxis=dict(title="Share (%)", range=[0, 100]))

    return create_chart_data(
        fig,
        chart_id="chart_channel_mix_evolution",
        title="Channel Mix Evolution Over Time (%)",
        height=380,
        description="Monitoring the digital shift and each channel's changing contribution to total income"
    )
