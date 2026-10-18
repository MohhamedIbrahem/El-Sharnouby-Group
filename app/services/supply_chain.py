"""
Supply Chain & Materials Management Service (Task 14)

Supplier performance scoring, procurement costs, lead time distribution,
material quality acceptance, supplier risk matrix, and material criticality.
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from app.core.models import KPICard, ChartData
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL,
    ACCENT_RED, ACCENT_GREEN, ACCENT_BLUE, PALETTE
)
from app.core.logger import setup_logger, log_function
from app.core.metrics import (
    pct_change_sum, pct_change_count, pct_change_ratio_windowed,
    pp_change_ratio, pct_change_mean,
)

PERIOD_LABEL = "vs prior 6 months"

logger = setup_logger(__name__)


def _prepare_po_data(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Helper to merge Purchase_Orders with Suppliers and Materials."""
    po = data.get("Purchase_Orders", pd.DataFrame()).copy()
    if po.empty:
        return po

    sup = data.get("Suppliers", pd.DataFrame())
    mat = data.get("Materials", pd.DataFrame())

    if not sup.empty and "Supplier_ID" in po.columns and "Supplier_ID" in sup.columns:
        po = po.merge(sup[["Supplier_ID", "Supplier_Name", "Primary_Category", "Governorate"]], on="Supplier_ID", how="left")
    
    if not mat.empty and "Material_ID" in po.columns and "Material_ID" in mat.columns:
        po = po.merge(mat[["Material_ID", "Material_Category", "Standard_Lead_Time_Days"]], on="Material_ID", how="left")

    if "Actual_Receipt_Date" in po.columns and "Order_Date" in po.columns:
        po["Lead_Time_Days"] = (po["Actual_Receipt_Date"] - po["Order_Date"]).dt.days
    else:
        po["Lead_Time_Days"] = 12

    if "Days_Late" not in po.columns and "Promised_Date" in po.columns and "Actual_Receipt_Date" in po.columns:
        po["Days_Late"] = (po["Actual_Receipt_Date"] - po["Promised_Date"]).dt.days

    po["On_Time"] = po["Days_Late"] <= 0
    po["Spend_EGP"] = po["Ordered_Qty"] * po["Unit_Cost_EGP"]
    po["Acceptance_Rate"] = np.where(po["Ordered_Qty"] > 0, (po["Accepted_Qty"] / po["Ordered_Qty"]) * 100, 100.0)
    po["Rejection_Rate"] = np.where(po["Ordered_Qty"] > 0, (po["Rejected_Qty"] / po["Ordered_Qty"]) * 100, 0.0)
    return po


@log_function
def get_supply_chain_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Supply Chain & Materials."""
    po = _prepare_po_data(data)
    
    total_spend = 0.0
    otif_rate = 0.0
    acceptance_rate = 0.0
    avg_lead_time = 0.0
    total_pos = 0

    if not po.empty:
        total_spend = float(po["Spend_EGP"].sum())
        total_pos = len(po)
        otif_rate = float(po["On_Time"].mean() * 100) if "On_Time" in po.columns else 0.0
        if po["Ordered_Qty"].sum() > 0:
            acceptance_rate = float((po["Accepted_Qty"].sum() / po["Ordered_Qty"].sum()) * 100)
        avg_lead_time = float(po["Lead_Time_Days"].mean()) if "Lead_Time_Days" in po.columns else 0.0

    # REAL deltas: trailing 6-month window vs previous 6-month window
    # (only ~3,600 POs over 36 months, so 6-month windows are steadier than 12)
    spend_delta = pct_change_sum(po, "Spend_EGP", "Order_Date", months=6) if not po.empty else None
    otif_delta = pp_change_ratio(po, "On_Time", "On_Time", "Order_Date", months=6) if not po.empty else None
    acceptance_delta = (
        pp_change_ratio(po, "Accepted_Qty", "Ordered_Qty", "Order_Date", months=6)
        if not po.empty else None
    )
    lead_delta = pct_change_mean(po, "Lead_Time_Days", "Order_Date", months=6) if not po.empty else None
    pos_delta = pct_change_count(po, "Order_Date", months=6) if not po.empty else None

    return [
        KPICard(
            title="Total Procurement Spend",
            value=format_currency_ar(total_spend),
            raw_value=total_spend,
            delta=round(spend_delta, 1) if spend_delta is not None else None,
            neutral_delta=True,
            delta_label=PERIOD_LABEL,
            color="orange",
        ),
        KPICard(
            title="On-Time Delivery (OTIF)",
            value=f"{otif_rate:.1f}%",
            raw_value=otif_rate,
            delta=round(otif_delta, 2) if otif_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="teal" if otif_rate >= 70 else "danger",
        ),
        KPICard(
            title="Raw Material Quality Acceptance",
            value=f"{acceptance_rate:.2f}%",
            raw_value=acceptance_rate,
            delta=round(acceptance_delta, 2) if acceptance_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="teal" if acceptance_rate >= 98 else "orange",
        ),
        KPICard(
            title="Average Lead Time",
            value=f"{avg_lead_time:.1f} days",
            raw_value=avg_lead_time,
            delta=round(lead_delta, 1) if lead_delta is not None else None,
            favorable=False,
            delta_label=PERIOD_LABEL,
            color="navy",
        ),
        KPICard(
            title="Total Purchase Orders (POs)",
            value=format_number_ar(total_pos),
            raw_value=float(total_pos),
            delta=round(pos_delta, 1) if pos_delta is not None else None,
            neutral_delta=True,
            delta_label=PERIOD_LABEL,
            color="navy",
        ),
    ]


@log_function
def get_supplier_scorecard(data: dict[str, pd.DataFrame]) -> ChartData:
    """Radar chart comparing key suppliers across 5 operational dimensions."""
    po = _prepare_po_data(data)
    if po.empty or "Supplier_Name" not in po.columns:
        fig = go.Figure()
        return create_chart_data(fig, "supplier_scorecard", "Supplier Radar Scorecard")

    # Aggregate by supplier
    sup_stats = po.groupby("Supplier_Name").agg(
        otif=("On_Time", lambda s: s.mean() * 100),
        quality=("Acceptance_Rate", "mean"),
        lead_time=("Lead_Time_Days", "mean"),
        spend=("Spend_EGP", "sum"),
        orders=("PO_ID", "count")
    ).reset_index()

    # Normalize metrics to 0-100 scale for radar
    categories = [
        "On-time delivery (OTIF %)",
        "Raw material quality (acceptance %)",
        "Delivery speed (index)",
        "Supply volume (index)",
        "Supply stability (%)"
    ]

    fig = go.Figure()

    # Select top 4 diverse suppliers for clear visualization
    top_sups = sup_stats.sort_values("spend", ascending=False).head(4)
    colors = [PRIMARY_ORANGE, SECONDARY_TEAL, ACCENT_BLUE, "#8b5cf6"]

    max_lead = max(sup_stats["lead_time"].max(), 25)
    max_orders = max(sup_stats["orders"].max(), 350)

    for idx, (_, row) in enumerate(top_sups.iterrows()):
        speed_score = max(0, min(100, (1 - (row["lead_time"] / max_lead)) * 100))
        volume_score = min(100, (row["orders"] / max_orders) * 100)
        stability_score = min(100, (row["otif"] * 0.6 + row["quality"] * 0.4))

        values = [
            round(row["otif"], 1),
            round(row["quality"], 1),
            round(speed_score, 1),
            round(volume_score, 1),
            round(stability_score, 1)
        ]
        values.append(values[0])  # Close the radar polygon

        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=categories + [categories[0]],
            fill="toself",
            name=str(row["Supplier_Name"]).replace("(anonymized)", "").strip(),
            line=dict(color=colors[idx % len(colors)], width=2),
            opacity=0.65,
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                showticklabels=True,
                tickfont=dict(size=10, color="#64748b"),
                gridcolor="rgba(226, 232, 240, 0.8)",
            ),
            angularaxis=dict(
                tickfont=dict(family="Inter, IBM Plex Sans Arabic, sans-serif", size=11, color="#374151"),
                gridcolor="rgba(226, 232, 240, 0.8)",
                rotation=90,
                direction="clockwise",
            ),
            bgcolor="rgba(0,0,0,0)"
        ),
        margin=dict(l=60, r=60, t=50, b=50),
    )
    return create_chart_data(fig, "supplier_scorecard", "Balanced Supplier Scorecard (Radar)", height=420)


@log_function
def get_lead_time_distribution(data: dict[str, pd.DataFrame]) -> ChartData:
    """Box plot of lead time in days across material categories."""
    po = _prepare_po_data(data)
    fig = go.Figure()

    if po.empty or "Material_Category" not in po.columns:
        return create_chart_data(fig, "lead_time_dist", "Lead Time Distribution by Material Category")

    cat_names_ar = {
        "Fabric": "Fabrics",
        "Trims": "Trims & Threads",
        "Printing": "Inks & Printing Materials",
        "Packaging": "Packaging Materials"
    }

    colors = [PRIMARY_ORANGE, SECONDARY_TEAL, ACCENT_BLUE, LIGHT_ORANGE]

    for idx, (cat, sub_df) in enumerate(po.groupby("Material_Category")):
        cat_ar = cat_names_ar.get(cat, cat)
        color = colors[idx % len(colors)]
        fig.add_trace(go.Box(
            y=sub_df["Lead_Time_Days"],
            name=cat_ar,
            boxmean=True,
            marker_color=color,
            line_width=1.5,
            hovertemplate="<b>%{x}</b><br>Lead time: %{y} days<extra></extra>",
        ))

    fig.update_layout(
        yaxis_title="Actual lead time (days)",
        xaxis_title="Material category",
        boxmode="group",
    )
    return create_chart_data(fig, "lead_time_dist", "Actual Lead Time by Material Category (Box Plot)", height=380)


@log_function
def get_acceptance_rate(data: dict[str, pd.DataFrame]) -> ChartData:
    """Horizontal bar chart ranking all suppliers by material acceptance rate %."""
    po = _prepare_po_data(data)
    fig = go.Figure()

    if po.empty or "Supplier_Name" not in po.columns:
        return create_chart_data(fig, "acceptance_rate", "Material Quality Acceptance by Supplier")

    sup_acc = po.groupby("Supplier_Name").agg(
        accepted=("Accepted_Qty", "sum"),
        ordered=("Ordered_Qty", "sum"),
    ).reset_index()
    sup_acc["rate"] = (sup_acc["accepted"] / sup_acc["ordered"]) * 100
    sup_acc = sup_acc.sort_values("rate", ascending=True)

    # Color code by threshold: >= 98% green/teal, < 98% orange/red
    bar_colors = [SECONDARY_TEAL if r >= 98.2 else PRIMARY_ORANGE for r in sup_acc["rate"]]

    clean_names = [s.replace("(anonymized)", "").strip() for s in sup_acc["Supplier_Name"]]

    fig.add_trace(go.Bar(
        x=sup_acc["rate"],
        y=clean_names,
        orientation="h",
        marker=dict(color=bar_colors),
        text=[f"{r:.2f}%" for r in sup_acc["rate"]],
        textposition="inside",
        insidetextanchor="middle",
        textfont=dict(color="#ffffff", size=11, family="Inter, IBM Plex Sans Arabic, sans-serif"),
        hovertemplate="<b>%{y}</b><br>Acceptance rate: %{x:.2f}%<extra></extra>",
    ))

    # Add 98% benchmark line (label sits in the clear band above the axes)
    fig.add_vline(
        x=98.0,
        line_dash="dash",
        line_color=ACCENT_RED,
        annotation=dict(
            text="Target (98%)",
            font=dict(color=ACCENT_RED, family="Inter, IBM Plex Sans Arabic, sans-serif", size=11),
            xshift=-6,
            yref="paper",
            y=1.02,
            yanchor="bottom",
            xanchor="right",
        ),
    )

    fig.update_layout(
        xaxis=dict(title="Acceptance rate (%)", range=[95, 100]),
        yaxis=dict(title=""),
        margin=dict(l=140, r=30, t=40, b=40),
    )
    return create_chart_data(fig, "acceptance_rate", "Raw Material Quality Acceptance by Supplier", height=420)


@log_function
def get_cost_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Monthly unit cost trend by material category over time."""
    po = _prepare_po_data(data)
    fig = go.Figure()

    if po.empty or "Order_Date" not in po.columns or "Material_Category" not in po.columns:
        return create_chart_data(fig, "cost_trend", "Average Material Unit Cost Trend")

    po["Year_Month"] = po["Order_Date"].dt.to_period("M").astype(str)
    cost_trend = po.groupby(["Year_Month", "Material_Category"])["Unit_Cost_EGP"].mean().reset_index()

    cat_names_ar = {
        "Fabric": "Fabrics",
        "Trims": "Trims",
        "Printing": "Printing materials",
        "Packaging": "Packaging"
    }
    colors = [PRIMARY_ORANGE, SECONDARY_TEAL, ACCENT_BLUE, LIGHT_ORANGE]

    for idx, (cat, sub_df) in enumerate(cost_trend.groupby("Material_Category")):
        cat_ar = cat_names_ar.get(cat, cat)
        sub_df = sub_df.sort_values("Year_Month")
        fig.add_trace(go.Scatter(
            x=sub_df["Year_Month"],
            y=sub_df["Unit_Cost_EGP"],
            mode="lines+markers",
            name=cat_ar,
            line=dict(color=colors[idx % len(colors)], width=2.5),
            marker=dict(size=5),
            hovertemplate="<b>%{x}</b><br>" + cat_ar + ": %{y:.2f} EGP<extra></extra>",
        ))

    fig.update_layout(
        xaxis_title="Month",
        yaxis_title="Average unit cost (EGP)",
    )
    return create_chart_data(fig, "cost_trend", "Monthly Raw Material Unit Cost Trend", height=380)


@log_function
def get_supplier_risk_matrix(data: dict[str, pd.DataFrame]) -> ChartData:
    """Scatter: Delivery Risk (% orders late) vs Quality Risk (% rejected qty)."""
    po = _prepare_po_data(data)
    fig = go.Figure()

    if po.empty or "Supplier_Name" not in po.columns:
        return create_chart_data(fig, "supplier_risk_matrix", "Supplier Risk Matrix (Late vs Rejected)")

    sup_risk = po.groupby("Supplier_Name").agg(
        total_orders=("PO_ID", "count"),
        late_orders=("On_Time", lambda s: (~s).sum()),
        total_ordered=("Ordered_Qty", "sum"),
        total_rejected=("Rejected_Qty", "sum"),
        total_spend=("Spend_EGP", "sum"),
    ).reset_index()

    sup_risk["delay_rate"] = (sup_risk["late_orders"] / sup_risk["total_orders"]) * 100
    sup_risk["rejection_rate"] = (sup_risk["total_rejected"] / sup_risk["total_ordered"]) * 100
    clean_names = [s.replace("(anonymized)", "").strip() for s in sup_risk["Supplier_Name"]]

    # Normalize bubble size
    max_spend = sup_risk["total_spend"].max()
    sizes = np.clip((sup_risk["total_spend"] / max_spend) * 45 + 15, 15, 60)

    # Color code risk: High Delay (>35%) or High Rejection (>2%) = Red
    colors = [
        ACCENT_RED if (d > 35 or r > 2.0) else (PRIMARY_ORANGE if (d > 30 or r > 1.8) else SECONDARY_TEAL)
        for d, r in zip(sup_risk["delay_rate"], sup_risk["rejection_rate"])
    ]

    fig.add_trace(go.Scatter(
        x=sup_risk["delay_rate"],
        y=sup_risk["rejection_rate"],
        mode="markers+text",
        text=clean_names,
        textposition="top center",
        textfont=dict(family="Inter, IBM Plex Sans Arabic, sans-serif", size=10, color="#1F2937"),
        marker=dict(
            size=sizes,
            color=colors,
            opacity=0.75,
            line=dict(width=1.5, color="#ffffff"),
        ),
        hovertemplate="<b>%{text}</b><br>Late orders: %{x:.1f}%<br>Rejected qty: %{y:.2f}%<br>Spend: %{customdata}<extra></extra>",
        customdata=[format_currency_ar(s) for s in sup_risk["total_spend"]],
    ))

    # Add quadrant threshold lines
    fig.add_vline(x=32.0, line_dash="dot", line_color="rgba(100, 116, 139, 0.4)")
    fig.add_hline(y=1.8, line_dash="dot", line_color="rgba(100, 116, 139, 0.4)")

    fig.update_layout(
        xaxis_title="Delivery risk: % late orders",
        yaxis_title="Quality risk: % rejected qty",
        margin=dict(l=50, r=50, t=50, b=50),
    )
    return create_chart_data(fig, "supplier_risk_matrix", "Supplier Risk Matrix: Delivery vs Quality (Risk Matrix)", height=420)


@log_function
def get_material_criticality(data: dict[str, pd.DataFrame]) -> ChartData:
    """Bubble chart: Lead Time vs Unit Cost vs Total Procurement Spend."""
    po = _prepare_po_data(data)
    fig = go.Figure()

    if po.empty or "Material_Name" not in po.columns:
        return create_chart_data(fig, "material_criticality", "Raw Material Criticality Analysis")

    mat_summary = po.groupby(["Material_Name", "Material_Category"]).agg(
        avg_cost=("Unit_Cost_EGP", "mean"),
        avg_lead=("Lead_Time_Days", "mean"),
        total_spend=("Spend_EGP", "sum"),
        total_orders=("PO_ID", "count"),
    ).reset_index()

    cat_colors = {
        "Fabric": PRIMARY_ORANGE,
        "Trims": SECONDARY_TEAL,
        "Printing": ACCENT_BLUE,
        "Packaging": "#8b5cf6"
    }

    max_spend = mat_summary["total_spend"].max()

    for cat, sub_df in mat_summary.groupby("Material_Category"):
        color = cat_colors.get(cat, DARK_NAVY)
        sizes = np.clip((sub_df["total_spend"] / max_spend) * 45 + 16, 16, 60)
        
        fig.add_trace(go.Scatter(
            x=sub_df["avg_lead"],
            y=sub_df["avg_cost"],
            mode="markers+text",
            name=cat,
            text=sub_df["Material_Name"],
            textposition="top center",
            textfont=dict(family="Inter, IBM Plex Sans Arabic, sans-serif", size=10, color="#374151"),
            marker=dict(
                size=sizes,
                color=color,
                opacity=0.75,
                line=dict(width=1.5, color="#ffffff"),
            ),
            hovertemplate="<b>%{text}</b> (" + str(cat) + ")<br>Avg payment term: %{x:.1f} days<br>Avg unit cost: %{y:.2f} EGP<br>Total spend: %{customdata}<extra></extra>",
            customdata=[format_currency_ar(s) for s in sub_df["total_spend"]],
        ))

    fig.update_layout(
        xaxis_title="Average actual payment term (days)",
        yaxis_title="Average unit cost (EGP)",
    )
    return create_chart_data(fig, "material_criticality", "Material Criticality: Payment Term vs Cost vs Spend", height=420)
