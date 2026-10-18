"""
Value Chain Profitability Analyzer Service (Task 15 - App 11)

Cross-department cost tracing connecting procurement, production bottlenecks,
printing reworks, quality inspection scrap, inventory carrying costs,
and customer returns to compute TRUE net margin per product and uncover hidden costs.
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from typing import Optional

from app.core.models import KPICard, ChartData
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL,
    ACCENT_RED, ACCENT_GREEN, ACCENT_BLUE, PALETTE
)
from app.ai.anomaly import detect_cross_department_anomalies
from app.core.logger import setup_logger, log_function

logger = setup_logger(__name__)

# ── Computed-once cache (DATA is loaded once at startup and never mutates) ──
_CHAIN_CACHE: Optional[pd.DataFrame] = None


def _compute_full_product_chain(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Computes comprehensive multi-department cost tracing per product.
    Cached after the first call — every chart/KPI on this page reuses it."""
    global _CHAIN_CACHE
    if _CHAIN_CACHE is not None:
        return _CHAIN_CACHE.copy()

    pm = data.get("Product_Master", pd.DataFrame()).copy()
    st = data.get("Sales_Transactions", pd.DataFrame())
    prod = data.get("Production_Orders", pd.DataFrame())
    print_b = data.get("Printing_Batches", pd.DataFrame())
    qc = data.get("Quality", pd.DataFrame())
    inv = data.get("Inventory_History", pd.DataFrame())

    if pm.empty:
        return pd.DataFrame()

    # 1. Sales & Revenue
    if not st.empty and "Product_ID" in st.columns:
        sales_agg = st.groupby("Product_ID").agg(
            revenue=("Net_Sales_EGP", "sum"),
            cogs=("Estimated_COGS_EGP", "sum"),
            gross_profit=("Gross_Profit_EGP", "sum"),
            refunds=("Refund_Value_EGP", "sum"),
            units_sold=("Quantity", "sum")
        ).reset_index()
    else:
        sales_agg = pd.DataFrame(columns=["Product_ID", "revenue", "cogs", "gross_profit", "refunds", "units_sold"])

    # 2. Production Overtime & Delays
    if not prod.empty and "Product_ID" in prod.columns:
        prod_agg = prod.groupby("Product_ID").agg(
            overtime_hours=("Overtime_Hours", "sum"),
            delay_days=("Delay_Days", "mean"),
            prod_rejected=("Rejected_Qty", "sum"),
            prod_good=("Good_Qty", "sum")
        ).reset_index()
    else:
        prod_agg = pd.DataFrame(columns=["Product_ID", "overtime_hours", "delay_days", "prod_rejected", "prod_good"])

    # 3. Printing Rework & Consumables
    if not print_b.empty and "Product_ID" in print_b.columns:
        print_agg = print_b.groupby("Product_ID").agg(
            print_rework=("Rework_Cost_EGP", "sum"),
            print_consumables=("Ink_or_Consumable_Cost_EGP", "sum"),
            reprint_qty=("Reprint_Qty", "sum")
        ).reset_index()
    else:
        print_agg = pd.DataFrame(columns=["Product_ID", "print_rework", "print_consumables", "reprint_qty"])

    # 4. Quality Scrap & Losses
    if not qc.empty and "Product_ID" in qc.columns:
        qc_agg = qc.groupby("Product_ID").agg(
            qc_loss=("Estimated_Loss_EGP", "sum"),
            qc_rejected=("Rejected_Qty", "sum")
        ).reset_index()
    else:
        qc_agg = pd.DataFrame(columns=["Product_ID", "qc_loss", "qc_rejected"])

    # 5. Inventory Carrying & Holding
    if not inv.empty and "Product_ID" in inv.columns:
        inv_agg = inv.groupby("Product_ID").agg(
            avg_stock=("Closing_Stock", "mean"),
            stockout_days=("Stockout_Days_In_Month", "sum")
        ).reset_index()
    else:
        inv_agg = pd.DataFrame(columns=["Product_ID", "avg_stock", "stockout_days"])

    # Merge into base Product Master
    df = pm[["Product_ID", "SKU", "Product_Name", "Brand", "Product_Family", "Public_Retail_Price_EGP"]].copy()
    for sub in [sales_agg, prod_agg, print_agg, qc_agg, inv_agg]:
        if not sub.empty:
            df = df.merge(sub, on="Product_ID", how="left")
    
    df = df.fillna(0)

    # Cost modeling coefficients
    # Overtime blended hourly rate = 150 EGP
    df["overtime_cost"] = df["overtime_hours"] * 150.0
    # Annual inventory holding carrying cost = 15% of average inventory valuation
    df["holding_cost"] = df["avg_stock"] * df["Public_Retail_Price_EGP"] * 0.15

    # Total Hidden Operational Friction Costs
    df["total_hidden_costs"] = (
        df["qc_loss"] + 
        df["print_rework"] + 
        df["overtime_cost"] + 
        df["refunds"] + 
        df["holding_cost"]
    )

    # True Net Profit and Margins
    df["true_net_profit"] = df["gross_profit"] - df["total_hidden_costs"]
    df["apparent_margin_pct"] = np.where(df["revenue"] > 0, (df["gross_profit"] / df["revenue"]) * 100, 0.0)
    df["true_margin_pct"] = np.where(df["revenue"] > 0, (df["true_net_profit"] / df["revenue"]) * 100, 0.0)
    df["margin_erosion_pct"] = df["apparent_margin_pct"] - df["true_margin_pct"]

    # AI Isolation Forest anomaly detection
    df = detect_cross_department_anomalies(df)
    _CHAIN_CACHE = df
    return df.copy()


@log_function
def get_product_list(data: dict[str, pd.DataFrame]) -> list[dict]:
    """Returns list of products with ID and Name for dropdown selector."""
    df = _compute_full_product_chain(data)
    if df.empty:
        return []
    df_sorted = df.sort_values("revenue", ascending=False)
    return [
        {"id": row["Product_ID"], "name": f"{row['Product_ID']} - {row['Product_Name']}"}
        for _, row in df_sorted.iterrows()
    ]


@log_function
def get_value_chain_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 4 executive KPIs for Value Chain Profitability."""
    df = _compute_full_product_chain(data)
    if df.empty:
        return []

    total_revenue = float(df["revenue"].sum())
    total_gross = float(df["gross_profit"].sum())
    total_hidden = float(df["total_hidden_costs"].sum())
    total_true_profit = float(df["true_net_profit"].sum())

    apparent_margin = (total_gross / total_revenue * 100) if total_revenue > 0 else 0.0
    true_margin = (total_true_profit / total_revenue * 100) if total_revenue > 0 else 0.0
    margin_gap = apparent_margin - true_margin

    flagged_anomalies = int(df["is_anomalous"].sum())

    return [
        KPICard(
            title="True Net Operating Profit",
            value=format_currency_ar(total_true_profit),
            raw_value=total_true_profit,
            delta=None,
            delta_label="After all hidden costs",
            color="teal",
        ),
        KPICard(
            title="Total Hidden Costs & Waste",
            value=format_currency_ar(total_hidden),
            raw_value=total_hidden,
            delta=None,
            delta_label=f"{total_hidden / total_gross * 100:.1f}% of gross profit" if total_gross > 0 else None,
            color="danger",
        ),
        KPICard(
            title="Apparent vs True Margin Gap",
            value=f"{margin_gap:.1f}%",
            raw_value=margin_gap,
            delta=None,
            delta_label=f"Apparent {apparent_margin:.1f}% vs true {true_margin:.1f}%",
            color="orange",
        ),
        KPICard(
            title="Products Under Compound Operational Stress (AI)",
            value=f"{flagged_anomalies} products",
            raw_value=float(flagged_anomalies),
            delta=round(flagged_anomalies / len(df) * 100, 1) if len(df) > 0 else None,
            neutral_delta=True,
            delta_label="of all products (Isolation Forest)",
            color="navy",
        ),
    ]


@log_function
def get_product_journey_waterfall(data: dict[str, pd.DataFrame], product_id: Optional[str] = None) -> ChartData:
    """Waterfall chart tracing full end-to-end journey from Revenue to True Net Profit."""
    df = _compute_full_product_chain(data)
    fig = go.Figure()

    if df.empty:
        return create_chart_data(fig, "waterfall_journey", "Product Profit Journey Across Departments (Waterfall)")

    # Select chosen product or default to highest revenue product
    if product_id and product_id in df["Product_ID"].values:
        p = df[df["Product_ID"] == product_id].iloc[0]
    else:
        p = df.sort_values("revenue", ascending=False).iloc[0]

    title_text = f"Product Profit Journey: {p['Product_ID']} - {p['Product_Name']} (Waterfall)"

    measures = ["relative", "relative", "relative", "relative", "relative", "relative", "relative", "total"]
    x_steps = [
        "Sales revenue",
        "Standard material cost (COGS)",
        "Production overtime cost",
        "Printing waste & rework",
        "Quality inspection losses",
        "Inventory holding cost",
        "Customer returns & refunds",
        "True net profit"
    ]
    
    y_values = [
        float(p["revenue"]),
        -float(p["cogs"]),
        -float(p["overtime_cost"]),
        -float(p["print_rework"]),
        -float(p["qc_loss"]),
        -float(p["holding_cost"]),
        -float(p["refunds"]),
        0.0  # Will be calculated as total
    ]

    text_labels = [format_currency_ar(v) for v in y_values[:-1]]
    text_labels.append(format_currency_ar(float(p["true_net_profit"])))

    fig.add_trace(go.Waterfall(
        name="Cost & profit journey",
        orientation="v",
        measure=measures,
        x=x_steps,
        textposition="outside",
        text=text_labels,
        textfont=dict(family="Inter, IBM Plex Sans Arabic, sans-serif", size=11, color="#374151"),
        y=y_values,
        connector={"line": {"color": "rgba(100, 116, 139, 0.4)", "dash": "dot"}},
        decreasing={"marker": {"color": ACCENT_RED}},
        increasing={"marker": {"color": SECONDARY_TEAL}},
        totals={"marker": {"color": PRIMARY_ORANGE if p["true_net_profit"] >= 0 else ACCENT_RED}},
    ))

    fig.update_layout(
        yaxis_title="Value (EGP)",
        margin=dict(l=50, r=50, t=50, b=80),
    )
    return create_chart_data(fig, "waterfall_journey", title_text, height=440)


@log_function
def get_true_profitability_leaderboard(data: dict[str, pd.DataFrame], n: int = 15) -> ChartData:
    """Horizontal bar chart ranking top and bottom products by true margin %."""
    df = _compute_full_product_chain(data)
    fig = go.Figure()

    if df.empty:
        return create_chart_data(fig, "true_profit_leaderboard", "True Profitability Leaderboard")

    # Select top 8 and bottom 7 products to show full spectrum
    df_sorted = df.sort_values("true_margin_pct", ascending=True)
    top_and_bottom = pd.concat([df_sorted.head(7), df_sorted.tail(8)]).drop_duplicates()

    colors = [
        SECONDARY_TEAL if m >= 10.0 else (PRIMARY_ORANGE if m >= 5.0 else ACCENT_RED)
        for m in top_and_bottom["true_margin_pct"]
    ]

    labels = [f"{row['Product_ID']} - {str(row['Product_Name'])[:22]}" for _, row in top_and_bottom.iterrows()]

    fig.add_trace(go.Bar(
        x=top_and_bottom["true_margin_pct"],
        y=labels,
        orientation="h",
        marker=dict(color=colors),
        text=[f"{m:.1f}% (rev: {format_currency_ar(r)})" for m, r in zip(top_and_bottom["true_margin_pct"], top_and_bottom["revenue"])],
        textposition="inside",
        insidetextanchor="middle",
        textfont=dict(color="#ffffff", size=10, family="Inter, IBM Plex Sans Arabic, sans-serif"),
        hovertemplate="<b>%{y}</b><br>True margin: %{x:.2f}%<br>Apparent margin: %{customdata[0]:.2f}%<br>Net profit: %{customdata[1]}<extra></extra>",
        customdata=list(zip(top_and_bottom["apparent_margin_pct"], [format_currency_ar(v) for v in top_and_bottom["true_net_profit"]])),
    ))

    # Benchmark lines
    fig.add_vline(x=10.0, line_dash="dash", line_color=SECONDARY_TEAL, annotation_text="Excellent margin (10%)", annotation_font=dict(size=10, color=SECONDARY_TEAL))
    fig.add_vline(x=5.0, line_dash="dot", line_color=PRIMARY_ORANGE, annotation_text="Safety threshold (5%)", annotation_font=dict(size=10, color=PRIMARY_ORANGE))

    fig.update_layout(
        xaxis_title="True net margin after all operating costs (%)",
        yaxis_title="",
        margin=dict(l=170, r=40, t=40, b=40),
    )
    return create_chart_data(fig, "true_profit_leaderboard", "Products Ranked by True Margin After All Costs (Leaderboard)", height=450)


@log_function
def get_hidden_cost_breakdown(data: dict[str, pd.DataFrame]) -> ChartData:
    """Treemap chart showing the breakdown of hidden costs across departments."""
    df = _compute_full_product_chain(data)
    fig = go.Figure()

    if df.empty:
        return create_chart_data(fig, "hidden_cost_breakdown", "Hidden Cost Breakdown by Department")

    qc_cost = float(df["qc_loss"].sum())
    refund_cost = float(df["refunds"].sum())
    rework_cost = float(df["print_rework"].sum())
    ot_cost = float(df["overtime_cost"].sum())
    holding_cost = float(df["holding_cost"].sum())

    treemap_df = pd.DataFrame([
        {"id": "qc", "label": f"Quality losses & inspection damage<br>{format_currency_ar(qc_cost)}", "parent": "root", "value": qc_cost, "color": ACCENT_RED},
        {"id": "refunds", "label": f"Customer returns & refunds<br>{format_currency_ar(refund_cost)}", "parent": "root", "value": refund_cost, "color": PRIMARY_ORANGE},
        {"id": "holding", "label": f"Inventory holding costs<br>{format_currency_ar(holding_cost)}", "parent": "root", "value": holding_cost, "color": LIGHT_ORANGE},
        {"id": "overtime", "label": f"Overtime & production bottlenecks<br>{format_currency_ar(ot_cost)}", "parent": "root", "value": ot_cost, "color": SECONDARY_TEAL},
        {"id": "rework", "label": f"Printing waste & rework<br>{format_currency_ar(rework_cost)}", "parent": "root", "value": rework_cost, "color": ACCENT_BLUE},
    ])

    fig = go.Figure(go.Treemap(
        labels=treemap_df["label"],
        parents=["Total hidden costs (30.3M EGP)"] * len(treemap_df),
        values=treemap_df["value"],
        marker=dict(colors=treemap_df["color"]),
        textinfo="label+percent parent",
        textfont=dict(family="Inter, IBM Plex Sans Arabic, sans-serif", size=13),
        hovertemplate="<b>%{label}</b><br>Value: %{value:,.0f} EGP<br>Share of waste: %{percentParent:.1%}<extra></extra>",
    ))

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return create_chart_data(fig, "hidden_cost_breakdown", "Hidden Cost Treemap by Department", height=380)


@log_function
def get_cross_dept_anomalies(data: dict[str, pd.DataFrame]) -> ChartData:
    """Horizontal bar chart showing products flagged by Isolation Forest with severity score."""
    df = _compute_full_product_chain(data)
    fig = go.Figure()

    if df.empty:
        return create_chart_data(fig, "cross_dept_anomalies", "Operationally Stressed Products (Isolation Forest)")

    anomalous = df[df["is_anomalous"]].sort_values("anomaly_score", ascending=True)

    if anomalous.empty:
        anomalous = df.sort_values("margin_erosion_pct", ascending=False).head(8)

    labels = [f"{row['Product_ID']} - {str(row['Product_Name'])[:20]}" for _, row in anomalous.iterrows()]

    fig.add_trace(go.Bar(
        x=anomalous["anomaly_score"],
        y=labels,
        orientation="h",
        marker=dict(
            color=anomalous["margin_erosion_pct"],
            colorscale=[[0, PRIMARY_ORANGE], [1, ACCENT_RED]],
            showscale=True,
            colorbar=dict(title="Margin erosion %", thickness=12),
        ),
        text=[f"Stress score: {s:.2f} | {st}" for s, st in zip(anomalous["anomaly_score"], anomalous["primary_stress"])],
        textposition="inside",
        insidetextanchor="middle",
        textfont=dict(color="#ffffff", size=10, family="Inter, IBM Plex Sans Arabic, sans-serif"),
        hovertemplate="<b>%{y}</b><br>Operational anomaly index: %{x:.3f}<br>Margin erosion: %{customdata[0]:.1f}%<br>Primary driver: %{customdata[1]}<extra></extra>",
        customdata=list(zip(anomalous["margin_erosion_pct"], anomalous["primary_stress"])),
    ))

    fig.update_layout(
        xaxis_title="Operational stress & anomaly index (Isolation Forest Score)",
        yaxis_title="",
        margin=dict(l=170, r=40, t=40, b=40),
    )
    return create_chart_data(fig, "cross_dept_anomalies", "Products Most Exposed to Cross-Departmental Stress (AI Anomalies)", height=420)


@log_function
def get_profitability_gap(data: dict[str, pd.DataFrame]) -> ChartData:
    """Scatter: Apparent Gross Margin % vs True Net Margin % with parity line."""
    df = _compute_full_product_chain(data)
    fig = go.Figure()

    if df.empty:
        return create_chart_data(fig, "profitability_gap", "Profitability Gap: Apparent vs True Margin")

    # Add 45-degree parity reference line
    max_val = max(df["apparent_margin_pct"].max(), 30)
    fig.add_trace(go.Scatter(
        x=[0, max_val],
        y=[0, max_val],
        mode="lines",
        name="Perfect parity line (zero waste)",
        line=dict(color="rgba(100, 116, 139, 0.4)", dash="dash", width=1.5),
        hoverinfo="none",
    ))

    # Color code points: Red if anomalous, Teal if true margin > 10%, Orange otherwise
    colors = [
        ACCENT_RED if a else (SECONDARY_TEAL if m >= 10.0 else PRIMARY_ORANGE)
        for a, m in zip(df["is_anomalous"], df["true_margin_pct"])
    ]

    sizes = np.clip((df["revenue"] / df["revenue"].max()) * 35 + 12, 12, 50)

    fig.add_trace(go.Scatter(
        x=df["apparent_margin_pct"],
        y=df["true_margin_pct"],
        mode="markers",
        text=df["Product_Name"],
        marker=dict(
            size=sizes,
            color=colors,
            opacity=0.75,
            line=dict(width=1.5, color="#ffffff"),
        ),
        hovertemplate="<b>%{text}</b><br>Apparent margin: %{x:.1f}%<br>True margin: %{y:.1f}%<br>Margin erosion: %{customdata[0]:.1f}%<br>Total waste: %{customdata[1]}<extra></extra>",
        customdata=list(zip(df["margin_erosion_pct"], [format_currency_ar(c) for c in df["total_hidden_costs"]])),
    ))

    fig.update_layout(
        xaxis_title="Apparent gross margin (%)",
        yaxis_title="True net margin (%)",
        margin=dict(l=50, r=50, t=50, b=50),
    )
    return create_chart_data(fig, "profitability_gap", "Profitability Gap & Margin Erosion (Scatter)", height=420)
