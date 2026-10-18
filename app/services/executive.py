"""
Executive Command Center Service (Task 5)
High-level KPIs, multi-channel performance, BU efficiency, and seasonality.
"""
import pandas as pd
import plotly.graph_objects as go
from typing import Optional
from app.core.models import KPICard, ChartData
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, PALETTE
)
from app.core.metrics import (
    pct_change_sum, pct_change_count, pp_change_ratio, pp_change_mean,
)
from app.core.logger import setup_logger, log_function

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)

@log_function
def get_executive_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates the 7 top-level enterprise KPIs."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    customers = data.get("Customers", pd.DataFrame())
    quality = data.get("Quality", pd.DataFrame())

    total_rev = sales["Net_Sales_EGP"].sum() if not sales.empty and "Net_Sales_EGP" in sales.columns else 0.0
    gross_profit = sales["Gross_Profit_EGP"].sum() if not sales.empty and "Gross_Profit_EGP" in sales.columns else 0.0
    net_margin = (gross_profit / total_rev * 100) if total_rev > 0 else 0.0
    order_col = "Invoice_ID" if "Invoice_ID" in sales.columns else None
    total_orders = sales[order_col].nunique() if order_col and not sales.empty else len(sales)
    total_customers = customers["Customer_ID"].nunique() if not customers.empty and "Customer_ID" in customers.columns else (
        sales["Customer_ID"].nunique() if not sales.empty and "Customer_ID" in sales.columns else 0
    )

    pass_rate = 0.0
    if not quality.empty and "Inspected_Qty" in quality.columns and "Passed_Qty" in quality.columns:
        tot_inspected = quality["Inspected_Qty"].sum()
        tot_passed = quality["Passed_Qty"].sum()
        pass_rate = (tot_passed / tot_inspected * 100) if tot_inspected > 0 else 0.0

    # REAL deltas: trailing 12-month window vs previous 12-month window
    rev_delta = pct_change_sum(sales, "Net_Sales_EGP", "Order_Date") if not sales.empty else None
    profit_delta = pct_change_sum(sales, "Gross_Profit_EGP", "Order_Date") if not sales.empty else None
    margin_delta = (
        pp_change_ratio(sales, "Gross_Profit_EGP", "Net_Sales_EGP", "Order_Date")
        if not sales.empty else None
    )
    orders_delta = pct_change_count(sales, "Order_Date") if not sales.empty and order_col else None
    customers_delta = pct_change_count(customers, "Join_Date") if not customers.empty else None
    quality_delta = (
        pp_change_ratio(quality, "Passed_Qty", "Inspected_Qty", "Inspection_Date")
        if not quality.empty else None
    )

    return [
        KPICard(
            title="Total Revenue",
            value=format_currency_ar(total_rev),
            raw_value=float(total_rev),
            delta=round(rev_delta, 1) if rev_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange"
        ),
        KPICard(
            title="Gross Profit",
            value=format_currency_ar(gross_profit),
            raw_value=float(gross_profit),
            delta=round(profit_delta, 1) if profit_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="teal"
        ),
        KPICard(
            title="Gross Margin",
            value=f"{net_margin:.1f}%",
            raw_value=float(net_margin),
            delta=round(margin_delta, 1) if margin_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="navy"
        ),
        KPICard(
            title="Total Orders",
            value=format_number_ar(total_orders),
            raw_value=float(total_orders),
            delta=round(orders_delta, 1) if orders_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange"
        ),
        KPICard(
            title="Customer Base",
            value=format_number_ar(total_customers),
            raw_value=float(total_customers),
            delta=round(customers_delta, 1) if customers_delta is not None else None,
            delta_label="New customers vs prior period",
            color="teal"
        ),
        KPICard(
            title="Quality Pass Rate",
            value=f"{pass_rate:.1f}%",
            raw_value=float(pass_rate),
            delta=round(quality_delta, 2) if quality_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="navy"
        ),
        KPICard(
            title="Revenue Growth (12 months)",
            value=f"{rev_delta:.1f}%" if rev_delta is not None else "—",
            raw_value=float(rev_delta) if rev_delta is not None else 0.0,
            delta=round(rev_delta, 1) if rev_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange"
        ),
    ]

@log_function
def get_revenue_profit_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Monthly revenue & profit line/area chart."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Year_Month" in sales.columns and "Net_Sales_EGP" in sales.columns:
        monthly = sales.groupby("Year_Month").agg(
            Revenue=("Net_Sales_EGP", "sum"),
            Profit=("Gross_Profit_EGP", "sum") if "Gross_Profit_EGP" in sales.columns else ("Net_Sales_EGP", lambda x: x.sum() * 0.35)
        ).reset_index().sort_values("Year_Month")

        fig.add_trace(go.Scatter(
            x=monthly["Year_Month"],
            y=monthly["Revenue"],
            mode="lines+markers",
            name="Net Revenue",
            line=dict(color=PRIMARY_ORANGE, width=3),
            fill="tozeroy",
            fillcolor="rgba(232, 114, 12, 0.08)",
            hovertemplate="<b>%{x}</b><br>Revenue: %{y:,.0f} EGP<extra></extra>"
        ))

        fig.add_trace(go.Scatter(
            x=monthly["Year_Month"],
            y=monthly["Profit"],
            mode="lines+markers",
            name="Gross Profit",
            line=dict(color=SECONDARY_TEAL, width=2.5, dash="solid"),
            hovertemplate="<b>%{x}</b><br>Profit: %{y:,.0f} EGP<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_revenue_profit_trend",
        title="Monthly Revenue & Profit Trend",
        height=380,
        description="Net revenue and gross profit by month in Egyptian pounds (EGP)"
    )

@log_function
def get_revenue_by_channel(data: dict[str, pd.DataFrame]) -> ChartData:
    """Donut chart: Retail vs Online vs Wholesale."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    channel_names_ar = {
        "Retail": "Retail Branches",
        "Online": "Online Store",
        "Wholesale": "Wholesale"
    }

    if not sales.empty and "Channel" in sales.columns and "Net_Sales_EGP" in sales.columns:
        by_channel = sales.groupby("Channel", observed=False)["Net_Sales_EGP"].sum().reset_index()
        by_channel["Channel_AR"] = by_channel["Channel"].map(lambda x: channel_names_ar.get(str(x), str(x)))

        fig.add_trace(go.Pie(
            labels=by_channel["Channel_AR"],
            values=by_channel["Net_Sales_EGP"],
            hole=0.6,
            marker=dict(colors=[PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE]),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>Sales: %{value:,.0f} EGP (%{percent})<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_revenue_by_channel",
        title="Revenue Distribution by Sales Channel",
        height=380,
        description="Each channel's share (retail branches, online store, wholesale) of total sales"
    )

@log_function
def get_business_unit_efficiency(data: dict[str, pd.DataFrame]) -> ChartData:
    """Grouped bar: operational efficiency per business unit."""
    ops = data.get("Group_Operations", pd.DataFrame())
    fig = go.Figure()

    if not ops.empty and "Business_Unit" in ops.columns and "Operational_Efficiency_Pct" in ops.columns:
        bu_map_ar = {
            "Textiles": "Textiles & Apparel",
            "Apparel": "Manufacturing & Assembly",
            "Printing": "Digital Printing",
            "Retail": "Branch Network",
            "E-Commerce": "E-Commerce"
        }
        ops_copy = ops.copy()
        ops_copy["BU_AR"] = ops_copy["Business_Unit"].map(lambda x: bu_map_ar.get(str(x), str(x)))
        bu_eff = ops_copy.groupby("BU_AR")["Operational_Efficiency_Pct"].mean().reset_index()

        fig.add_trace(go.Bar(
            x=bu_eff["BU_AR"],
            y=bu_eff["Operational_Efficiency_Pct"],
            marker_color=SECONDARY_TEAL,
            text=bu_eff["Operational_Efficiency_Pct"].apply(lambda v: f"{v:.1f}%"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Operational efficiency: %{y:.1f}%<extra></extra>"
        ))
        fig.update_layout(yaxis=dict(range=[0, 105], title="Efficiency (%)"))

    return create_chart_data(
        fig,
        chart_id="chart_bu_efficiency",
        title="Operational Efficiency by Business Unit",
        height=380,
        description="Average operational efficiency across the group's industrial and commercial sectors"
    )

@log_function
def get_top_products(data: dict[str, pd.DataFrame], n: int = 10) -> ChartData:
    """Horizontal bar: top N products by revenue."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    prod = data.get("Product_Master", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Product_ID" in sales.columns and "Net_Sales_EGP" in sales.columns:
        top_p = sales.groupby("Product_ID")["Net_Sales_EGP"].sum().reset_index()
        if not prod.empty and "Product_ID" in prod.columns and "Product_Name" in prod.columns:
            top_p = top_p.merge(prod[["Product_ID", "Product_Name", "Product_Family"]], on="Product_ID", how="left")
            top_p["Label"] = top_p["Product_Name"].fillna(top_p["Product_ID"])
        else:
            top_p["Label"] = top_p["Product_ID"]

        top_p = top_p.sort_values("Net_Sales_EGP", ascending=False).head(n).iloc[::-1]

        fig.add_trace(go.Bar(
            y=top_p["Label"].astype(str),
            x=top_p["Net_Sales_EGP"],
            orientation="h",
            marker=dict(
                color=top_p["Net_Sales_EGP"],
                colorscale=[[0, LIGHT_ORANGE], [1, PRIMARY_ORANGE]],
                showscale=False
            ),
            text=top_p["Net_Sales_EGP"].apply(format_currency_ar),
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Sales: %{x:,.0f} EGP<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_top_products",
        title=f"Top {n} Products by Revenue",
        height=420,
        description="Best-selling and highest-value products across all sales channels"
    )

@log_function
def get_seasonality_heatmap(data: dict[str, pd.DataFrame]) -> ChartData:
    """Heatmap: month × product family revenue intensity."""
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

    if not sales.empty and "Month" in sales.columns and "Product_Family" in sales.columns and "Net_Sales_EGP" in sales.columns:
        pivot = sales.pivot_table(
            index="Product_Family",
            columns="Month",
            values="Net_Sales_EGP",
            aggfunc="sum",
            fill_value=0
        )
        pivot.index = [family_ar.get(str(f), str(f)) for f in pivot.index]
        for m in range(1, 13):
            if m not in pivot.columns:
                pivot[m] = 0
        pivot = pivot[[m for m in range(1, 13)]]
        col_labels = [month_names_ar[m - 1] for m in pivot.columns]

        fig.add_trace(go.Heatmap(
            z=pivot.values / 1000,
            x=col_labels,
            y=list(pivot.index),
            colorscale="Oranges",
            colorbar=dict(title="K EGP"),
            hovertemplate="Family: <b>%{y}</b><br>Month: <b>%{x}</b><br>Sales: %{z:,.1f}K EGP<extra></extra>"
        ))

    return create_chart_data(
        fig,
        chart_id="chart_seasonality_heatmap",
        title="Seasonality Matrix: Product Families by Month",
        height=380,
        description="Demand and sales density by season to pinpoint peak periods for each product line"
    )
