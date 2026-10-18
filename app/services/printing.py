"""
Printing Performance & Downtime Service (Task 13)
Printing batch yields, printing defects, rework costs, machine downtime, and utilization analysis.
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from app.core.models import KPICard, ChartData
from app.core.charts import (
    create_chart_data, format_currency_ar, format_number_ar,
    PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED, ACCENT_GREEN, ACCENT_BLUE, PALETTE
)
from app.core.logger import setup_logger, log_function
from app.core.metrics import pct_change_sum, pp_change_ratio, pp_change_mean

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)


@log_function
def get_printing_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Printing Performance & Downtime."""
    pb = data.get("Printing_Batches", pd.DataFrame())
    md = data.get("Machine_Downtime", pd.DataFrame())

    total_printed = 0
    avg_yield = 0.0
    reprint_rate = 0.0
    total_downtime = 0.0
    consumable_cost = 0.0

    if not pb.empty:
        if "Printed_Qty" in pb.columns:
            total_printed = int(pb["Printed_Qty"].sum())
        if "Good_Qty" in pb.columns and total_printed > 0:
            avg_yield = float((pb["Good_Qty"].sum() / total_printed) * 100)
        if "Reprint_Qty" in pb.columns and total_printed > 0:
            reprint_rate = float((pb["Reprint_Qty"].sum() / total_printed) * 100)
        if "Ink_or_Consumable_Cost_EGP" in pb.columns:
            consumable_cost = float(pb["Ink_or_Consumable_Cost_EGP"].sum())

    if not md.empty and "Downtime_Hours" in md.columns:
        total_downtime = float(md["Downtime_Hours"].sum())

    # REAL deltas: trailing 12-month window vs previous 12-month window
    printed_delta = pct_change_sum(pb, "Printed_Qty", "Print_Date") if not pb.empty else None
    yield_delta = (
        pp_change_ratio(pb, "Good_Qty", "Printed_Qty", "Print_Date")
        if not pb.empty else None
    )
    reprint_delta = (
        pp_change_ratio(pb, "Reprint_Qty", "Printed_Qty", "Print_Date")
        if not pb.empty else None
    )
    downtime_delta = pct_change_sum(md, "Downtime_Hours", "Date") if not md.empty else None
    consumable_delta = pct_change_sum(pb, "Ink_or_Consumable_Cost_EGP", "Print_Date") if not pb.empty else None

    return [
        KPICard(
            title="Total Printed Pieces",
            value=f"{total_printed:,}",
            raw_value=float(total_printed),
            delta=round(printed_delta, 1) if printed_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange",
        ),
        KPICard(
            title="Average Print Yield (%)",
            value=f"{avg_yield:.1f}%",
            raw_value=float(avg_yield),
            delta=round(yield_delta, 2) if yield_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="teal" if avg_yield >= 95 else "orange",
        ),
        KPICard(
            title="Reprint Rate (%)",
            value=f"{reprint_rate:.2f}%",
            raw_value=float(reprint_rate),
            delta=round(reprint_delta, 2) if reprint_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            favorable=False,
            color="danger" if reprint_rate > 3.0 else "teal",
        ),
        KPICard(
            title="Total Downtime Hours",
            value=f"{total_downtime:,.1f} hrs",
            raw_value=float(total_downtime),
            delta=round(downtime_delta, 1) if downtime_delta is not None else None,
            delta_label=PERIOD_LABEL,
            favorable=False,
            color="navy",
        ),
        KPICard(
            title="Ink & Consumables Cost",
            value=format_currency_ar(consumable_cost),
            raw_value=float(consumable_cost),
            delta=round(consumable_delta, 1) if consumable_delta is not None else None,
            delta_label=PERIOD_LABEL,
            neutral_delta=True,
            color="orange",
        ),
    ]


@log_function
def get_machine_yield(data: dict[str, pd.DataFrame]) -> ChartData:
    """Bar chart: Print Yield % across printing machines."""
    pb = data.get("Printing_Batches", pd.DataFrame())
    fig = go.Figure()

    if not pb.empty and "Machine_ID" in pb.columns and "Good_Qty" in pb.columns and "Printed_Qty" in pb.columns:
        grp = pb.groupby("Machine_ID", observed=False).agg({
            "Good_Qty": "sum",
            "Printed_Qty": "sum"
        }).reset_index()
        grp["Yield_Pct"] = (grp["Good_Qty"] / grp["Printed_Qty"].replace(0, np.nan)) * 100
        grp = grp.sort_values("Yield_Pct", ascending=False)

        colors = [SECONDARY_TEAL if y >= 96 else (PRIMARY_ORANGE if y >= 92 else ACCENT_RED) for y in grp["Yield_Pct"]]

        fig.add_trace(go.Bar(
            x=grp["Machine_ID"],
            y=grp["Yield_Pct"],
            text=[f"{v:.1f}%" for v in grp["Yield_Pct"]],
            textposition="auto",
            marker=dict(color=colors, line=dict(color=DARK_NAVY, width=1))
        ))

        fig.add_hline(y=96, line_dash="dash", line_color=DARK_NAVY)
        fig.add_annotation(
            text="Target (96%)",
            xref="paper", x=0.99, xanchor="right",
            yref="paper", y=1.04, yanchor="bottom",
            showarrow=False,
            font=dict(color="#64748B", family="Inter, IBM Plex Sans Arabic, sans-serif", size=11),
        )

    fig.update_layout(
        title="Healthy Print Yield by Machine",
        xaxis_title="Printing machine",
        yaxis_title="Yield (%)",
        yaxis=dict(range=[80, 100])
    )
    return create_chart_data(fig, "machine_yield", "Yield by Printing Machine", height=380)


@log_function
def get_defect_types(data: dict[str, pd.DataFrame]) -> ChartData:
    """Donut chart: Printing defect types distribution."""
    pb = data.get("Printing_Batches", pd.DataFrame())
    fig = go.Figure()

    if not pb.empty and "Defect_Type" in pb.columns:
        counts = pb["Defect_Type"].dropna().value_counts().reset_index()
        counts.columns = ["Defect", "Count"]
        counts = counts[~counts["Defect"].astype(str).str.lower().isin(["none", "nan", "no defect", "no significant issue"])]

        colors = [PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED, "#8b5cf6"]

        fig.add_trace(go.Pie(
            labels=counts["Defect"],
            values=counts["Count"],
            hole=0.55,
            marker=dict(colors=colors),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>Cases: %{value:,.0f} (%{percent})<extra></extra>"
        ))

    fig.update_layout(
        title="Print Defect Distribution (Fading, Smudging, Misalignment)",
        showlegend=True
    )
    return create_chart_data(fig, "defect_types", "Print Defect Distribution", height=380)


@log_function
def get_reprint_cost_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Line/Area chart: Monthly Rework and Consumables Cost trend."""
    pb = data.get("Printing_Batches", pd.DataFrame()).copy()
    fig = go.Figure()

    if not pb.empty and "Print_Date" in pb.columns and "Rework_Cost_EGP" in pb.columns and "Ink_or_Consumable_Cost_EGP" in pb.columns:
        pb["Print_Date"] = pd.to_datetime(pb["Print_Date"], errors="coerce")
        pb["Month"] = pb["Print_Date"].dt.to_period("M").astype(str)
        pb = pb.dropna(subset=["Month"])

        grp = pb.groupby("Month", observed=False).agg({
            "Ink_or_Consumable_Cost_EGP": "sum",
            "Rework_Cost_EGP": "sum"
        }).reset_index().sort_values("Month")

        fig.add_trace(go.Scatter(
            x=grp["Month"],
            y=grp["Ink_or_Consumable_Cost_EGP"],
            name="Ink & consumables cost",
            mode="lines+markers",
            line=dict(color=PRIMARY_ORANGE, width=3),
            marker=dict(size=6)
        ))
        fig.add_trace(go.Scatter(
            x=grp["Month"],
            y=grp["Rework_Cost_EGP"],
            name="Reprint & rework cost",
            mode="lines+markers",
            line=dict(color=ACCENT_RED, width=2.5, dash="dash"),
            marker=dict(size=6)
        ))

    fig.update_layout(
        title="Consumables vs Reprint Cost by Month",
        xaxis_title="Month",
        yaxis_title="Cost (EGP)",
    )
    return create_chart_data(fig, "reprint_cost_trend", "Consumables & Reprint Cost Trend", height=380)


@log_function
def get_downtime_by_reason(data: dict[str, pd.DataFrame]) -> ChartData:
    """Horizontal bar chart: Machine downtime hours grouped by reason."""
    md = data.get("Machine_Downtime", pd.DataFrame())
    fig = go.Figure()

    if not md.empty and "Reason" in md.columns and "Downtime_Hours" in md.columns:
        grp = md.groupby("Reason", observed=False)["Downtime_Hours"].sum().reset_index()
        grp = grp.sort_values("Downtime_Hours", ascending=True)

        reason_ar = {
            "Planned maintenance": "Planned maintenance",
            "Electrical failure": "Electrical failure",
            "Mechanical failure": "Mechanical failure",
            "Operator error": "Operator error",
            "Material shortage": "Material & ink shortage",
            "Changeover / Setup": "Changeover / setup",
            "Quality adjustment": "Quality adjustment & calibration"
        }
        grp["Reason_AR"] = grp["Reason"].map(lambda x: reason_ar.get(str(x), str(x)))

        fig.add_trace(go.Bar(
            y=grp["Reason_AR"],
            x=grp["Downtime_Hours"],
            orientation="h",
            text=[f"{v:,.1f} h" for v in grp["Downtime_Hours"]],
            textposition="auto",
            marker=dict(
                color=PRIMARY_ORANGE,
                line=dict(color=DARK_NAVY, width=1)
            )
        ))

    fig.update_layout(
        title="Factory Downtime Hours by Reason",
        xaxis_title="Downtime (hours)",
        yaxis_title="Reason",
    )
    return create_chart_data(fig, "downtime_by_reason", "Downtime Hours by Reason", height=380)


@log_function
def get_planned_vs_unplanned(data: dict[str, pd.DataFrame]) -> ChartData:
    """Stacked bar: Planned vs Unplanned downtime hours by Business Area."""
    md = data.get("Machine_Downtime", pd.DataFrame())
    fig = go.Figure()

    if not md.empty and "Business_Area" in md.columns and "Planned" in md.columns and "Downtime_Hours" in md.columns:
        pivot = md.pivot_table(
            index="Business_Area",
            columns="Planned",
            values="Downtime_Hours",
            aggfunc="sum",
            fill_value=0
        ).reset_index()

        area_ar = {
            "Printing": "Printing dept.",
            "Cutting": "Cutting & prep dept.",
            "Sewing": "Sewing & assembly dept.",
            "Finishing": "Finishing & pressing dept.",
            "Packaging": "Packaging dept."
        }
        pivot["Area_AR"] = pivot["Business_Area"].map(lambda x: area_ar.get(str(x), str(x)))

        planned_col = "Yes" if "Yes" in pivot.columns else None
        unplanned_col = "No" if "No" in pivot.columns else None

        if planned_col:
            fig.add_trace(go.Bar(
                x=pivot["Area_AR"],
                y=pivot[planned_col],
                name="Planned downtime (maintenance)",
                marker_color=SECONDARY_TEAL,
                text=[f"{v:,.0f}h" for v in pivot[planned_col]],
                textposition="inside"
            ))
        if unplanned_col:
            fig.add_trace(go.Bar(
                x=pivot["Area_AR"],
                y=pivot[unplanned_col],
                name="Unplanned / emergency downtime",
                marker_color=ACCENT_RED,
                text=[f"{v:,.0f}h" for v in pivot[unplanned_col]],
                textposition="inside"
            ))

    fig.update_layout(
        title="Planned vs Unplanned Downtime by Department",
        xaxis_title="Manufacturing department",
        yaxis_title="Downtime hours",
        barmode="stack",
    )
    return create_chart_data(fig, "planned_vs_unplanned", "Planned vs Unplanned Downtime", height=380)


@log_function
def get_machine_utilization_heatmap(data: dict[str, pd.DataFrame]) -> ChartData:
    """Heatmap: Downtime hours by Machine ID and Month."""
    md = data.get("Machine_Downtime", pd.DataFrame()).copy()
    fig = go.Figure()

    if not md.empty and "Date" in md.columns and "Machine_ID" in md.columns and "Downtime_Hours" in md.columns:
        md["Date"] = pd.to_datetime(md["Date"], errors="coerce")
        md["Month"] = md["Date"].dt.to_period("M").astype(str)
        md = md.dropna(subset=["Month"])

        pivot = md.pivot_table(
            index="Machine_ID",
            columns="Month",
            values="Downtime_Hours",
            aggfunc="sum",
            fill_value=0
        )

        fig.add_trace(go.Heatmap(
            z=pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            colorscale="Oranges",
            colorbar=dict(title="Downtime hours"),
            hovertemplate="Machine: %{y}<br>Month: %{x}<br>Downtime: %{z:,.1f} h<extra></extra>"
        ))

    fig.update_layout(
        title="Downtime Heatmap: Machines by Month",
        xaxis_title="Month",
        yaxis_title="Machine code",
    )
    return create_chart_data(fig, "machine_utilization_heatmap", "Machine Downtime Density by Month", height=400)
