"""
Factory Production & Bottlenecks Service (Task 11)
Analyzes factory throughput, line efficiency, bottleneck Pareto, delay patterns, and overtime.
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
def get_production_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Factory Production & Bottlenecks."""
    po = data.get("Production_Orders", pd.DataFrame())

    total_produced = 0
    avg_efficiency = 0.0
    delay_rate = 0.0
    avg_delay_days = 0.0
    reject_rate = 0.0

    if not po.empty:
        if "Produced_Qty" in po.columns:
            total_produced = int(po["Produced_Qty"].sum())
        if "Efficiency_Pct" in po.columns:
            avg_efficiency = float(po["Efficiency_Pct"].mean())
        if "Delay_Days" in po.columns:
            delayed = po["Delay_Days"] > 0
            delay_rate = float(delayed.mean() * 100)
            if delayed.any():
                avg_delay_days = float(po.loc[delayed, "Delay_Days"].mean())
        if "Rejected_Qty" in po.columns and "Produced_Qty" in po.columns and total_produced > 0:
            reject_rate = float((po["Rejected_Qty"].sum() / total_produced) * 100)

    # REAL deltas: trailing 12-month window vs previous 12-month window
    produced_delta = pct_change_sum(po, "Produced_Qty", "Start_Date") if not po.empty else None
    eff_delta = pp_change_mean(po, "Efficiency_Pct", "Start_Date") if not po.empty else None
    delay_delta = pp_change_mean(po, "Delay_Days", "Start_Date") if not po.empty else None
    reject_delta = (
        pp_change_ratio(po, "Rejected_Qty", "Produced_Qty", "Start_Date")
        if not po.empty else None
    )

    return [
        KPICard(
            title="Units Produced",
            value=f"{total_produced:,}",
            raw_value=float(total_produced),
            delta=round(produced_delta, 1) if produced_delta is not None else None,
            delta_label=PERIOD_LABEL,
            color="orange",
        ),
        KPICard(
            title="Average Operational Efficiency",
            value=f"{avg_efficiency:.1f}%",
            raw_value=float(avg_efficiency),
            delta=round(eff_delta, 2) if eff_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="teal" if avg_efficiency >= 80 else "orange",
        ),
        KPICard(
            title="Late Orders Share",
            value=f"{delay_rate:.1f}%",
            raw_value=float(delay_rate),
            delta=None,
            delta_label="All-time total share",
            color="danger" if delay_rate > 15 else "teal",
        ),
        KPICard(
            title="Average Delay Days",
            value=f"{avg_delay_days:.1f} days",
            raw_value=float(avg_delay_days),
            delta=round(delay_delta, 2) if delay_delta is not None else None,
            delta_label=PERIOD_LABEL + " (days/order)",
            favorable=False,
            color="navy",
        ),
        KPICard(
            title="Factory QC Rejection Rate",
            value=f"{reject_rate:.2f}%",
            raw_value=float(reject_rate),
            delta=round(reject_delta, 2) if reject_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            favorable=False,
            color="teal" if reject_rate <= 2.0 else "danger",
        ),
    ]


@log_function
def get_efficiency_by_line(data: dict[str, pd.DataFrame]) -> ChartData:
    """Bar chart: Operational Efficiency % across factory production lines."""
    po = data.get("Production_Orders", pd.DataFrame())
    fig = go.Figure()

    if not po.empty and "Line_ID" in po.columns and "Efficiency_Pct" in po.columns:
        grp = po.groupby("Line_ID", observed=False)["Efficiency_Pct"].mean().reset_index()
        grp = grp.sort_values("Efficiency_Pct", ascending=False)

        colors = [SECONDARY_TEAL if eff >= 85 else (PRIMARY_ORANGE if eff >= 75 else ACCENT_RED) for eff in grp["Efficiency_Pct"]]

        fig.add_trace(go.Bar(
            x=grp["Line_ID"],
            y=grp["Efficiency_Pct"],
            text=[f"{v:.1f}%" for v in grp["Efficiency_Pct"]],
            textposition="auto",
            marker=dict(color=colors, line=dict(color=DARK_NAVY, width=1)),
            name="Average efficiency %"
        ))

        fig.add_hline(
            y=85, line_dash="dash", line_color=DARK_NAVY,
            annotation_text="Target (85%)", annotation_position="top left"
        )

    fig.update_layout(
        title="Average Efficiency by Production Line",
        xaxis_title="Production line",
        yaxis_title="Operational efficiency (%)",
        yaxis=dict(range=[0, 100])
    )
    return create_chart_data(fig, "efficiency_by_line", "Efficiency by Production Line", height=380)


@log_function
def get_plan_vs_actual(data: dict[str, pd.DataFrame]) -> ChartData:
    """Grouped bar: Planned Quantity vs Actual Produced Quantity by month."""
    po = data.get("Production_Orders", pd.DataFrame()).copy()
    fig = go.Figure()

    if not po.empty and "Start_Date" in po.columns and "Planned_Qty" in po.columns and "Produced_Qty" in po.columns:
        po["Start_Date"] = pd.to_datetime(po["Start_Date"], errors="coerce")
        po["Month"] = po["Start_Date"].dt.to_period("M").astype(str)
        po = po.dropna(subset=["Month"])

        grp = po.groupby("Month", observed=False).agg({
            "Planned_Qty": "sum",
            "Produced_Qty": "sum"
        }).reset_index().sort_values("Month")

        fig.add_trace(go.Bar(
            x=grp["Month"],
            y=grp["Planned_Qty"],
            name="Planned quantity",
            marker_color=DARK_NAVY,
            text=[format_number_ar(v) for v in grp["Planned_Qty"]],
            textposition="outside"
        ))
        fig.add_trace(go.Bar(
            x=grp["Month"],
            y=grp["Produced_Qty"],
            name="Actual produced quantity",
            marker_color=PRIMARY_ORANGE,
            text=[format_number_ar(v) for v in grp["Produced_Qty"]],
            textposition="outside"
        ))

    fig.update_layout(
        title="Planned vs Actual Production by Month",
        xaxis_title="Month",
        yaxis_title="Pieces",
        barmode="group",
    )
    return create_chart_data(fig, "plan_vs_actual", "Planned vs Actual Production by Month", height=400)


@log_function
def get_bottleneck_pareto(data: dict[str, pd.DataFrame]) -> ChartData:
    """Pareto chart: Primary factory bottlenecks with cumulative percentage."""
    po = data.get("Production_Orders", pd.DataFrame())
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if not po.empty and "Primary_Bottleneck" in po.columns:
        counts = po["Primary_Bottleneck"].dropna().value_counts().reset_index()
        counts.columns = ["Bottleneck", "Count"]
        counts = counts[~counts["Bottleneck"].astype(str).str.lower().isin(["none", "nan", "no bottleneck"])]

        if not counts.empty:
            counts["Cumulative_Pct"] = (counts["Count"].cumsum() / counts["Count"].sum()) * 100

            fig.add_trace(go.Bar(
                x=counts["Bottleneck"],
                y=counts["Count"],
                name="Bottleneck frequency",
                marker_color=PRIMARY_ORANGE,
                text=counts["Count"],
                textposition="auto"
            ), secondary_y=False)

            fig.add_trace(go.Scatter(
                x=counts["Bottleneck"],
                y=counts["Cumulative_Pct"],
                name="Cumulative share (%)",
                marker_color=DARK_NAVY,
                mode="lines+markers",
                line=dict(width=3, color=DARK_NAVY),
                text=[f"{v:.0f}%" for v in counts["Cumulative_Pct"]],
            ), secondary_y=True)

            fig.add_hline(y=80, line_dash="dash", line_color=ACCENT_RED, secondary_y=True,
                          annotation_text="Pareto rule (80%)", annotation_position="bottom right")

    fig.update_layout(
        title="Pareto Chart of Production Line Bottlenecks & Downtime",
        xaxis_title="Bottleneck type",
    )
    fig.update_yaxes(title_text="Cases", secondary_y=False)
    fig.update_yaxes(title_text="Cumulative share (%)", range=[0, 105], secondary_y=True)

    return create_chart_data(fig, "bottleneck_pareto", "Production Bottleneck Pareto Analysis", height=400)


@log_function
def get_delay_distribution(data: dict[str, pd.DataFrame]) -> ChartData:
    """Categorical distribution of delivery delay days."""
    po = data.get("Production_Orders", pd.DataFrame())
    fig = go.Figure()

    if not po.empty and "Delay_Days" in po.columns:
        delays = po["Delay_Days"].fillna(0)

        bins = [-1, 0, 3, 7, 14, 1000]
        labels = ["On time (0 days)", "Slight delay (1-3 days)", "Moderate delay (4-7 days)", "Noticeable delay (8-14 days)", "Critical delay (>14 days)"]
        cats = pd.cut(delays, bins=bins, labels=labels)
        counts = cats.value_counts()[labels].reset_index()
        counts.columns = ["Bucket", "Orders_Count"]

        colors = [ACCENT_GREEN, LIGHT_TEAL, SECONDARY_TEAL, "#C2410C", ACCENT_RED]

        fig.add_trace(go.Bar(
            x=counts["Bucket"],
            y=counts["Orders_Count"],
            text=[f"{int(v):,} orders" for v in counts["Orders_Count"]],
            textposition="auto",
            marker=dict(color=colors)
        ))

    fig.update_layout(
        title="Production Order Delay Distribution",
        xaxis_title="Delay category",
        yaxis_title="Production orders",
    )
    return create_chart_data(fig, "delay_distribution", "Production Order Delay Distribution", height=380)


@log_function
def get_overtime_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Monthly overtime hours trend across factory operations."""
    po = data.get("Production_Orders", pd.DataFrame()).copy()
    fig = go.Figure()

    if not po.empty and "Start_Date" in po.columns and "Overtime_Hours" in po.columns:
        po["Start_Date"] = pd.to_datetime(po["Start_Date"], errors="coerce")
        po["Month"] = po["Start_Date"].dt.to_period("M").astype(str)
        po = po.dropna(subset=["Month"])

        grp = po.groupby("Month", observed=False)["Overtime_Hours"].sum().reset_index().sort_values("Month")

        fig.add_trace(go.Scatter(
            x=grp["Month"],
            y=grp["Overtime_Hours"],
            mode="lines+markers",
            fill="tozeroy",
            line=dict(color=PRIMARY_ORANGE, width=3),
            fillcolor="rgba(232, 114, 12, 0.15)",
            marker=dict(size=6, color=DARK_NAVY),
            name="Overtime hours"
        ))

    fig.update_layout(
        title="Factory Overtime Hours by Month",
        xaxis_title="Month",
        yaxis_title="Total overtime hours",
    )
    return create_chart_data(fig, "overtime_trend", "Monthly Overtime Hours Trend", height=380)


@log_function
def get_efficiency_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Multi-line: Monthly efficiency trend for top production lines."""
    po = data.get("Production_Orders", pd.DataFrame()).copy()
    fig = go.Figure()

    if not po.empty and "Start_Date" in po.columns and "Line_ID" in po.columns and "Efficiency_Pct" in po.columns:
        po["Start_Date"] = pd.to_datetime(po["Start_Date"], errors="coerce")
        po["Month"] = po["Start_Date"].dt.to_period("M").astype(str)
        po = po.dropna(subset=["Month"])

        grp = po.groupby(["Month", "Line_ID"], observed=False)["Efficiency_Pct"].mean().reset_index()

        lines = grp["Line_ID"].unique()
        colors = [PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_BLUE]

        for idx, line in enumerate(sorted(lines)):
            sub = grp[grp["Line_ID"] == line].sort_values("Month")
            fig.add_trace(go.Scatter(
                x=sub["Month"],
                y=sub["Efficiency_Pct"],
                mode="lines+markers",
                name=f"Line {line}",
                line=dict(color=colors[idx % len(colors)], width=2.5),
                marker=dict(size=5)
            ))

    fig.update_layout(
        title="Efficiency Trend by Production Line",
        xaxis_title="Month",
        yaxis_title="Efficiency (%)",
        yaxis=dict(range=[50, 100])
    )
    return create_chart_data(fig, "efficiency_trend", "Efficiency Trend Across Months by Line", height=400)
