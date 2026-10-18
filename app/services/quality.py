"""
Quality, Returns & COPQ Service (Task 12)
QC inspections, defect Pareto, root causes, quality cost losses, and correlation with customer returns.
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
from app.core.metrics import pct_change_sum, pct_change_count, pp_change_ratio, pp_change_mean

PERIOD_LABEL = "vs prior 12 months"

logger = setup_logger(__name__)


@log_function
def get_quality_kpis(data: dict[str, pd.DataFrame]) -> list[KPICard]:
    """Calculates 5 KPIs for Quality & Returns."""
    qc = data.get("Quality", pd.DataFrame())
    sales = data.get("Sales_Transactions", pd.DataFrame())

    total_inspected = 0
    pass_rate = 0.0
    reject_rate = 0.0
    quality_loss = 0.0
    return_rate = 0.0

    if not qc.empty:
        if "Inspected_Qty" in qc.columns:
            total_inspected = int(qc["Inspected_Qty"].sum())
        if "Passed_Qty" in qc.columns and total_inspected > 0:
            pass_rate = float((qc["Passed_Qty"].sum() / total_inspected) * 100)
        if "Rejected_Qty" in qc.columns and total_inspected > 0:
            reject_rate = float((qc["Rejected_Qty"].sum() / total_inspected) * 100)
        if "Estimated_Loss_EGP" in qc.columns:
            quality_loss = float(qc["Estimated_Loss_EGP"].sum())

    if not sales.empty and "Returned" in sales.columns:
        return_rate = float((sales["Returned"] == "Yes").mean() * 100)

    # REAL deltas: trailing 12-month window vs previous 12-month window
    inspected_delta = pct_change_sum(qc, "Inspected_Qty", "Inspection_Date") if not qc.empty else None
    pass_delta = (
        pp_change_ratio(qc, "Passed_Qty", "Inspected_Qty", "Inspection_Date")
        if not qc.empty else None
    )
    reject_delta = (
        pp_change_ratio(qc, "Rejected_Qty", "Inspected_Qty", "Inspection_Date")
        if not qc.empty else None
    )
    loss_delta = pct_change_sum(qc, "Estimated_Loss_EGP", "Inspection_Date") if not qc.empty else None
    return_delta = pct_change_count(sales, "Order_Date", mask=sales["Returned"] == "Yes") if not sales.empty else None

    return [
        KPICard(
            title="Units Inspected",
            value=f"{total_inspected:,}",
            raw_value=float(total_inspected),
            delta=round(inspected_delta, 1) if inspected_delta is not None else None,
            delta_label=PERIOD_LABEL,
            neutral_delta=True,
            color="navy",
        ),
        KPICard(
            title="Quality Pass Rate",
            value=f"{pass_rate:.1f}%",
            raw_value=float(pass_rate),
            delta=round(pass_delta, 2) if pass_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            color="teal" if pass_rate >= 95 else "orange",
        ),
        KPICard(
            title="QC Rejection Rate",
            value=f"{reject_rate:.2f}%",
            raw_value=float(reject_rate),
            delta=round(reject_delta, 2) if reject_delta is not None else None,
            delta_label=f"{PERIOD_LABEL} (pp)",
            favorable=False,
            color="danger" if reject_rate > 3.0 else "teal",
        ),
        KPICard(
            title="Cost of Poor Quality (COPQ)",
            value=format_currency_ar(quality_loss),
            raw_value=float(quality_loss),
            delta=round(loss_delta, 1) if loss_delta is not None else None,
            delta_label=PERIOD_LABEL,
            favorable=False,
            color="danger",
        ),
        KPICard(
            title="Customer Return Rate",
            value=f"{return_rate:.2f}%",
            raw_value=float(return_rate),
            delta=round(return_delta, 1) if return_delta is not None else None,
            delta_label=PERIOD_LABEL + " (of invoices)",
            favorable=False,
            color="orange" if return_rate > 5.0 else "teal",
        ),
    ]


@log_function
def get_defect_pareto(data: dict[str, pd.DataFrame]) -> ChartData:
    """Pareto chart: Defect types frequency and cumulative percentage."""
    qc = data.get("Quality", pd.DataFrame())
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if not qc.empty and "Defect_Type" in qc.columns:
        counts = qc["Defect_Type"].dropna().value_counts().reset_index()
        counts.columns = ["Defect", "Count"]
        counts = counts[~counts["Defect"].astype(str).str.lower().isin(["none", "nan", "no defect", "no significant issue"])]

        if not counts.empty:
            counts["Cumulative_Pct"] = (counts["Count"].cumsum() / counts["Count"].sum()) * 100

            fig.add_trace(go.Bar(
                x=counts["Defect"],
                y=counts["Count"],
                name="Defect frequency",
                marker_color=PRIMARY_ORANGE,
                text=counts["Count"],
                textposition="auto"
            ), secondary_y=False)

            fig.add_trace(go.Scatter(
                x=counts["Defect"],
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
        title="Pareto Chart of Top Quality Defects",
        xaxis_title="Defect type",
    )
    fig.update_yaxes(title_text="Defect cases", secondary_y=False)
    fig.update_yaxes(title_text="Cumulative share (%)", range=[0, 105], secondary_y=True)

    return create_chart_data(fig, "defect_pareto", "Quality Defect Pareto Analysis", height=400)


@log_function
def get_root_cause_analysis(data: dict[str, pd.DataFrame]) -> ChartData:
    """Horizontal bar chart: Primary root causes of defects."""
    qc = data.get("Quality", pd.DataFrame())
    fig = go.Figure()

    if not qc.empty and "Root_Cause" in qc.columns:
        causes = qc["Root_Cause"].dropna().value_counts().reset_index()
        causes.columns = ["Root_Cause", "Count"]
        causes = causes[~causes["Root_Cause"].astype(str).str.lower().isin(["none", "nan", "no significant issue"])]
        causes = causes.head(8).sort_values("Count", ascending=True)

        fig.add_trace(go.Bar(
            y=causes["Root_Cause"],
            x=causes["Count"],
            orientation="h",
            text=[f"{v:,} cases" for v in causes["Count"]],
            textposition="auto",
            marker=dict(
                color=SECONDARY_TEAL,
                line=dict(color=DARK_NAVY, width=1)
            )
        ))

    fig.update_layout(
        title="Top Root Causes of Quality Defects",
        xaxis_title="Cases",
        yaxis_title="Root cause",
    )
    return create_chart_data(fig, "root_cause_analysis", "Root Cause Analysis of Quality Defects", height=380)


@log_function
def get_quality_by_stage(data: dict[str, pd.DataFrame]) -> ChartData:
    """Stacked bar: Passed vs Rejected quantities across production inspection stages."""
    qc = data.get("Quality", pd.DataFrame())
    fig = go.Figure()

    if not qc.empty and "Stage" in qc.columns and "Passed_Qty" in qc.columns and "Rejected_Qty" in qc.columns:
        grp = qc.groupby("Stage", observed=False).agg({
            "Passed_Qty": "sum",
            "Rejected_Qty": "sum"
        }).reset_index()

        stage_ar = {
            "Fabric": "Fabric inspection",
            "Cutting": "Cutting stage",
            "Printing": "Printing stage",
            "Sewing": "Sewing stage",
            "Finishing": "Final finishing",
            "Packaging": "Packaging"
        }
        grp["Stage_AR"] = grp["Stage"].map(lambda x: stage_ar.get(str(x), str(x)))

        fig.add_trace(go.Bar(
            x=grp["Stage_AR"],
            y=grp["Passed_Qty"],
            name="Passed units",
            marker_color=SECONDARY_TEAL,
            text=[format_number_ar(v) for v in grp["Passed_Qty"]],
            textposition="inside"
        ))
        fig.add_trace(go.Bar(
            x=grp["Stage_AR"],
            y=grp["Rejected_Qty"],
            name="Rejected units",
            marker_color=ACCENT_RED,
            text=[format_number_ar(v) for v in grp["Rejected_Qty"]],
            textposition="outside"
        ))

    fig.update_layout(
        title="QC Pass vs Rejection by Production Stage",
        xaxis_title="Inspection stage",
        yaxis_title="Units",
        barmode="stack",
    )
    return create_chart_data(fig, "quality_by_stage", "Quality by Production Stage", height=380)


@log_function
def get_quality_loss_trend(data: dict[str, pd.DataFrame]) -> ChartData:
    """Monthly quality loss cost trend in EGP (Cost of Poor Quality)."""
    qc = data.get("Quality", pd.DataFrame()).copy()
    fig = go.Figure()

    if not qc.empty and "Inspection_Date" in qc.columns and "Estimated_Loss_EGP" in qc.columns:
        qc["Inspection_Date"] = pd.to_datetime(qc["Inspection_Date"], errors="coerce")
        qc["Month"] = qc["Inspection_Date"].dt.to_period("M").astype(str)
        qc = qc.dropna(subset=["Month"])

        grp = qc.groupby("Month", observed=False)["Estimated_Loss_EGP"].sum().reset_index().sort_values("Month")

        fig.add_trace(go.Scatter(
            x=grp["Month"],
            y=grp["Estimated_Loss_EGP"],
            mode="lines+markers",
            fill="tozeroy",
            line=dict(color=ACCENT_RED, width=3),
            fillcolor="rgba(239, 68, 68, 0.15)",
            marker=dict(size=6, color=DARK_NAVY),
            name="Quality loss cost (EGP)"
        ))

    fig.update_layout(
        title="Monthly COPQ Trend (EGP)",
        xaxis_title="Month",
        yaxis_title="Estimated losses (EGP)",
    )
    return create_chart_data(fig, "quality_loss_trend", "Monthly Quality Loss Trend", height=380)


@log_function
def get_return_reasons(data: dict[str, pd.DataFrame]) -> ChartData:
    """Donut chart: Return reasons breakdown from sales transactions."""
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not sales.empty and "Returned" in sales.columns and "Return_Reason" in sales.columns:
        ret = sales[sales["Returned"] == "Yes"]
        counts = ret["Return_Reason"].dropna().value_counts().reset_index()
        counts.columns = ["Reason", "Count"]
        counts = counts[~counts["Reason"].astype(str).str.lower().isin(["no return", "nan", "none"])]

        colors = [PRIMARY_ORANGE, SECONDARY_TEAL, DARK_NAVY, LIGHT_ORANGE, LIGHT_TEAL, ACCENT_RED]

        fig.add_trace(go.Pie(
            labels=counts["Reason"],
            values=counts["Count"],
            hole=0.55,
            marker=dict(colors=colors),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>Returns: %{value:,.0f} pieces (%{percent})<extra></extra>"
        ))

    fig.update_layout(
        title="Customer Return Reasons by Outlet & Website",
        showlegend=True
    )
    return create_chart_data(fig, "return_reasons", "Customer Return Reasons", height=380)


@log_function
def get_quality_return_correlation(data: dict[str, pd.DataFrame]) -> ChartData:
    """Scatter: Product QC Reject Rate % vs Customer Return Rate %."""
    qc = data.get("Quality", pd.DataFrame())
    sales = data.get("Sales_Transactions", pd.DataFrame())
    fig = go.Figure()

    if not qc.empty and not sales.empty and "Product_ID" in qc.columns and "Product_ID" in sales.columns:
        qc_prod = qc.groupby("Product_ID", observed=False).agg({
            "Inspected_Qty": "sum",
            "Rejected_Qty": "sum"
        }).reset_index()
        qc_prod["QC_Reject_Rate"] = (qc_prod["Rejected_Qty"] / qc_prod["Inspected_Qty"].replace(0, np.nan)) * 100

        sales_prod = sales.groupby("Product_ID", observed=False).agg({
            "Quantity": "sum",
            "Returned": lambda s: (s == "Yes").sum(),
            "Product_Name": "first"
        }).reset_index()
        sales_prod["Return_Rate"] = (sales_prod["Returned"] / sales_prod["Quantity"].replace(0, np.nan)) * 100

        merged = pd.merge(qc_prod, sales_prod, on="Product_ID").dropna()
        merged = merged[merged["Quantity"] >= 50]

        sizes = np.clip(merged["Quantity"] / 100, 8, 30)

        fig.add_trace(go.Scatter(
            x=merged["QC_Reject_Rate"],
            y=merged["Return_Rate"],
            mode="markers",
            marker=dict(
                size=sizes,
                color=PRIMARY_ORANGE,
                opacity=0.75,
                line=dict(color=DARK_NAVY, width=1.5)
            ),
            text=merged["Product_Name"],
            hovertemplate="<b>%{text}</b><br>QC rejection: %{x:.2f}%<br>Customer returns: %{y:.2f}%<extra></extra>"
        ))

    fig.update_layout(
        title="Internal Inspection Defects vs Customer Returns by Product",
        xaxis_title="Factory QC rejection rate (%)",
        yaxis_title="Customer return rate (%)",
    )
    return create_chart_data(fig, "quality_return_correlation", "Inspection Defects vs Returns Correlation", height=420)
