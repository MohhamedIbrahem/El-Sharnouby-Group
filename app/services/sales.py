"""
Sales & Profitability Service (Task 6)
Deep sales analytics: margins, discount impact, MoM/YoY growth, product families.
"""
import pandas as pd
import plotly.graph_objects as go
from app.core.models import KPICard, ChartData
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED, PALETTE
)
from app.core.metrics import (
    pct_change_sum, pct_change_count, pp_change_ratio, pp_change_mean,
)
from app.core.logger import setup_logger, log_function

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)

@log_function
def get_sales_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Sales & Profitability."""
    sales = data.get("Sales_Transactions", pd.DataFrame())

    net_sales = sales["Net_Sales_EGP"].sum() if not sales.empty and "Net_Sales_EGP" in sales.columns else 0.0
    gross_sales = sales["Gross_Sales_EGP"].sum() if not sales.empty and "Gross_Sales_EGP" in sales.columns else 0.0
    units = sales["Quantity"].sum() if not sales.empty and "Quantity" in sales.columns else 0
    profit = sales["Gross_Profit_EGP"].sum() if not sales.empty and "Gross_Profit_EGP" in sales.columns else 0.0
    margin = (profit / net_sales * 100) if net_sales > 0 else 0.0
    discount_impact = max(0.0, float(gross_sales - net_sales))

    # REAL deltas: trailing 12-month window vs previous 12-month window
    sales_delta = pct_change_sum(sales, "Net_Sales_EGP", "Order_Date") if not sales.empty else None
    units_delta = pct_change_sum(sales, "Quantity", "Order_Date") if not sales.empty else None
    profit_delta = pct_change_sum(sales, "Gross_Profit_EGP", "Order_Date") if not sales.empty else None
    margin_delta = (
        pp_change_ratio(sales, "Gross_Profit_EGP", "Net_Sales_EGP", "Order_Date")
        if not sales.empty else None
    )
    discount_delta = None
    if not sales.empty and "Gross_Sales_EGP" in sales.columns and "Net_Sales_EGP" in sales.columns:
        impact_df = sales.assign(_Impact=sales["Gross_Sales_EGP"] - sales["Net_Sales_EGP"])
        discount_delta = pct_change_sum(impact_df, "_Impact", "Order_Date")

    return [
        KPICard(
            title="Net Revenue",
            value=format_currency_ar(net_sales),
            raw_value=float(net_sales),
            delta=round(sales_delta, 1) if sales_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange"
        ),
        KPICard(
            title="Units Sold",
            value=format_number_ar(units),
            raw_value=float(units),
            delta=round(units_delta, 1) if units_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="teal"
        ),
        KPICard(
            title="Gross Profit",
            value=format_currency_ar(profit),
            raw_value=float(profit),
            delta=round(profit_delta, 1) if profit_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="navy"
        ),
        KPICard(
            title="Average Margin",
            value=f"{margin:.1f}%",
            raw_value=float(margin),
            delta=round(margin_delta, 2) if margin_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="teal"
        ),
        KPICard(
            title="Discount Impact",
            value=format_currency_ar(discount_impact),
            raw_value=float(discount_impact),
            delta=round(discount_delta, 1) if discount_delta is not None else None,
            delta_label=PERIOD_LABEL,
            favorable=False,
            color="orange"
        ),
    ]

@log_function
def get_revenue_vs_profit_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Dual-axis: Monthly Revenue and Profit Margin %."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Year_Month" in sales.columns and "Net_Sales_EGP" in sales.columns:
        m = sales.groupby("Year_Month").agg(
            Revenue=("Net_Sales_EGP", "sum"),
            Profit=("Gross_Profit_EGP", "sum")
        ).reset_index().sort_values("Year_Month")
        m["Margin_Pct"] = (m["Profit"] / m["Revenue"] * 100).fillna(0)

        fig.add_trace(go.Bar(
            x=m["Year_Month"],
            y=m["Revenue"],
            name="Revenue (EGP)",
            marker_color=PRIMARY_ORANGE,
            yaxis="y",
            hovertemplate="<b>%{x}</b><br>Revenue: %{y:,.0f} EGP<extra></extra>"
        ))

        fig.add_trace(go.Scatter(
            x=m["Year_Month"],
            y=m["Margin_Pct"],
            name="Margin (%)",
            mode="lines+markers",
            line=dict(color=SECONDARY_TEAL, width=3),
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>Margin: %{y:.1f}%<extra></extra>"
        ))

        fig.update_layout(
            yaxis=dict(title="Revenue (EGP)", showgrid=True),
            yaxis2=dict(
                title="Margin (%)",
                overlaying="y",
                side="right",
                range=[0, max(50, m["Margin_Pct"].max() * 1.2)],
                showgrid=False
            )
        )

    return create_chart_data(
        fig,
        chart_id="chart_sales_revenue_profit",
        title="Monthly Revenue vs Profit Margin",
        height=380,
        description="Monthly sales volume against the stability or volatility of the profit margin"
    )

@log_function
def get_revenue_by_product_family(data: dict[str, pd.DataFrame]) -> ChartData:
    """Treemap of revenue & profit across product families."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    family_ar = {
        "Fabrics": "Fabrics & Textiles",
        "Men_Wear": "Men's Wear",
        "Women_Wear": "Women's Wear",
        "Kids_Wear": "Kids' Wear",
        "Home_Textiles": "Home Textiles",
        "Uniforms": "Uniforms & Supplies",
    }

    if not sales.empty and "Product_Family" in sales.columns and "Net_Sales_EGP" in sales.columns:
        fam = sales.groupby("Product_Family", observed=False).agg(
            Revenue=("Net_Sales_EGP", "sum"),
            Profit=("Gross_Profit_EGP", "sum")
        ).reset_index().sort_values("Revenue", ascending=False)
        fam["Family_AR"] = fam["Product_Family"].map(lambda x: family_ar.get(str(x), str(x)))

        fig = go.Figure(go.Treemap(
            labels=fam["Family_AR"],
            parents=[""] * len(fam),
            values=fam["Revenue"],
            textinfo="label+value+percent parent",
            marker=dict(colors=PALETTE[:len(fam)]),
            hovertemplate="<b>%{label}</b><br>Sales: %{value:,.0f} EGP<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_family_treemap",
        title="Revenue Structure by Product Family",
        height=380,
        description="Treemap showing the relative sales size of each product family in the group"
    )

@log_function
def get_discount_impact_analysis(data: dict[str, pd.DataFrame]) -> ChartData:
    """Scatter plot: Discount % vs Gross Margin % showing margin compression."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Discount_Pct" in sales.columns and "Gross_Margin_Pct" in sales.columns:
        sample_df = sales.sample(min(800, len(sales)), random_state=42)

        fig.add_trace(go.Scatter(
            x=sample_df["Discount_Pct"],
            y=sample_df["Gross_Margin_Pct"],
            mode="markers",
            marker=dict(
                size=7,
                color=sample_df["Gross_Margin_Pct"],
                colorscale="Viridis",
                opacity=0.6,
                showscale=False
            ),
            hovertemplate="Discount: %{x:.1f}%<br>Gross margin: %{y:.1f}%<extra></extra>"
        ))
        fig.update_layout(
            xaxis=dict(title="Discount granted (%)"),
            yaxis=dict(title="Gross Margin (%)")
        )

    return create_chart_data(
        fig,
        chart_id="chart_discount_impact",
        title="Discount Impact on Margin Erosion",
        height=380,
        description="Relationship between discount depth and realized margin, exposing unprofitable deals"
    )

@log_function
def get_growth_comparison(data: dict[str, pd.DataFrame]) -> ChartData:
    """Quarterly growth comparison bars."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Year" in sales.columns and "Quarter" in sales.columns and "Net_Sales_EGP" in sales.columns:
        q = sales.groupby(["Year", "Quarter"])["Net_Sales_EGP"].sum().reset_index()
        q["Label"] = q["Year"].astype(str) + " - Q" + q["Quarter"].astype(str)

        fig.add_trace(go.Bar(
            x=q["Label"],
            y=q["Net_Sales_EGP"],
            marker_color=SECONDARY_TEAL,
            text=q["Net_Sales_EGP"].apply(format_currency_ar),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Sales: %{y:,.0f} EGP<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_growth_quarterly",
        title="Quarterly Sales Performance",
        height=380,
        description="Quarter-by-quarter sales progression for cumulative performance tracking"
    )

@log_function
def get_seasonality_by_family(data: dict[str, pd.DataFrame]) -> ChartData:
    """Multi-line seasonality curves by Product Family."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    family_ar = {
        "Fabrics": "Fabrics & Textiles",
        "Men_Wear": "Men's Wear",
        "Women_Wear": "Women's Wear",
        "Kids_Wear": "Kids' Wear",
        "Home_Textiles": "Home Textiles",
        "Uniforms": "Uniforms & Supplies",
    }
    month_names_ar = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

    if not sales.empty and "Month" in sales.columns and "Product_Family" in sales.columns:
        f_month = sales.groupby(["Product_Family", "Month"], observed=False)["Net_Sales_EGP"].sum().reset_index()

        for idx, fam in enumerate(f_month["Product_Family"].unique()):
            sub = f_month[f_month["Product_Family"] == fam].sort_values("Month")
            if not sub.empty:
                color = PALETTE[idx % len(PALETTE)]
                label = family_ar.get(str(fam), str(fam))
                fig.add_trace(go.Scatter(
                    x=[month_names_ar[m - 1] for m in sub["Month"]],
                    y=sub["Net_Sales_EGP"],
                    mode="lines+markers",
                    name=label,
                    line=dict(color=color, width=2.5),
                    hovertemplate=f"<b>{label}</b><br>Month: %{{x}}<br>Sales: %{{y:,.0f}} EGP<extra></extra>"
                ))

    return create_chart_data(
        fig,
        chart_id="chart_seasonality_curves",
        title="Seasonal Demand Curves by Product Family",
        height=400,
        description="Seasonal behavior of each product family across the 12 months"
    )

@log_function
def get_top_bottom_margin_products(data: dict[str, pd.DataFrame], n: int = 10) -> ChartData:
    """Top 5 and Bottom 5 products by margin %."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    prod = data.get("Product_Master", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Product_ID" in sales.columns and "Gross_Margin_Pct" in sales.columns:
        p_margin = sales.groupby("Product_ID").agg(
            Avg_Margin=("Gross_Margin_Pct", "mean"),
            Revenue=("Net_Sales_EGP", "sum")
        ).reset_index()
        p_margin = p_margin[p_margin["Revenue"] > 1000]

        if not prod.empty and "Product_Name" in prod.columns:
            p_margin = p_margin.merge(prod[["Product_ID", "Product_Name"]], on="Product_ID", how="left")
            p_margin["Name"] = p_margin["Product_Name"].fillna(p_margin["Product_ID"])
        else:
            p_margin["Name"] = p_margin["Product_ID"]

        top5 = p_margin.sort_values("Avg_Margin", ascending=False).head(5)
        bot5 = p_margin.sort_values("Avg_Margin", ascending=True).head(5)
        combined = pd.concat([bot5, top5]).sort_values("Avg_Margin")

        colors = [ACCENT_RED if m < 25 else SECONDARY_TEAL for m in combined["Avg_Margin"]]

        fig.add_trace(go.Bar(
            y=combined["Name"].astype(str),
            x=combined["Avg_Margin"],
            orientation="h",
            marker_color=colors,
            text=combined["Avg_Margin"].apply(lambda v: f"{v:.1f}%"),
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Average margin: %{x:.1f}%<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_top_bottom_margins",
        title="Product Margin Spectrum (Top & Bottom)",
        height=420,
        description="Identifying high-margin products versus low-margin products"
    )
