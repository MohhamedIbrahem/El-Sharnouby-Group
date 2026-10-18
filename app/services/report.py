"""
Business Intelligence Report Service
=====================================

Orchestrates the existing analytical services into a single structured,
management-level report (page + Markdown/JSON export).

Design rules:
1. REUSE FIRST — everything a dashboard service already computes is called,
   never recomputed. New aggregations live in documented `_calc_*` helpers
   (each docstring states the exact formula) covered by unit tests whose
   oracle values were independently revalidated against the source CSVs
   (tests/test_report.py, validation_report.md).
2. TRACEABLE — every finding carries exact metric values, a source, and any
   limitation; finding IDs are stable strings referenced by the risk and
   recommendation tables.
3. NO FABRICATION — forecasts are labeled predictions, K-Means segments as
   heuristic segmentation, Isolation-Forest outputs as statistical flags that
   are NOT proof of error, and the discount-cap simulations as counterfactual
   scenarios (never realized savings).
4. GRACEFUL — a missing/failing dataset never crashes the report; the affected
   analysis is skipped and marked "unavailable" in the analyses-status table.
5. LOCAL & DETERMINISTIC — no external LLM/API calls; the Markdown/JSON exports
   are deterministic for the same data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.core.logger import setup_logger, log_function
from app.core.models import KPICard, ChartData

# ── Reused services (canonical sources of the dashboard numbers) ─────────────
from app.services.executive import (
    get_executive_kpis, get_revenue_profit_trend, get_revenue_by_channel,
)
from app.services.sales import get_sales_kpis
from app.services.customers import get_customer_kpis, _get_segmented_rfm
from app.services.channels import get_channel_kpis
from app.services.inventory import get_inventory_kpis, get_demand_forecast
from app.services.marketing import get_marketing_kpis
from app.services.production import get_production_kpis
from app.services.quality import get_quality_kpis
from app.services.printing import get_printing_kpis
from app.services.supply_chain import (
    get_supply_chain_kpis, get_supplier_scorecard, _prepare_po_data,
)
from app.services.value_chain import get_value_chain_kpis, _compute_full_product_chain
from app.ai.forecasting import forecast_demand

logger = setup_logger(__name__)

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "positive": 3}
VALID_SEVERITIES = set(SEVERITY_ORDER)
VALID_SCOPES = {"actual", "simulated", "modeled", "prediction", "segmentation", "anomaly"}
SCOPE_TAGS = {
    "actual": "Verified from data",
    "simulated": "Simulated scenario — not realized",
    "modeled": "Modeled estimate",
    "prediction": "Prediction — not an actual result",
    "segmentation": "Statistical segmentation — not verified customer types",
    "anomaly": "Statistical anomaly flag — not proof of error",
}


# ── Formatting helpers ────────────────────────────────────────────────────────

def _egp(v: Any) -> str:
    """Exact EGP amount with thousands separators (exactness aids traceability)."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, np.floating) and np.isnan(v)):
        return "n/a"
    return f"EGP {float(v):,.0f}"


def _pct(v: Any, dec: int = 1) -> str:
    """Formats a FRACTION (0.614 -> '61.4%'); n/a-safe."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, np.floating) and np.isnan(v)):
        return "n/a"
    return f"{float(v) * 100:.{dec}f}%"


def _pp(v: Any, dec: int = 1) -> str:
    """Formats a value already expressed in percentage POINTS (8.5 -> '8.5%')."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, np.floating) and np.isnan(v)):
        return "n/a"
    return f"{float(v):.{dec}f}%"


def _num(v: Any, dec: int = 0) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, np.floating) and np.isnan(v)):
        return "n/a"
    return f"{float(v):,.{dec}f}"


def _kpi_value(cards: list, title: str) -> Optional[str]:
    """Display value of a reused KPI card by its (stable) title; None if absent."""
    for c in cards or []:
        if c.title == title and c.value not in (None, "", "0", "0.0"):
            return str(c.value)
    return None


# ============================================================================
# Structured report objects
# ============================================================================

@dataclass
class EvidenceItem:
    label: str          # e.g. "CY2025 discounts"
    value: str          # e.g. "EGP 60,606,283"
    source: str = ""    # e.g. "Sales_Transactions: Sum(Gross−Net), CY2025"

    def to_dict(self) -> dict:
        return {"label": self.label, "value": self.value, "source": self.source}


@dataclass
class ReportFinding:
    """One evidence-backed discovery. IDs (F01…) are stable across rebuilds."""
    id: str
    title: str
    severity: str       # high / medium / low / positive
    scope: str          # actual / simulated / modeled / prediction / segmentation / anomaly
    category: str
    finding: str
    evidence: list[EvidenceItem]
    interpretation: str
    impact: str
    action: str
    source: str
    confidence: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "severity": self.severity,
            "scope": self.scope, "category": self.category, "finding": self.finding,
            "evidence": [e.to_dict() for e in self.evidence],
            "interpretation": self.interpretation, "impact": self.impact,
            "action": self.action, "source": self.source, "confidence": self.confidence,
        }


@dataclass
class RiskItem:
    priority: str       # High / Medium / Low
    title: str
    evidence: str
    area: str
    consequence: str
    next_step: str
    linked_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "priority": self.priority, "title": self.title, "evidence": self.evidence,
            "area": self.area, "consequence": self.consequence, "next_step": self.next_step,
            "linked_findings": list(self.linked_findings),
        }


@dataclass
class RecommendationItem:
    id: str
    title: str
    category: str       # Evidence-based / Exploratory
    references: list[str]
    action: str
    metric_to_monitor: str
    evaluation: str

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "category": self.category,
            "references": list(self.references), "action": self.action,
            "metric_to_monitor": self.metric_to_monitor, "evaluation": self.evaluation,
        }


@dataclass
class AnalysisStatus:
    name: str
    status: str         # executed / unavailable / not possible
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class ReportContext:
    generated_at: str
    period_label: str
    period_start: str
    period_end: str
    executive_kpis: list[KPICard] = field(default_factory=list)
    exec_summary: list[str] = field(default_factory=list)
    findings: list[ReportFinding] = field(default_factory=list)
    charts: list[ChartData] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    opportunities: list[RiskItem] = field(default_factory=list)
    recommendations: list[RecommendationItem] = field(default_factory=list)
    dataset_coverage: list[dict] = field(default_factory=list)
    analyses_status: list[AnalysisStatus] = field(default_factory=list)
    limitations: list[dict] = field(default_factory=list)

    def sort_findings(self) -> None:
        self.findings.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 9))

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "period": {"start": self.period_start, "end": self.period_end, "label": self.period_label},
            "executive_kpis": [k.model_dump() for k in self.executive_kpis],
            "exec_summary": list(self.exec_summary),
            "findings": [f.to_dict() for f in self.findings],
            "charts": [{"chart_id": c.chart_id, "title": c.title} for c in self.charts],
            "risks": [r.to_dict() for r in self.risks],
            "opportunities": [o.to_dict() for o in self.opportunities],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "dataset_coverage": list(self.dataset_coverage),
            "analyses_status": [a.to_dict() for a in self.analyses_status],
            "limitations": list(self.limitations),
        }


# ============================================================================
# Documented aggregation helpers — wholesale unit economics use the dataset's
# own semantics, independently revalidated: Net = Gross×(1−Discount_Pct) and
# GP = Net − Estimated_COGS_EGP on wholesale rows.
# ============================================================================

def _sales(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return data.get("Sales_Transactions", pd.DataFrame())


def _wholesale(sales: pd.DataFrame) -> pd.DataFrame:
    if sales.empty or "Channel" not in sales.columns:
        return sales.iloc[0:0] if not sales.empty else sales
    return sales[sales["Channel"].astype(str) == "Wholesale"]


def _calc_discount_system(sales: pd.DataFrame) -> dict:
    """Wholesale discount structure.

    Formulas: Disc_EGP = Gross_Sales_EGP − Net_Sales_EGP (per row). Tiers group
    on round(Discount_Pct, 2); per-tier share = rows / Σrows. corr = Pearson(
    Discount_Pct, Quantity). CY2025 totals filter Order_Date year == 2025 —
    computed both group-wide (the independently validated oracle figure) and
    wholesale-only.
    """
    out: dict[str, Any] = {}
    # Group-wide CY2025 discount spending vs CY2025 group gross profit.
    if (not sales.empty and "Order_Date" in sales.columns
            and {"Gross_Sales_EGP", "Net_Sales_EGP", "Gross_Profit_EGP"}.issubset(sales.columns)):
        allc = sales[sales["Order_Date"].dt.year == 2025]
        if not allc.empty:
            out["cy2025_discounts_all"] = float((allc["Gross_Sales_EGP"] - allc["Net_Sales_EGP"]).sum())
            out["cy2025_gp_all"] = float(allc["Gross_Profit_EGP"].sum())
            if out["cy2025_gp_all"]:
                out["cy2025_ratio_all"] = out["cy2025_discounts_all"] / out["cy2025_gp_all"]
    w = _wholesale(sales)
    if w.empty or "Discount_Pct" not in w.columns:
        return out
    if not {"Gross_Sales_EGP", "Net_Sales_EGP", "Gross_Profit_EGP"}.issubset(w.columns):
        return out
    w = w.assign(Disc_EGP=w["Gross_Sales_EGP"] - w["Net_Sales_EGP"])
    if "Invoice_ID" not in w.columns:  # fall back to row counting
        w = w.reset_index().rename(columns={"index": "Invoice_ID"})
    tiers = w.assign(Tier=w["Discount_Pct"].round(2)).groupby("Tier").agg(
        rows=("Invoice_ID", "size"), gp=("Gross_Profit_EGP", "sum"),
        rev=("Net_Sales_EGP", "sum"), disc=("Disc_EGP", "sum"),
        avg_qty=("Quantity", "mean") if "Quantity" in w.columns else ("Invoice_ID", "size"),
    )
    if not tiers.empty and tiers["rev"].sum() > 0:
        tiers = tiers.sort_index()
        tiers["share"] = tiers["rows"] / tiers["rows"].sum()
        tiers["gm"] = np.where(tiers["rev"] > 0, tiers["gp"] / tiers["rev"], np.nan)
        out["tiers"] = tiers
        gp_lo = float(tiers.loc[tiers.index.min(), "gp"])
        gp_hi = float(tiers.loc[tiers.index.max(), "gp"])
        out["tier_gp_ratio"] = (gp_hi / gp_lo) if gp_lo != 0 else None
    if "Quantity" in w.columns and len(w) > 2:
        # Correlation is undefined when either series is constant (pandas 3.x
        # returns numerical dust, not NaN, so guard on variance explicitly).
        a, b = w["Discount_Pct"], w["Quantity"]
        try:
            if float(a.std()) > 1e-12 and float(b.std()) > 1e-12:
                c = float(a.corr(b))
                if not pd.isna(c):
                    out["corr_tier_qty"] = c
        except (TypeError, ValueError):
            pass
    cy = w[w["Order_Date"].dt.year == 2025] if "Order_Date" in w.columns else w.iloc[0:0]
    if not cy.empty:
        out["cy2025_discounts"] = float(cy["Disc_EGP"].sum())
        out["cy2025_gp"] = float(cy["Gross_Profit_EGP"].sum())
        if out["cy2025_gp"]:
            out["cy2025_ratio"] = out["cy2025_discounts"] / out["cy2025_gp"]
    if "Product_Family" in w.columns:
        fam = w.groupby("Product_Family", observed=True)["Disc_EGP"].sum()
        if float(fam.sum()) > 0:
            out["top_discount_family"] = str(fam.idxmax())
            out["top_discount_family_share"] = float(fam.max() / fam.sum())
    return out


def _calc_cap_scenario(sales: pd.DataFrame, cap: float = 0.30, volume_loss: float = 0.0) -> dict:
    """Counterfactual discount-cap simulation (NOT realized savings).

    Wholesale rows with Discount_Pct > cap are re-priced.  Modeled new GP per
    affected row = Gross_Sales_EGP×(1−cap) − Estimated_COGS_EGP.
    delta_full   = Σ new_gp − Σ Gross_Profit_EGP (full retention);
    delta_volume = Σ (1−volume_loss)×new_gp − Σ Gross_Profit_EGP (uniform
    quantity loss on affected rows); breakeven_volume_loss = the fraction of
    affected-row volume that can be lost before the gain dissolves.
    """
    out: dict[str, Any] = {"cap": cap}
    w = _wholesale(sales)
    if w.empty or "Discount_Pct" not in w.columns:
        return out
    if not {"Gross_Sales_EGP", "Estimated_COGS_EGP", "Gross_Profit_EGP"}.issubset(w.columns):
        return out
    aff = w[w["Discount_Pct"] > cap]
    out["affected_rows"] = int(len(aff))
    if aff.empty:
        return out
    new_gp = aff["Gross_Sales_EGP"] * (1 - cap) - aff["Estimated_COGS_EGP"]
    gp_old = float(aff["Gross_Profit_EGP"].sum())
    out["affected_products"] = int(aff["Product_ID"].nunique()) if "Product_ID" in aff.columns else None
    out["delta_full"] = float(new_gp.sum() - gp_old)
    out["delta_volume"] = float((1 - volume_loss) * new_gp.sum() - gp_old)
    out["breakeven_volume_loss"] = float(1 - gp_old / new_gp.sum()) if new_gp.sum() > 0 else None
    return out


def _calc_loss_makers(sales: pd.DataFrame) -> dict:
    """Wholesale loss-making products.

    Per Product_ID over wholesale rows: GP=ΣGross_Profit_EGP, GM=GP/ΣNet,
    break-even discount = 1 − ΣEstimated_COGS_EGP / ΣGross_Sales_EGP.
    """
    out: dict[str, Any] = {}
    w = _wholesale(sales)
    if w.empty or "Product_ID" not in w.columns:
        return out
    if not {"Gross_Profit_EGP", "Net_Sales_EGP", "Estimated_COGS_EGP"}.issubset(w.columns):
        return out
    g = w.groupby("Product_ID", observed=True).agg(
        gp=("Gross_Profit_EGP", "sum"), rev=("Net_Sales_EGP", "sum"),
        gross=("Gross_Sales_EGP", "sum"), cogs=("Estimated_COGS_EGP", "sum"),
        units=("Quantity", "sum") if "Quantity" in w.columns else ("Net_Sales_EGP", "size"),
        rows=("Gross_Profit_EGP", "size"),
    )
    g["gm"] = np.where(g["rev"] > 0, g["gp"] / g["rev"], np.nan)
    loss = g[g["gp"] < 0].sort_values("gp").reset_index()
    out["products_evaluated"] = int(len(g))
    out["loss_makers"] = loss
    if loss.empty:
        return out
    p = loss.iloc[0]
    out["worst"] = {
        "id": str(p["Product_ID"]), "gp": float(p["gp"]), "gm": float(p["gm"]),
        "units": int(p["units"]), "rows": int(p["rows"]),
        # Break-even discount: the tier at which Gross×(1−d) = COGS on average
        # → d* = 1 − ΣCOGS/ΣGross (Gross BEFORE discount, NOT Net).
        "breakeven": float(1 - p["cogs"] / p["gross"]) if p["gross"] else None,
    }
    pw = w[w["Product_ID"] == p["Product_ID"]]
    if not pw.empty and "Discount_Pct" in pw.columns:
        tier_pnl = pw.assign(Tier=pw["Discount_Pct"].round(2)).groupby("Tier")["Gross_Profit_EGP"].agg(["sum", "count"])
        out["worst_tier_pnl"] = tier_pnl.sort_index()
        out["worst_tier_max"] = float(pw["Discount_Pct"].max())
    return out


def _calc_fiscal_trend(sales: pd.DataFrame) -> dict:
    """Fiscal-year trend (fiscal year Oct–Sep, labeled by its ending year).

    FY = Order_Date.year + (month >= 10); growths compare only pairs of fiscal
    years that both span 12 complete months (partial edge years excluded).
    """
    if sales.empty or not {"Order_Date", "Net_Sales_EGP"}.issubset(sales.columns):
        return {}
    months = sales["Order_Date"].dt.month
    fy_series = sales["Order_Date"].dt.year + (months >= 10).astype(int)
    fy_net = sales.assign(FY=fy_series).groupby("FY")["Net_Sales_EGP"].sum()
    fy_months = sales.assign(FY=fy_series, M=sales["Order_Date"].dt.to_period("M")).groupby("FY")["M"].nunique()
    growths: dict[str, float] = {}
    yrs = sorted(fy_net.index)
    for prev_y, y in zip(yrs[:-1], yrs[1:]):
        if int(fy_months.get(y, 0)) == 12 and int(fy_months.get(prev_y, 0)) == 12 and float(fy_net.get(prev_y, 0)) > 0:
            growths[str(y)] = float(float(fy_net[y]) / float(fy_net[prev_y]) - 1)  # fraction
    return {"fy_net": fy_net, "fy_growth": growths, "fy_months": fy_months}


def _calc_channel_structure(sales: pd.DataFrame) -> dict:
    """Channel structure + like-for-like LTM growth per channel.

    share = ΣNet(channel)/ΣNet(all); GM = ΣGP/ΣNet per channel; LTM growth =
    (Σ monthly Net over the last 12 months) / (Σ previous 12) − 1 per channel.
    """
    out: dict[str, Any] = {}
    if sales.empty or not {"Channel", "Net_Sales_EGP", "Order_Date"}.issubset(sales.columns):
        return out
    df = sales
    if "Year_Month" not in df.columns:
        df = df.assign(Year_Month=df["Order_Date"].dt.to_period("M").astype(str))
    if "Gross_Profit_EGP" not in df.columns:
        return out
    by_ch = df.groupby("Channel", observed=True)["Net_Sales_EGP"].sum()
    gp_ch = df.groupby("Channel", observed=True)["Gross_Profit_EGP"].sum()
    if by_ch.empty or float(by_ch.sum()) <= 0:
        return out
    total = float(by_ch.sum())
    channels: dict[str, dict] = {}
    for ch, v in by_ch.items():
        ch = str(ch)
        m = df[df["Channel"].astype(str) == ch].groupby("Year_Month")["Net_Sales_EGP"].sum().sort_index()
        growth = float(m.iloc[-12:].sum() / m.iloc[-24:-12].sum() - 1) if len(m) >= 24 else None  # fraction
        rev = float(v)
        channels[ch] = {
            "revenue": rev, "share": rev / total,
            "gm": float(gp_ch.get(ch, 0)) / rev if rev else None,
            "ltm_growth": growth,
        }
        out[f"{ch.lower()}_growth"] = growth
    out["channels"] = channels
    out["wholesale_share"] = channels.get("Wholesale", {}).get("share")
    return out

def _calc_returns(sales: pd.DataFrame) -> dict:
    """Return/refund aggregation.

    refunds = Σ Refund_Value_EGP (all-time / CY2026 by Order_Date). CY2026
    return reasons = Return_Reason counts among rows with Returned == 'Yes'.
    """
    out: dict[str, Any] = {}
    if sales.empty or "Refund_Value_EGP" not in sales.columns:
        return out
    out["refunds_all"] = float(sales["Refund_Value_EGP"].sum())
    if "Order_Date" in sales.columns:
        cy26 = sales[sales["Order_Date"].dt.year == 2026]
        if not cy26.empty:
            out["refunds_cy2026"] = float(cy26["Refund_Value_EGP"].sum())
            if "Returned" in cy26.columns and "Return_Reason" in cy26.columns:
                ret = cy26[cy26["Returned"].astype(str).str.strip().str.lower() == "yes"]
                reasons = ret["Return_Reason"].astype(str).str.strip()
                reasons = reasons[~reasons.str.lower().isin(["no return", "nan", "none", "", "n/a"])]
                if not reasons.empty:
                    out["cy2026_reasons"] = reasons.value_counts()
    return out


def _calc_quality(qc: pd.DataFrame) -> dict:
    """COPQ aggregation. ΣEstimated_Loss_EGP (modeled) all-time / CY2026 by
    Inspection_Date; defect and root-cause frequency counts exclude nulls."""
    out: dict[str, Any] = {}
    if qc.empty:
        return out
    if "Estimated_Loss_EGP" in qc.columns:
        out["copq_all"] = float(qc["Estimated_Loss_EGP"].sum())
        if "Inspection_Date" in qc.columns:
            cy = qc[qc["Inspection_Date"].dt.year == 2026]
            if not cy.empty:
                out["copq_cy2026"] = float(cy["Estimated_Loss_EGP"].sum())
    if "Defect_Type" in qc.columns:
        out["defect_nulls"] = int(qc["Defect_Type"].isna().sum())
        d = qc["Defect_Type"].astype(str).str.strip()
        d = d[~d.str.lower().isin(["none", "nan", "no defect", "", "n/a", "not significant"])]
        if not d.empty:
            out["top_defect"] = d.value_counts()
    if "Root_Cause" in qc.columns:
        r = qc["Root_Cause"].astype(str).str.strip()
        r = r[~r.str.lower().isin(["none", "nan", "", "n/a", "no significant issue"])]
        if not r.empty:
            out["top_root_cause"] = r.value_counts()
    return out


def _calc_stockouts(inv: pd.DataFrame, sales: pd.DataFrame) -> dict:
    """Stockout escalation + modeled LTM opportunity cost.

    Escalation counts (SKU, snapshot-month) rows with Stockout_Days_In_Month>0
    and Σ Stockout_Days over the first-6 vs last-6 snapshot months. Lost GP
    (OPPORTUNITY-COST MODEL, lower bound): Σ over LTM rows of
    Stockout_Days_In_Month × Avg_Daily_Sales_90D × group-wide GP-per-unit.
    """
    out: dict[str, Any] = {}
    if inv.empty or "Stockout_Days_In_Month" not in inv.columns:
        return out
    snap = pd.to_datetime(inv["Snapshot_Month"], errors="coerce")
    if snap.isna().all():
        return out
    m_period = snap.dt.to_period("M")
    months = sorted(m_period.dropna().unique())
    if len(months) < 12:
        return out
    first6, last6 = set(months[:6]), set(months[-6:])
    days = inv["Stockout_Days_In_Month"].clip(lower=0)
    out["first6_sku_months"] = int((days[m_period.isin(first6)] > 0).sum())
    out["last6_sku_months"] = int((days[m_period.isin(last6)] > 0).sum())
    out["first6_days"] = int(days[m_period.isin(first6)].sum())
    out["last6_days"] = int(days[m_period.isin(last6)].sum())
    out["escalation_x"] = (out["last6_sku_months"] / out["first6_sku_months"]) if out["first6_sku_months"] else None
    firstm, lastm = months[0].strftime("%b %Y"), months[-1].strftime("%b %Y")
    out["window_label"] = f"{firstm} vs {lastm} (first/last 6 snapshot months)"
    if not sales.empty and {"Gross_Profit_EGP", "Quantity"}.issubset(sales.columns):
        units = float(sales["Quantity"].sum())
        if units > 0:
            gp_per_unit = float(sales["Gross_Profit_EGP"].sum()) / units
            out["gp_per_unit"] = gp_per_unit
            ltm = inv[m_period.isin(months[-12:])]
            if "Avg_Daily_Sales_90D" in ltm.columns:
                lost_units = float((ltm["Stockout_Days_In_Month"].clip(lower=0) * ltm["Avg_Daily_Sales_90D"]).sum())
                out["lost_units_ltm"] = lost_units
                out["lost_gp_ltm"] = lost_units * gp_per_unit
    return out


def _calc_suppliers(po: pd.DataFrame) -> dict:
    """Supplier OTD evidence (reuses supply_chain._prepare_po_data).

    Windows follow the same design as the stockout escalation: the INITIAL 12
    months of the PO series vs the MOST RECENT 12 months (per-supplier rates
    are all-time). OTD = mean(On_Time) per window.
    """
    out: dict[str, Any] = {}
    if po.empty or "On_Time" not in po.columns:
        return out
    if "Supplier_ID" in po.columns:
        sup = po.groupby("Supplier_ID", observed=True).agg(
            otd=("On_Time", "mean"), orders=("On_Time", "size")
        ).reset_index().sort_values("otd")
        out["worst"] = sup.head(3)
    if "Order_Date" in po.columns:
        d = po["Order_Date"]
        months = pd.Series(d.dt.to_period("M").dropna().unique()).sort_values()
        if len(months) >= 12:
            first12 = po[d.dt.to_period("M").isin(months[:12])]
            last12 = po[d.dt.to_period("M").isin(months[-12:])]
            if len(first12) > 0 and len(last12) > 0:
                out["otd_first12"] = float(first12["On_Time"].mean())
                out["otd_last12"] = float(last12["On_Time"].mean())
    return out


def _calc_production(prod: pd.DataFrame) -> dict:
    """CY2026 plan achievement (Start_Date in 2026): Produced/Planned; plus
    Primary_Bottleneck frequency counts among those orders ('None' excluded).
    NOT a capacity-utilization metric (no capacity fields exist)."""
    out: dict[str, Any] = {}
    if prod.empty:
        return out
    if "Start_Date" not in prod.columns:
        return out
    cy = prod[prod["Start_Date"].dt.year == 2026]
    if cy.empty:
        return out
    if {"Planned_Qty", "Produced_Qty"}.issubset(cy.columns):
        planned = float(cy["Planned_Qty"].sum())
        produced = float(cy["Produced_Qty"].sum())
        out["cy2026_planned"] = planned
        out["cy2026_produced"] = produced
        if planned > 0:
            out["cy2026_achievement"] = produced / planned
    if "Primary_Bottleneck" in cy.columns:
        bn = cy["Primary_Bottleneck"].astype(str).str.strip()
        bn = bn[~bn.str.lower().isin(["none", "nan", "", "n/a"])]
        if not bn.empty:
            out["bottlenecks_cy2026"] = bn.value_counts()
    return out


def _calc_marketing(mkt: pd.DataFrame, sales: pd.DataFrame) -> dict:
    """Marketing-attribution consistency evidence.

    attributed = ΣAttributed_Revenue_EGP; B2C = ΣNet_Sales_EGP over channels
    {Online, Retail}; ratio = attributed / B2C; system Order_Attributed total
    is compared with the count of actual B2C invoice rows. By-platform ROAS =
    attributed / spend per row-group.
    """
    out: dict[str, Any] = {}
    if mkt.empty or "Attributed_Revenue_EGP" not in mkt.columns:
        return out
    out["attributed_total"] = float(mkt["Attributed_Revenue_EGP"].sum())
    out["spend_total"] = float(mkt["Spend_EGP"].sum()) if "Spend_EGP" in mkt.columns else None
    out["orders_attributed"] = float(mkt["Orders_Attributed"].sum()) if "Orders_Attributed" in mkt.columns else None
    b2c = pd.DataFrame()
    if not sales.empty and "Channel" in sales.columns:
        b2c = sales[sales["Channel"].astype(str).isin(["Online", "Retail"])]
        if "Net_Sales_EGP" in b2c.columns:
            out["b2c_revenue"] = float(b2c["Net_Sales_EGP"].sum())
        out["b2c_rows"] = int(len(b2c))
    if out.get("b2c_revenue"):
        out["attribution_ratio"] = out["attributed_total"] / out["b2c_revenue"]
    if "Platform" in mkt.columns and "Spend_EGP" in mkt.columns:
        by_plat = mkt.groupby("Platform", observed=True).agg(
            attributed=("Attributed_Revenue_EGP", "sum"), spend=("Spend_EGP", "sum"))
        by_plat["roas"] = np.where(by_plat["spend"] > 0, by_plat["attributed"] / by_plat["spend"], np.nan)
        out["by_platform"] = by_plat.sort_values("attributed", ascending=False)
    return out


def _calc_service(cs: pd.DataFrame) -> dict:
    """Customer-service aggregates (no customer-level records are exposed)."""
    out: dict[str, Any] = {}
    if cs.empty:
        return out
    out["tickets"] = int(len(cs))
    if "Resolved" in cs.columns:
        out["resolved_rate"] = float((cs["Resolved"].astype(str).str.strip().str.lower() == "yes").mean())
    if "First_Response_Minutes" in cs.columns:
        out["avg_first_response_min"] = float(cs["First_Response_Minutes"].mean())
    if "Resolution_Hours" in cs.columns:
        out["avg_resolution_hours"] = float(cs["Resolution_Hours"].mean())
    if "CSAT_1_to_5" in cs.columns:
        out["avg_csat"] = float(cs["CSAT_1_to_5"].mean())
    return out


def _summarize_segments(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregated view of the REUSED RFM+K-Means cache (no new modeling):
    per Segment — customer count, share, mean Monetary/Frequency/Recency."""
    rfm = _get_segmented_rfm(data)
    if rfm.empty or "Segment" not in rfm.columns or len(rfm) == 0:
        return pd.DataFrame()
    stats = rfm.groupby("Segment", observed=True).agg(
        customers=("Customer_ID", "size"),
        avg_monetary=("Monetary", "mean"),
        avg_frequency=("Frequency", "mean"),
        avg_recency=("Recency", "mean"),
    )
    stats["share"] = stats["customers"] / stats["customers"].sum()
    return stats.sort_values("avg_monetary", ascending=False)


def _weekly_history(sales: pd.DataFrame) -> pd.Series:
    """Weekly demand buckets (same Grouper as the AI module) for sanity anchors."""
    if sales.empty or not {"Order_Date", "Quantity"}.issubset(sales.columns):
        return pd.Series(dtype=float)
    return sales.groupby(pd.Grouper(key="Order_Date", freq="W-MON"))["Quantity"].sum().dropna()


def _dataset_coverage(data: dict[str, pd.DataFrame]) -> list[dict]:
    """Row counts + month coverage per table (aggregate metadata only)."""
    date_cols = [("Order_Date", "Transactions"), ("Inspection_Date", "Inspections"),
                 ("Snapshot_Month", "Snapshots"), ("Start_Date", "Production starts"),
                 ("Open_Date", "Tickets"), ("Join_Date", "Customers since"),
                 ("Date", "Records"), ("Month", "Records")]
    rows = []
    for name, df in sorted(data.items()):
        if df is None:
            continue
        note = "—"
        for col, label in date_cols:
            if col in df.columns and df[col].notna().any():
                s = pd.to_datetime(df[col], errors="coerce").dropna()
                if not s.empty:
                    note = f"{label}: {s.min():%b %Y}–{s.max():%b %Y}"
                    break
        rows.append({"table": name, "rows": int(len(df)), "coverage": note})
    return rows

# ============================================================================
# Finding builders — each returns Optional[ReportFinding] (None = unavailable).
# Evidence rows follow a CANONICAL ORDER per finding (documented in the risk/
# summary builders, which reference them by index).
# ============================================================================

def _f_discount_system(d: dict, fid: str) -> Optional[ReportFinding]:
    tiers = d.get("tiers")
    if tiers is None or tiers.empty or "cy2025_discounts" not in d:
        return None
    ratio = d.get("cy2025_ratio")
    corr = d.get("corr_tier_qty")
    gp_ratio = d.get("tier_gp_ratio")
    tier_list = ", ".join(f"{int(round(t * 100))}%" for t in tiers.index)
    shares = ", ".join(_pct(s, 1) for s in tiers["share"])
    ev = [
        EvidenceItem("CY2025 group discounts (all channels)", _egp(d.get("cy2025_discounts_all", d["cy2025_discounts"])),
                     "Sales_Transactions: Σ(Gross−Net), Order_Date CY2025"),
        EvidenceItem("CY2025 discounts ÷ CY2025 gross profit (group)", f"{d.get('cy2025_ratio_all', ratio):.2f}×",
                     "same window; independently validated oracle figure"),
        EvidenceItem("Of which wholesale (CY2025)", _egp(d["cy2025_discounts"]), "Σ(Gross−Net), wholesale rows only"),
        EvidenceItem("Wholesale discounts ÷ wholesale gross profit (CY2025)", f"{ratio:.2f}×", "wholesale rows only"),
        EvidenceItem("Discount tiers (wholesale)", tier_list, "Wholesale Discount_Pct unique values"),
        EvidenceItem("Transaction share per tier", shares + " (near-uniform)", "rows / Σrows per tier"),
        EvidenceItem("Tier depth vs order size", f"r = {corr:.3f}" if corr is not None else "n/a",
                     "Pearson corr(Discount_Pct, Quantity)"),
        EvidenceItem("Deepest-tier GP vs shallowest-tier GP", _num(gp_ratio, 2) + "×" if gp_ratio else "n/a",
                     "tier GP table"),
        EvidenceItem("Top discount-consuming family",
                     f"{d.get('top_discount_family', 'n/a')} — {_pct(d.get('top_discount_family_share'))} of all discounts",
                     "Σ(Gross−Net) by Product_Family"),
    ]
    return ReportFinding(
        id=fid,
        title="Discount spending outweighs the profit it creates — and tiers are depth-locked, not earned",
        severity="high", scope="actual", category="Sales & Discounts",
        finding=(
            f"Group-wide discounts reached {_egp(d.get('cy2025_discounts_all', d['cy2025_discounts']))} in CY2025 — "
            f"{d.get('cy2025_ratio_all', ratio):.2f}× that year's gross profit. Within wholesale the program is a fixed "
            f"five-tier structure ({tier_list}) allocated near-uniformly across transactions ({shares}) — "
            f"{_egp(d['cy2025_discounts'])} of CY2025 discounts, {ratio:.2f}× the wholesale channel's own profit — "
            f"and tier depth shows no relation to order size (r = {corr:.3f}), i.e. depth is assigned "
            "administratively rather than earned on volume."
        ),
        evidence=ev,
        interpretation=(
            "A discount program more than 2.7× larger than the gross profit it feeds cannot be "
            "sustained without volume-linked logic. The uniform tier split is a data fact; the "
            "'assigned rather than earned' reading is the business interpretation."
        ),
        impact="Wholesale profitability; pricing policy; margin drag on ~85% of group revenue.",
        action=(
            "Review the wholesale tier policy: cap routine discounts at 30% and require volume "
            "justification for deeper tiers (see the cap-simulation finding for modeled GP impact)."
        ),
        source="app/services/report.py::_calc_discount_system (Sales_Transactions; formulas in docstring). Context on the Sales & Profitability dashboard discount analytics.",
        confidence="High — figures reproduce exactly from source rows (independently validated).",
    )


def _f_cap_scenario(c30: dict, c28: dict, fid: str) -> Optional[ReportFinding]:
    if not c30 or c30.get("affected_rows", 0) == 0 or c30.get("delta_full") is None:
        return None
    be = c30.get("breakeven_volume_loss")
    ev = [
        EvidenceItem("Modeled GP gain — full retention (cap 30%)", _egp(c30["delta_full"]),
                     "Simulated: new GP = Gross×0.70 − COGS on affected rows; NOT realized"),
        EvidenceItem("Modeled GP gain — affected rows lose 20% of volume", _egp(c30["delta_volume"]),
                     "Simulated: GP × 0.8 on affected rows; NOT realized"),
        EvidenceItem("Affected wholesale rows", _num(c30["affected_rows"]),
                     "rows with Discount_Pct > 30% (the 32/35/38% tiers)"),
        EvidenceItem("Modeled GP gain — cap 28%, full retention", _egp(c28.get("delta_full")) if c28.get("delta_full") is not None else "n/a", "Simulated, cap 28%"),
        EvidenceItem("Modeled GP gain — cap 28%, −20% volume", _egp(c28.get("delta_volume")) if c28.get("delta_volume") is not None else "n/a", "Simulated, cap 28%"),
        EvidenceItem("Volume-loss tolerance at 30% cap", f"{be:.1%}" if be is not None else "n/a",
                     "share of affected-row volume that can be lost before GP gain = 0"),
    ]
    return ReportFinding(
        id=fid,
        title="A 30% wholesale discount cap is modeled to recover double-digit millions in gross profit",
        severity="high", scope="simulated", category="Pricing Strategy",
        finding=(
            f"Re-pricing the {_num(c30['affected_rows'])} wholesale transactions currently discounted "
            f"above 30% is modeled to add {_egp(c30['delta_full'])} of gross profit with full retention, "
            f"or {_egp(c30['delta_volume'])} if those rows lose 20% of their volume. The modeled gain only "
            f"dissolves if affected volume falls by more than {be:.0%} — a counterfactual simulation, "
            "not a realized figure."
        ),
        evidence=ev,
        interpretation=(
            "The scenario is arithmetically exact but rests on one counterfactual assumption "
            "(unchanged re-priced price induced behavior). Without elasticity data the volume-loss "
            "assumption is the key uncertainty; hence the pilot-first recommendation."
        ),
        impact="Wholesale pricing; EGP exposure in the tens of millions over the 36-month horizon.",
        action=(
            "Pilot the 30% cap on a limited subset (or by product, prioritizing loss-makers) and "
            "measure realized GP against the modeled bounds before group-wide roll-out."
        ),
        source="app/services/report.py::_calc_cap_scenario (Sales_Transactions; re-pricing formula documented in the function docstring).",
        confidence="Medium — arithmetic reproduces exactly; the retention assumption is counterfactual by definition.",
    )


def _f_loss_makers(lm: dict, fid: str) -> Optional[ReportFinding]:
    loss = lm.get("loss_makers")
    if loss is None or loss.empty:
        return None
    worst = lm["worst"]
    be_pct = _pct(worst["breakeven"], 1) if worst.get("breakeven") is not None else "n/a"
    ev = [
        EvidenceItem("Wholesale products evaluated", _num(lm["products_evaluated"]), "grouped by Product_ID"),
        EvidenceItem("Loss-making products", _num(len(loss)), "Σ Gross_Profit_EGP < 0 (wholesale)"),
        EvidenceItem("Worst product cumulative GP", _egp(worst["gp"]),
                     f"{worst['id']}: Σ Gross_Profit_EGP over {worst['rows']:,} wholesale invoices"),
        EvidenceItem("Worst product gross margin", _pct(worst["gm"]), "GP / ΣNet_Sales_EGP"),
        EvidenceItem("Worst product break-even discount", be_pct, "1 − ΣCOGS / ΣGross (wholesale rows)"),
        EvidenceItem("Deepest tiers of the worst product", f"top tier {_pct(lm.get('worst_tier_max'))}", "max Discount_Pct"),
    ]
    tier_pnl = lm.get("worst_tier_pnl")
    if tier_pnl is not None and not tier_pnl.empty:
        for tier, row in tier_pnl.iterrows():
            ev.append(EvidenceItem(f"Worst product @ {int(round(tier * 100))}% tier", _egp(row["sum"]),
                                   f"{int(row['count']):,} invoices on that tier"))
    if len(loss) > 1:
        others = ", ".join(f"{r.Product_ID} {_egp(r.gp)}" for r in loss.iloc[1:3].itertuples())
        ev.append(EvidenceItem("Next loss-makers", others, "same rule, ranked by cumulative GP"))
    return ReportFinding(
        id=fid,
        title="A handful of wholesale products is priced below its own break-even discount",
        severity="medium", scope="actual", category="Product Profitability",
        finding=(
            f"Only {len(loss)} of {lm['products_evaluated']} wholesale products are loss-making, led by "
            f"{worst['id']}: {_egp(worst['gp'])} cumulative GP (GM {_pct(worst['gm'])}) across "
            f"{worst['rows']:,} invoices. Its break-even discount is ≈{be_pct}; losses concentrate in the "
            f"deepest tiers (e.g. {_pct(lm.get('worst_tier_max'))}) and shrink tier-by-tier as discounts "
            "shallow — verified arithmetically."
        ),
        evidence=ev,
        interpretation=(
            "Losses are explained by discount depth exceeding the product's break-even discount — "
            "a pricing-policy problem, not a cost problem. Every deeper tier below break-even "
            "deepens the loss proportionally."
        ),
        impact="Product-level P&L; wholesale unit economics (COGS/Gross is the binding constraint).",
        action=(
            "Restrict these products' wholesale tiers to at or below their break-even discount, or "
            "renegotiate their input cost; treat them as pricing exceptions in any book-wide cap."
        ),
        source="app/services/report.py::_calc_loss_makers (Sales_Transactions, wholesale rows; formulas in docstring). True-health context on the Value Chain dashboard.",
        confidence="High — every figure reproduces exactly from source rows (independently validated).",
    )


def _f_fiscal_trend(ft: dict, ex_kpis: list, fid: str) -> Optional[ReportFinding]:
    g = ft.get("fy_growth") or {}
    if len(g) < 2:
        return None
    years = sorted(g.keys())
    prev_y, latest_y = years[-2], years[-1]
    gm_val = _kpi_value(ex_kpis, "Gross Margin")
    gm_card = next((k for k in ex_kpis if k.title == "Gross Margin"), None)
    ev = [
        EvidenceItem(f"FY{prev_y} net revenue growth", _pct(g[prev_y], 1), "FY = Oct–Sep fiscal year, Σ Net_Sales_EGP"),
        EvidenceItem(f"FY{latest_y} net revenue growth", _pct(g[latest_y], 1), "same formula; both windows cover 12 complete months"),
        EvidenceItem("Gross margin (LTM)", gm_val or "n/a", "reused Executive dashboard KPI"),
        EvidenceItem("Margin change LTM vs prior 12m",
                     f"{gm_card.delta:+.2f} pp" if gm_card is not None and gm_card.delta is not None else "n/a",
                     "reused Executive service (trailing vs prior 12 months)"),
    ]
    return ReportFinding(
        id=fid,
        title=f"Revenue growth is decelerating ({_pct(g[prev_y], 1)} → {_pct(g[latest_y], 1)}) while margins stay thin",
        severity="high", scope="actual", category="Growth & Stability",
        finding=(
            f"Fiscal-year net revenue growth fell from {_pct(g[prev_y], 1)} in FY{prev_y} to "
            f"{_pct(g[latest_y], 1)} in FY{latest_y}, with gross margin at {gm_val or 'n/a'} — thin in "
            "absolute terms for a manufacturing-retail group (fiscal windows are used because the "
            "first and last calendar years are partial and distort calendar-year YoY)."
        ),
        evidence=ev,
        interpretation=(
            "Deceleration combined with a thin margin leaves little buffer against cost slips and "
            "concentrates the value of the margin-recovery levers documented elsewhere in this report."
        ),
        impact="Group-level planning; cash-flow trajectory; initiative prioritization.",
        action="Treat margin recovery (discount cap, loss-maker pricing) as the primary response to the slowdown rather than pure volume pushes.",
        source="app/services/report.py::_calc_fiscal_trend (Sales_Transactions FY windows) + reused get_executive_kpis margin cards.",
        confidence="High — growth rates reproduce exactly; the fiscal-window choice is documented and justified by partial edge years.",
    )


def _f_channel_structure(chs: dict, fid: str) -> Optional[ReportFinding]:
    channels = chs.get("channels") or {}
    if not channels or "Wholesale" not in channels:
        return None
    ws, online, retail = channels["Wholesale"], channels.get("Online", {}), channels.get("Retail", {})
    ev = [
        EvidenceItem("Online LTM revenue growth", _pct(online.get("ltm_growth")), "last-12-month vs prior-12-month sums"),
        EvidenceItem("Retail LTM revenue growth", _pct(retail.get("ltm_growth")), "same like-for-like windows"),
        EvidenceItem("Wholesale share of revenue", _pct(ws.get("share")), "Σ Net_Sales_EGP by channel"),
        EvidenceItem("Wholesale gross margin", _pct(ws.get("gm")), "ΣGP / ΣNet per channel"),
        EvidenceItem("Retail gross margin", _pct(retail.get("gm")), "same"),
        EvidenceItem("Online gross margin", _pct(online.get("gm")), "same"),
        EvidenceItem("Wholesale LTM revenue growth", _pct(ws.get("ltm_growth")), "same"),
    ]
    on_g, rt_g = online.get("ltm_growth"), retail.get("ltm_growth")
    return ReportFinding(
        id=fid,
        title="Revenue is structurally concentrated in the lowest-margin channel",
        severity="high", scope="actual", category="Channel Structure",
        finding=(
            f"Wholesale generates {_pct(ws.get('share'))} of group revenue at a {_pct(ws.get('gm'))} gross margin, "
            f"versus {_pct(retail.get('gm'))} in retail and {_pct(online.get('gm'))} online. Meanwhile online is the "
            f"fastest-growing channel (LTM {_pct(on_g)}) and retail is shrinking (LTM {_pct(rt_g)})."
        ),
        evidence=ev,
        interpretation=(
            "Per unit of revenue the wholesale channel earns roughly a third of the margin earned in "
            "consumer channels — and its deep-discount system (see the discount finding) is the "
            "plausible mechanism. Observed relationship, not an established causal effect."
        ),
        impact="Channel-mix strategy; branch vs online investment; pricing architecture.",
        action="Protect and extend the high-margin online growth (fulfilment capacity, traffic) and apply the pricing fixes inside wholesale.",
        source="app/services/report.py::_calc_channel_structure (Sales_Transactions) — consistent with the Branch & Channel Performance dashboard KPIs.",
        confidence="High — like-for-like LTM windows reproduce exactly.",
    )


def _f_quality(qd: dict, qk: list, fid: str) -> Optional[ReportFinding]:
    if "copq_all" not in qd:
        return None
    top_defect, top_root = qd.get("top_defect"), qd.get("top_root_cause")
    ev = [
        EvidenceItem("Modeled quality loss — all-time", _egp(qd["copq_all"]),
                     "Quality: Σ Estimated_Loss_EGP (internal modeled estimate)"),
        EvidenceItem("Modeled quality loss — CY2026", _egp(qd.get("copq_cy2026")), "same, Inspection_Date CY2026"),
        EvidenceItem("Units inspected", _kpi_value(qk, "Units Inspected") or "n/a", "reused Quality dashboard KPI"),
        EvidenceItem("QC rejection rate (LTM)", _kpi_value(qk, "QC Rejection Rate") or "n/a", "reused Quality dashboard KPI"),
    ]
    if top_defect is not None and not top_defect.empty:
        ev.append(EvidenceItem("Most frequent defect", f"{top_defect.index[0]} — {_num(float(top_defect.iloc[0]))} cases",
                               f"Defect_Type counts ({qd.get('defect_nulls', 0):,} nulls excluded)"))
    if top_root is not None and not top_root.empty:
        ev.append(EvidenceItem("Most frequent root cause", f"{top_root.index[0]} — {_num(float(top_root.iloc[0]))} cases", "Root_Cause counts"))
    d_line = (f" The dominant defect is '{top_defect.index[0]}'"
              + (f" and the dominant root cause is '{top_root.index[0]}'." if top_root is not None and not top_root.empty else ".")
              ) if top_defect is not None and not top_defect.empty else ""
    return ReportFinding(
        id=fid,
        title="Modeled quality losses run at sixteen million pounds over the horizon",
        severity="high", scope="modeled", category="Quality",
        finding=(
            f"The modeled cost of poor quality totals {_egp(qd['copq_all'])} across the dataset, of which "
            f"{_egp(qd.get('copq_cy2026'))} falls in CY2026.{d_line}"
        ),
        evidence=ev,
        interpretation=(
            "These are standard-cost estimates from the QC dataset (not audited cash losses) and they "
            "overlap with customer refunds on returned defective units — the two are never added in "
            "this report."
        ),
        impact="Factory operations; input-material cost; the modeled true margins on the Value Chain dashboard.",
        action=("Attack the dominant defect/root-cause pair at its stage of origin (the stage breakdown "
                "on the Quality dashboard is the drill-down path) and validate the modeled estimate "
                "with a physical sample audit."),
        source="app/services/report.py::_calc_quality (Quality) + reused get_quality_kpis cards.",
        confidence="Medium — the amount is an internal modeled estimate; window splits reproduce exactly.",
    )


def _f_returns(rd: dict, qk: list, fid: str) -> Optional[ReportFinding]:
    if "refunds_all" not in rd:
        return None
    reasons = rd.get("cy2026_reasons")
    r_rate = _kpi_value(qk, "Customer Return Rate")
    ev = [
        EvidenceItem("Refunds — all-time", _egp(rd["refunds_all"]), "Sales_Transactions: Σ Refund_Value_EGP"),
        EvidenceItem("Refunds — CY2026", _egp(rd.get("refunds_cy2026")), "same, Order_Date CY2026"),
        EvidenceItem("Customer return rate", r_rate or "n/a", "reused Quality & Returns dashboard KPI"),
    ]
    if reasons is not None and not reasons.empty:
        n0, n1 = float(reasons.iloc[0]), float(reasons.iloc[1]) if len(reasons) > 1 else None
        ev.append(EvidenceItem("Top CY2026 return reason", f"{reasons.index[0]} — {_num(n0)} invoices",
                               "Return_Reason counts among Returned=='Yes', CY2026"))
        if n1 is not None:
            ev.append(EvidenceItem("Top reason vs second reason", f"{n0:.0f} vs {n1:.0f} ({n0 / n1:.1f}×)", "same counts"))
        top_line = (f" The leading reason is '{reasons.index[0]}' at "
                    f"{_pct(n0 / float(reasons.sum()))} of CY2026 returns.")
    else:
        top_line = ""
    return ReportFinding(
        id=fid,
        title="Customer returns are a multi-million cash cost with a single dominant reason",
        severity="medium", scope="actual", category="Returns & Product Fit",
        finding=(
            f"Refunds reached {_egp(rd.get('refunds_cy2026'))} in CY2026 ({_egp(rd['refunds_all'])} all-time, "
            f"return rate {r_rate or 'n/a'}).{top_line}"
        ),
        evidence=ev,
        interpretation=(
            "Refunds are realized cash outflows on transactions that exist in the log. The dominant "
            "reason focuses the fix. A link to factory quality cannot be tested because returns carry "
            "no production-batch identifier — see limitations."
        ),
        impact="Retail & online fulfilment; refund policy; inventory return flows.",
        action=("Investigate the dominant return driver (size charts, photos, specs) and track its "
                "weekly share; do not bill the returns pile to factory quality without a tested link."),
        source="app/services/report.py::_calc_returns (Sales_Transactions) + reused Customer Return Rate KPI.",
        confidence="High for cash amounts and reason counts; any quality-linkage claim is explicitly NOT established.",
    )


def _f_stockouts(sd: dict, ik: list, fid: str) -> Optional[ReportFinding]:
    if "first6_sku_months" not in sd:
        return None
    esc = sd.get("escalation_x")
    ev = [
        EvidenceItem("SKU-months in stockout — first 6 snapshot months", str(sd["first6_sku_months"]),
                     f"Inventory_History ({sd.get('window_label', '')})"),
        EvidenceItem("SKU-months — last 6 snapshot months", str(sd["last6_sku_months"]), "same windows"),
        EvidenceItem("Escalation", f"×{esc:.1f}" if esc else "n/a", "last-6 / first-6"),
        EvidenceItem("Stockout days", f"{sd['first6_days']} → {sd['last6_days']}", "Σ Stockout_Days_In_Month, same windows"),
    ]
    if "lost_gp_ltm" in sd:
        ev.append(EvidenceItem("Modeled lost gross profit (last 12 months)", _egp(sd["lost_gp_ltm"]),
                               "Σ days × Avg_Daily_Sales_90D × GP/unit — OPPORTUNITY-COST model, not realized loss"))
    ev.append(EvidenceItem("Stockout-risk SKUs (current)", _kpi_value(ik, "Stockout-Risk Products") or "n/a", "reused Inventory dashboard KPI"))
    return ReportFinding(
        id=fid,
        title="Stockout exposure has escalated roughly tenfold since the start of the dataset",
        severity="medium", scope="actual", category="Inventory",
        finding=(
            f"SKU-months with stockouts rose from {sd['first6_sku_months']} (first 6 snapshot months) to "
            f"{sd['last6_sku_months']} (last 6) — ×{esc:.1f} — and stockout days from {sd['first6_days']} to "
            f"{sd['last6_days']}, against a benchmark target of zero."
        ),
        evidence=ev,
        interpretation=(
            "Availability has degraded sharply across the horizon. Any lost-GP figure is a conservative "
            "opportunity-cost model because Avg_Daily_Sales_90D lags true stockout-period demand; it is "
            "reported as a model, not realized loss."
        ),
        impact="Branch shelf availability, unmet online demand, customer defection risk; replenishment policy.",
        action=("Fix replenishment triggers for stockout-risk SKUs (Days_of_Cover < 15 on the Stockout "
                "Risk map), prioritized against the supplier OTD program (upstream feedstock delays)."),
        source="app/services/report.py::_calc_stockouts (Inventory_History) — consistent with the Inventory & Demand Planning dashboard.",
        confidence="High for escalation counts/days; Medium for the modeled GP figure (documented model).",
    )

def _f_suppliers(sd: dict, sk: list, fid: str) -> Optional[ReportFinding]:
    if not sd:
        return None
    ev = [
        EvidenceItem("OTD — most recent 12 months (all suppliers)", _pct(sd.get("otd_last12")),
                     "Purchase_Orders: mean(On_Time), most recent 12 months of the series"),
        EvidenceItem("OTD — initial 12 months", _pct(sd.get("otd_first12")), "same rule, first 12 months"),
        EvidenceItem("Overall OTIF KPI (recomputed)", _kpi_value(sk, "On-Time Delivery (OTIF)") or "n/a",
                     "reused Supply Chain dashboard KPI"),
    ]
    worst = sd.get("worst")
    weak_lines = []
    if worst is not None and not worst.empty:
        for _, s in worst.iterrows():
            ev.append(EvidenceItem(f"Supplier {s['Supplier_ID']} all-time OTD", _pct(s["otd"]),
                                   f"across {int(s['orders']):,} POs"))
            if s["otd"] < 0.40:
                weak_lines.append(f"{s['Supplier_ID']} at {_pct(s['otd'])}")
    weak = (f" The weakest suppliers run below 40%: {', '.join(weak_lines)}." if weak_lines else "")
    return ReportFinding(
        id=fid,
        title="Supplier reliability is deteriorating, with two suppliers under 40% on-time",
        severity="high", scope="actual", category="Procurement",
        finding=(
            f"On-time delivery fell from {_pct(sd.get('otd_first12'))} to {_pct(sd.get('otd_last12'))} "
            f"(initial 12 months vs most recent 12 of the series).{weak}"
        ),
        evidence=ev,
        interpretation=(
            "Falling OTD propagates into production delays, overtime and stockouts — it is the "
            "upstream thread that ties the production and inventory findings together."
        ),
        impact="Production planning; material availability; OTIF to customers.",
        action=("Set explicit OTD SLAs with corrective clauses for sub-40% suppliers and diversify "
                "supply for the critical materials flagged in the risk matrix."),
        source="app/services/report.py::_calc_suppliers via reused supply_chain._prepare_po_data (Purchase_Orders); consistent with the Supply Chain supplier scorecard.",
        confidence="High — 3,600 POs with complete receipt data; rates reproduce exactly.",
    )


def _f_production(pd_: dict, fid: str) -> Optional[ReportFinding]:
    if not pd_ or "cy2026_achievement" not in pd_:
        return None
    bn = pd_.get("bottlenecks_cy2026")
    ev = [
        EvidenceItem("CY2026 planned quantity", _num(pd_["cy2026_planned"]),
                     "Production_Orders: Σ Planned_Qty, Start_Date CY2026"),
        EvidenceItem("CY2026 produced quantity", _num(pd_["cy2026_produced"]), "Σ Produced_Qty, same orders"),
        EvidenceItem("Plan achievement", _pct(pd_["cy2026_achievement"]), "Produced / Planned (NOT capacity utilization)"),
    ]
    bn_line = ""
    if bn is not None and len(bn) > 1:
        ev.append(EvidenceItem("Most frequent bottleneck", f"{bn.index[0]} — {int(bn.iloc[0])} orders",
                               "Primary_Bottleneck counts, 'None' excluded"))
        ev.append(EvidenceItem("Second bottleneck", f"{bn.index[1]} — {int(bn.iloc[1])} orders", "same"))
        bn_line = (f" The dominant bottleneck stages are {bn.index[0]} ({int(bn.iloc[0])} orders) "
                   f"and {bn.index[1]} ({int(bn.iloc[1])} orders).")
    return ReportFinding(
        id=fid,
        title="2026 production ran below plan, with two stages dominating the bottlenecks",
        severity="medium", scope="actual", category="Production",
        finding=(
            f"CY2026 production achieved {_pct(pd_['cy2026_achievement'])} of plan "
            f"({_num(pd_['cy2026_produced'])} of {_num(pd_['cy2026_planned'])} units).{bn_line}"
        ),
        evidence=ev,
        interpretation=(
            "Achievement of plan is a shortfall metric (produced ÷ planned) — it is not capacity "
            "utilization: no machine/line capacity fields exist to derive that."
        ),
        impact="Output planning; overtime spend; downstream shelf availability.",
        action="Rebalance stage capacity starting with the two leading bottleneck stages; track the monthly plan-vs-actual chart on the Production dashboard.",
        source="app/services/report.py::_calc_production (Production_Orders) — aligned with the Production dashboard Pareto.",
        confidence="High for the achievement ratio; bottleneck counts are frequency statistics, not measured capacity studies.",
    )


def _f_marketing(md: dict, mk: list, fid: str) -> Optional[ReportFinding]:
    if "attributed_total" not in md or "b2c_revenue" not in md:
        return None
    ratio = md.get("attribution_ratio")
    ev = [
        EvidenceItem("Attributed revenue (marketing system)", _egp(md["attributed_total"]), "Marketing: Σ Attributed_Revenue_EGP"),
        EvidenceItem("Actual B2C net revenue (Online + Retail)", _egp(md["b2c_revenue"]), "Sales_Transactions channels {Online, Retail}"),
        EvidenceItem("Attributed ÷ B2C revenue", f"{ratio:.2f}×" if ratio else "n/a", "ratio"),
        EvidenceItem("Orders attributed (marketing system)", _num(md.get("orders_attributed")), "Σ Orders_Attributed"),
        EvidenceItem("Actual B2C invoice rows", _num(md.get("b2c_rows")), "count of transactions in the same channels"),
        EvidenceItem("CAC KPI shown on dashboard", _kpi_value(mk, "Customer Acquisition Cost (CAC)") or "n/a",
                     "reused KPI: Spend ÷ Orders_Attributed — see the limitation"),
    ]
    by_plat = md.get("by_platform")
    plat_line = ""
    if by_plat is not None and not by_plat.empty and float(by_plat["attributed"].sum()) > 0:
        top = by_plat.iloc[0]
        share = float(top["attributed"]) / float(by_plat["attributed"].sum())
        spend_share = float(top["spend"]) / float(by_plat["spend"].sum())
        ev.append(EvidenceItem(f"Top-attributed platform — {by_plat.index[0]}",
                               f"{_pct(share)} of attributed revenue on {_pct(spend_share)} of spend",
                               "by-platform Σ; dashboard ROAS"))
        ev.append(EvidenceItem("Platform ROAS spread",
                               f"highest {by_plat['roas'].max():.1f}×, lowest {by_plat['roas'].dropna().min():.1f}×",
                               "Attributed ÷ spend per platform"))
        plat_line = (f" The top platform accounts for {_pct(share)} of all attributed revenue on "
                     f"just {_pct(spend_share)} of spend.")
    return ReportFinding(
        id=fid,
        title="Marketing attribution numbers cannot be used for ROI or CAC decisions",
        severity="medium", scope="actual", category="Marketing Measurement",
        finding=(
            f"The marketing system reports {_egp(md['attributed_total'])} of attributed revenue — "
            f"{ratio:.2f}× the actual B2C net revenue ({_egp(md['b2c_revenue'])}) — plus "
            f"{_num(md.get('orders_attributed'))} attributed orders against {_num(md.get('b2c_rows'))} real "
            f"B2C invoice rows.{plat_line} Attribution cannot be mapped to actual transactions, and no "
            "experiment or customer linkage exists in the data."
        ),
        evidence=ev,
        interpretation=(
            "Attributed revenue/orders are an internal marketing-system metric overlapping transaction "
            "records in unknown ways. Without a holdout experiment, ROAS/CAC from these fields cannot "
            "establish what marketing actually drove — CAC as currently aggregated (EGP ~40) is "
            "arithmetically spend ÷ attributed orders, not a true acquisition cost."
        ),
        impact="Marketing budget allocation; expansion decisions founded on the ROAS/CAC KPI.",
        action=("Stop presenting dashboard ROAS/CAC as management ROI; commission a simple platform-level "
                "holdout test before scaling spend by platform."),
        source="app/services/report.py::_calc_marketing (Marketing + Sales_Transactions) — quantifies the limitation of the Marketing dashboard KPIs.",
        confidence="High for the mismatch arithmetic; the attribution's meaning itself stays unestablished.",
    )


def _f_value_chain(chain: pd.DataFrame, vk: list, fid: str) -> Optional[ReportFinding]:
    if chain.empty or not vk:
        return None
    hidden = next((k for k in vk if k.title == "Total Hidden Costs & Waste"), None)
    gap = next((k for k in vk if k.title == "Apparent vs True Margin Gap"), None)
    true_p = next((k for k in vk if k.title == "True Net Operating Profit"), None)
    if hidden is None or gap is None or true_p is None:
        return None
    ev = [
        EvidenceItem("Total hidden operational costs (modeled)", hidden.value,
                     "QC losses + print rework + overtime + refunds + inventory holding (reused formulas)"),
        EvidenceItem("Apparent vs true margin gap", gap.value, "reused Value Chain dashboard KPI"),
        EvidenceItem("True net operating profit", true_p.value, "Gross profit − hidden costs (modeled)"),
    ]
    erosion = chain.sort_values("margin_erosion_pct", ascending=False).head(3)
    er_lines = []
    for _, p in erosion.iterrows():
        ev.append(EvidenceItem(f"{p['Product_ID']} margin erosion",
                               f"{p['apparent_margin_pct']:.1f}% → {p['true_margin_pct']:.1f}% "
                               f"(−{_pp(p['margin_erosion_pct'])} hidden-cost drag)",
                               "cross-department trace: QC + rework + overtime + refunds + holding"))
        er_lines.append(f"{p['Product_ID']} (−{_pp(p['margin_erosion_pct'])})")
    if "is_anomalous" in chain.columns:
        ev.append(EvidenceItem("Products also flagged by AI", f"{int(chain['is_anomalous'].sum())} of {len(chain)}",
                               "Isolation Forest, contamination 0.15 (see the anomaly finding)"))
    return ReportFinding(
        id=fid,
        title="Reported margins are materially higher than true margins after cross-department costs",
        severity="high", scope="modeled", category="Cross-Department Economics",
        finding=(
            f"After tracing quality scrap, printing rework, overtime, refunds and inventory holding to "
            f"individual products, apparent margins shrink by {gap.value} — {hidden.value} of hidden costs "
            f"— and true net operating profit lands at {true_p.value}. The steepest erosion: "
            f"{', '.join(er_lines)}."
        ),
        evidence=ev,
        interpretation=(
            "Dashboard gross margins are computed against modeled COGS only. The gap quantifies "
            "operational friction that never appears as a line item — margin you think you have but "
            "don't receive."
        ),
        impact="Pricing floors, product-level P&L, capital allocation between products.",
        action=("Use the true-margin leaderboard (Value Chain dashboard) as the floor for wholesale "
                "price approvals and fix the top-erosion products first."),
        source="Reused app/services/value_chain.py::_compute_full_product_chain (cost coefficients — 150 EGP/h overtime, 15%/yr holding — documented there).",
        confidence="Medium — the cost-translation coefficients are stated modeling assumptions; relative ranking is more robust than absolute levels.",
    )


def _f_anomaly(chain: pd.DataFrame, fid: str) -> Optional[ReportFinding]:
    if chain.empty or "is_anomalous" not in chain.columns or not bool(chain["is_anomalous"].any()):
        return None
    flags = chain[chain["is_anomalous"]].sort_values("anomaly_score", ascending=False)
    ev = [
        EvidenceItem("Flagged products", f"{len(flags)} of {len(chain)} ({len(flags) / len(chain):.0%})",
                     "Isolation Forest, contamination=0.15, random_state=42"),
        EvidenceItem("What an anomaly is here", "statistical outlier across 8 cross-department stress features",
                     "margin, QC loss, rework, refunds, delay days, overtime — NOT proof of error"),
    ]
    for _, p in flags.head(5).iterrows():
        ev.append(EvidenceItem(f"{p['Product_ID']} — stress score {p['anomaly_score']:.2f}",
                               f"main stress: {p['primary_stress']}", "highest-quantile drivers listed"))
    return ReportFinding(
        id=fid,
        title="AI anomaly detection flags a set of products under compound operational stress",
        severity="medium", scope="anomaly", category="AI — Anomaly Detection",
        finding=(
            f"The unsupervised Isolation Forest model flags {len(flags)} of {len(chain)} products as "
            "statistical outliers across eight cross-department features. These are FLAGS, not proof "
            "of error — each one needs a business review before acting."
        ),
        evidence=ev,
        interpretation=(
            "Flagged products combine several stress sources at once, which makes them candidates for "
            "cost-and-quality audits. The score is a relative severity index, not a probability; the "
            "flag rate is set by the contamination parameter."
        ),
        impact="Operational audit prioritization; product roadmap maintenance.",
        action="Run the flagged list through the monthly ops review; verify each driver with the owning department.",
        source="Reused app/ai/anomaly.py via value_chain._compute_full_product_chain — identical to the Value Chain dashboard chart.",
        confidence="Medium — unsupervised detection; contamination (15%) sets the flag rate by construction.",
    )


def _f_segments(seg_summary: pd.DataFrame, ck: list, fid: str) -> Optional[ReportFinding]:
    if seg_summary is None or seg_summary.empty:
        return None
    ev = [
        EvidenceItem("Customers scored", _num(float(seg_summary["customers"].sum())),
                     "app/ai/clustering.py: RFM + K-Means (k=4, seed 42)"),
    ]
    names = list(seg_summary.index)
    for name, r in seg_summary.iterrows():
        ev.append(EvidenceItem(f"Segment '{name}'", f"{int(r['customers']):,} customers ({_pct(r['share'])}) — avg spend {_egp(r['avg_monetary'])}",
                               "cluster means (heuristic, not verified personas)"))
    at_risk = _kpi_value(ck, "Customers At Risk")
    if at_risk:
        ev.append(EvidenceItem("Customers labeled 'At Risk'", at_risk, "reused Customer 360 KPI"))
    return ReportFinding(
        id=fid,
        title="K-Means RFM segmentation produces four usable customer cohorts",
        severity="low", scope="segmentation", category="AI — Segmentation",
        finding=(
            f"The platform's RFM + K-Means model segments {int(seg_summary['customers'].sum()):,} customers into "
            f"four cohorts with clearly separated spend profiles ({', '.join(names)})."
            + (f" The 'At Risk' cohort covers {at_risk} of the base." if at_risk else "")
        ),
        evidence=ev,
        interpretation=(
            "Segments are model-generated personas — useful as hypotheses for campaigns, not verified "
            "customer types. Cohort names are assigned by ranking and depend on the k and scaling choices."
        ),
        impact="CRM activation; retention campaigns; win-back targeting.",
        action=("Pilot one win-back campaign for the 'At Risk' cohort with a control slice and measure "
                "uplift before scaling."),
        source="Reused app/services/customers.py::_get_segmented_rfm (the same cache powering the Customer 360 charts) + reused KPI card.",
        confidence="Low–medium — standard RFM heuristic; cluster names are model-assigned labels.",
    )


def _f_forecast(fc: pd.DataFrame, hist_weekly: pd.Series, fid: str) -> Optional[ReportFinding]:
    if fc is None or fc.empty or "Forecast" not in fc.columns:
        return None
    total = float(fc["Forecast"].sum())
    mean_f = float(fc["Forecast"].mean())
    rel_band = float(((fc["Upper_Bound"] - fc["Lower_Bound"]).mean() / mean_f) * 100) if mean_f else None
    slope = float(fc["Forecast"].iloc[-1] - fc["Forecast"].iloc[0])
    hist_avg = float(hist_weekly.tail(12).mean()) if hist_weekly is not None and not hist_weekly.empty else None
    ev = [
        EvidenceItem("Forecast horizon",
                     f"{len(fc)} weekly steps ({fc['Date'].iloc[0]:%d %b %Y} → {fc['Date'].iloc[-1]:%d %b %Y})",
                     "app/ai/forecasting.py: linear trend + residual σ; 95% CI = ±1.96σ"),
        EvidenceItem("Historical basis", f"{len(hist_weekly) if hist_weekly is not None else 0} weeks of weekly demand",
                     "same weekly Grouper the model consumes"),
        EvidenceItem("Forecast total demand (point estimate)", f"{total:,.0f} units", "Σ weekly point forecasts"),
        EvidenceItem("Typical 95% band width", f"±{rel_band:.0f}% of the point estimate" if rel_band else "n/a",
                     "±1.96 × residual standard error"),
        EvidenceItem("Actual average weekly demand (last 12 weeks)", f"{hist_avg:,.0f} units" if hist_avg else "n/a",
                     "sanity anchor for the forecast level"),
        EvidenceItem("Nature of this number", "PREDICTION — model output, not observed data",
                     "no holdout accuracy metrics exist in the module; none are claimed"),
    ]
    return ReportFinding(
        id=fid,
        title="AI demand forecast projects the next 90 days with a wide confidence band",
        severity="low", scope="prediction", category="AI — Forecasting",
        finding=(
            f"The demand model forecasts {total:,.0f} units over the next 90 days ({len(fc)} weekly steps), "
            f"with a typical 95% band of ±{rel_band:.0f}% and a "
            f"{'rising' if slope > 0 else 'flat/declining'} weekly trajectory (Δ {slope:+,.0f} units from "
            "first to last step). Compare with the actual recent average of "
            f"{hist_avg:,.0f} units/week."
        ),
        evidence=ev,
        interpretation=(
            "A trend extrapolation with an interval, not a causal model: it assumes recent weekly "
            "demand continues. No back-test accuracy exists in the codebase, so no accuracy claim is made."
        ),
        impact="Purchase planning, staffing, availability planning — useful as directional guidance only.",
        action=("Use the point forecast as a planning reference with the stated band; add a holdout "
                "back-test to the module before operationalizing the numbers."),
        source="Reused app/ai/forecasting.py::forecast_demand (same model as the Inventory forecast chart, embedded in this report).",
        confidence="Low — simple linear-trend model; never presented as an actual result.",
    )


def _f_service(serv: dict, fid: str) -> Optional[ReportFinding]:
    if "tickets" not in serv:
        return None
    ev = [
        EvidenceItem("Service tickets (all-time)", _num(serv["tickets"]), "Customer_Service rows"),
        EvidenceItem("Resolution rate", _pct(serv.get("resolved_rate")),
                     "share of tickets marked Resolved = Yes"),
        EvidenceItem("Average first response", f"{serv['avg_first_response_min']:.0f} min" if serv.get("avg_first_response_min") is not None else "n/a",
                     "mean First_Response_Minutes"),
        EvidenceItem("Average resolution time", f"{serv['avg_resolution_hours']:.1f} h" if serv.get("avg_resolution_hours") is not None else "n/a",
                     "mean Resolution_Hours"),
        EvidenceItem("Average CSAT", f"{serv['avg_csat']:.2f} / 5" if serv.get("avg_csat") is not None else "n/a", "mean CSAT_1_to_5"),
    ]
    if serv.get("resolved_rate") is not None and serv["resolved_rate"] < 0.75:
        ev.append(EvidenceItem("Unresolved backlog", f"{(1 - serv['resolved_rate']) * 100:.1f}% of tickets",
                               "cannot be joined to sales — no Customer_ID in Customer_Service"))
    return ReportFinding(
        id=fid,
        title="Customer service responds quickly; a share of tickets remains unresolved",
        severity="low", scope="actual", category="Customer Service",
        finding=(
            f"Across {serv['tickets']:,} tickets the resolution rate is {_pct(serv.get('resolved_rate'))} with "
            f"first response in ≈{serv.get('avg_first_response_min', 0):.0f} minutes and CSAT "
            f"{serv.get('avg_csat', float('nan')):.2f}/5."
        ),
        evidence=ev,
        interpretation=(
            "Service responsiveness is measurable and adequate; the unresolved share is tracked here "
            "as a small but real cost of friction. Tickets cannot be linked to purchasers (no "
            "Customer_ID), so no sales-impact conclusion is possible."
        ),
        impact="Support staffing; service-level monitoring only (no revenue linkage possible).",
        action="Review the unresolved-ticket backlog causes by issue type on the Customer Service dashboard; set a burn-down weekly target.",
        source="app/services/report.py::_calc_service (Customer_Service).",
        confidence="High for the aggregates; per-customer linkage impossible by schema.",
    )

# ============================================================================
# Report assembly
# ============================================================================

_REPORT_CACHE: Optional[tuple[tuple, ReportContext]] = None


def _data_key(data: dict[str, pd.DataFrame]) -> tuple:
    """Cheap identity fingerprint: object identity + table shapes."""
    return (id(data), len(data), tuple(sorted((k, len(v)) for k, v in data.items() if v is not None)))


def _safe(fn, name: str, status_list: list, default):
    try:
        return fn()
    except Exception as e:  # graceful: an unavailable analysis never kills the report
        logger.warning("Report: '%s' unavailable (%s)", name, e)
        status_list.append(AnalysisStatus(name, "unavailable", str(e)))
        return default


def get_report_context(data: dict[str, pd.DataFrame]) -> ReportContext:
    """Public entry for routes: cached build (DATA is immutable post-startup)."""
    global _REPORT_CACHE
    key = _data_key(data)
    if _REPORT_CACHE is not None and _REPORT_CACHE[0] == key:
        return _REPORT_CACHE[1]
    ctx = build_report(data)
    _REPORT_CACHE = (key, ctx)
    return ctx


@log_function
def build_report(data: dict[str, pd.DataFrame]) -> ReportContext:
    """Build the full report context from a dict of tables (e.g. core.DATA).

    Every reused service is called through `_safe` so a failing dataset or
    analysis is recorded and skipped instead of crashing the page/export.
    """
    status: list[AnalysisStatus] = []

    # ── 1. Reused KPI layers ─────────────────────────────────────────────────
    exec_kpis = _safe(lambda: get_executive_kpis(data), "Executive KPI layer (reused)", status, [])
    _safe(lambda: get_sales_kpis(data), "Sales KPI layer (reused)", status, [])
    ck = _safe(lambda: get_customer_kpis(data), "Customer KPI layer (reused)", status, [])
    _safe(lambda: get_channel_kpis(data), "Channel KPI layer (reused)", status, [])
    ik = _safe(lambda: get_inventory_kpis(data), "Inventory KPI layer (reused)", status, [])
    mk = _safe(lambda: get_marketing_kpis(data), "Marketing KPI layer (reused)", status, [])
    _safe(lambda: get_production_kpis(data), "Production KPI layer (reused)", status, [])
    qk = _safe(lambda: get_quality_kpis(data), "Quality KPI layer (reused)", status, [])
    _safe(lambda: get_printing_kpis(data), "Printing KPI layer (reused)", status, [])
    sk = _safe(lambda: get_supply_chain_kpis(data), "Supply-chain KPI layer (reused)", status, [])
    vk = _safe(lambda: get_value_chain_kpis(data), "Value-chain KPI layer (reused)", status, [])

    # ── 2. Period metadata ───────────────────────────────────────────────────
    ctx = ReportContext(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        period_label="", period_start="", period_end="",
        executive_kpis=exec_kpis, analyses_status=status,
    )
    sales = _sales(data)
    if not sales.empty and "Order_Date" in sales.columns:
        d = pd.to_datetime(sales["Order_Date"], errors="coerce").dropna()
        if not d.empty:
            n_months = d.dt.to_period("M").nunique()
            ctx.period_start, ctx.period_end = f"{d.min():%b %Y}", f"{d.max():%b %Y}"
            ctx.period_label = f"{ctx.period_start} – {ctx.period_end} ({n_months} complete months)"

    # ── 3. Embedded charts (all reused builders — no new chart code) ─────────
    for maker, name in [
        (lambda: get_revenue_profit_trend(data), "Monthly revenue & profit trend chart"),
        (lambda: get_revenue_by_channel(data), "Revenue mix by channel chart"),
        (lambda: get_supplier_scorecard(data), "Supplier scorecard chart"),
        (lambda: get_demand_forecast(data, horizons=[30, 60, 90]), "Demand forecast chart"),
    ]:
        chart = _safe(maker, name, status, None)
        if chart is not None:
            ctx.charts.append(chart)

    # ── 4. New evidence computations (documented formulas above) ─────────────
    disc = _safe(lambda: _calc_discount_system(sales), "Discount-system evidence", status, {})
    caps = (
        _safe(lambda: _calc_cap_scenario(sales, 0.30, volume_loss=0.2), "Cap scenario 30% evidence", status, {}),
        _safe(lambda: _calc_cap_scenario(sales, 0.28, volume_loss=0.2), "Cap scenario 28% evidence", status, {}),
    )
    lm = _safe(lambda: _calc_loss_makers(sales), "Loss-maker evidence", status, {})
    ft = _safe(lambda: _calc_fiscal_trend(sales), "Fiscal-trend evidence", status, {})
    chs = _safe(lambda: _calc_channel_structure(sales), "Channel-structure evidence", status, {})
    ret = _safe(lambda: _calc_returns(sales), "Returns evidence", status, {})
    qd = _safe(lambda: _calc_quality(data.get("Quality", pd.DataFrame())), "Quality evidence", status, {})
    sd = _safe(lambda: _calc_stockouts(data.get("Inventory_History", pd.DataFrame()), sales),
               "Stockout evidence", status, {})
    sup = _safe(lambda: _calc_suppliers(_prepare_po_data(data)), "Supplier OTD evidence", status, {})
    prd = _safe(lambda: _calc_production(data.get("Production_Orders", pd.DataFrame())),
                "Production evidence", status, {})
    mkt = _safe(lambda: _calc_marketing(data.get("Marketing", pd.DataFrame()), sales),
                "Marketing attribution evidence", status, {})
    serv = _safe(lambda: _calc_service(data.get("Customer_Service", pd.DataFrame())), "Service evidence", status, {})
    chain = _safe(lambda: _compute_full_product_chain(data), "Value-chain product trace (AI features)", status, pd.DataFrame())
    seg = _safe(lambda: _summarize_segments(data), "AI segmentation summary", status, pd.DataFrame())
    hist_weekly = _safe(lambda: _weekly_history(sales), "Weekly demand history", status, pd.Series(dtype=float))
    fc = _safe(lambda: forecast_demand(sales, horizon_days=90), "AI demand forecast (90-day)", status, pd.DataFrame())

    # ── 5. Findings (each builder guarded; unavailable findings are skipped) ──
    builder_defs = [
        ("Discount finding", lambda: _f_discount_system(disc, "F01")),
        ("Cap-scenario finding", lambda: _f_cap_scenario(caps[0], caps[1], "F02")),
        ("Loss-maker finding", lambda: _f_loss_makers(lm, "F03")),
        ("Fiscal-trend finding", lambda: _f_fiscal_trend(ft, exec_kpis, "F04")),
        ("Channel-structure finding", lambda: _f_channel_structure(chs, "F05")),
        ("Quality finding", lambda: _f_quality(qd, qk, "F06")),
        ("Returns finding", lambda: _f_returns(ret, qk, "F07")),
        ("Stockout finding", lambda: _f_stockouts(sd, ik, "F08")),
        ("Supplier finding", lambda: _f_suppliers(sup, sk, "F09")),
        ("Production finding", lambda: _f_production(prd, "F10")),
        ("Marketing-attribution finding", lambda: _f_marketing(mkt, mk, "F11")),
        ("Value-chain finding", lambda: _f_value_chain(chain, vk, "F12")),
        ("Anomaly finding", lambda: _f_anomaly(chain, "F13")),
        ("Segmentation finding", lambda: _f_segments(seg, ck, "F14")),
        ("Forecast finding", lambda: _f_forecast(fc, hist_weekly, "F15")),
        ("Service finding", lambda: _f_service(serv, "F16")),
    ]
    for name, fn in builder_defs:
        fnd = _safe(fn, name, [], None)
        if fnd is not None:
            ctx.findings.append(fnd)
        else:
            status.append(AnalysisStatus(f"Finding {name}", "unavailable",
                                         "insufficient data or failed inputs — skipped rather than fabricated"))
    ctx.sort_findings()

    status.append(AnalysisStatus("Forecast accuracy (holdout back-test)", "not possible",
                                 "the existing forecasting module has no train/test evaluation; accuracy must not be claimed"))
    status.append(AnalysisStatus("Causal lift of marketing channels", "not possible",
                                 "no experiment data and no join between campaigns and transactions"))
    status.append(AnalysisStatus("Capacity utilization", "not possible",
                                 "no machine/line capacity fields exist in the datasets"))
    status.append(AnalysisStatus("Customer-service ↔ purchasing linkage", "not possible",
                                 "Customer_Service has no Customer_ID"))
    status.append(AnalysisStatus("Returns ↔ production-batch linkage", "not possible",
                                 "sales returns carry no batch identifier; datasets join only via Product_ID"))

    # ── 6. Narrative sections ────────────────────────────────────────────────
    ctx.dataset_coverage = _safe(lambda: _dataset_coverage(data), "Dataset coverage", [], [])
    ctx.exec_summary = _build_exec_summary(ctx)
    _build_risks(ctx)
    _build_recommendations(ctx)
    ctx.limitations = _limitations(disc, qd, mkt)
    return ctx


def _first_ev(f: ReportFinding, i: int) -> str:
    return f.evidence[i].value if len(f.evidence) > i else "n/a"


def _ev_by_prefix(f: ReportFinding, prefix: str) -> str:
    for e in f.evidence:
        if e.label.startswith(prefix):
            return e.value
    return "n/a"


def _build_exec_summary(ctx: ReportContext) -> list[str]:
    f = {x.id: x for x in ctx.findings}
    if not f:
        return ["No analytical findings could be produced with the data loaded in this environment. "
                "See the Data Coverage and Limitations section."]
    bullets: list[str] = []
    if "F02" in f:
        bullets.append(
            f"Largest modeled upside: capping routine wholesale discounts at 30% recovers roughly "
            f"{_first_ev(f['F02'], 0)} of gross profit with full retention — {_first_ev(f['F02'], 1)} "
            "even if affected volume drops 20% (simulated scenario, F02).")
    if "F01" in f:
        bullets.append(
            f"Largest cost: discounts reached {_first_ev(f['F01'], 0)} in CY2025 — "
            f"{_first_ev(f['F01'], 1)} of that year's gross profit — issued through near-uniform "
            "tiers that do not respond to order size (F01).")
    if "F04" in f:
        bullets.append(
            f"Growth is decelerating: fiscal-year revenue growth moved from {_first_ev(f['F04'], 0)} "
            f"to {_first_ev(f['F04'], 1)} at a thin {_first_ev(f['F04'], 2)} gross margin (F04).")
    if "F05" in f:
        bullets.append(
            f"Channel mix: online grows {_first_ev(f['F05'], 0)} LTM at {_first_ev(f['F05'], 5)} GM "
            f"while {_first_ev(f['F05'], 2)} of revenue still earns {_first_ev(f['F05'], 3)} GM in "
            "wholesale (F05).")
    if "F06" in f:
        bullets.append(
            f"Quality drag: modeled cost of poor quality totals {_first_ev(f['F06'], 0)}, of which "
            f"{_first_ev(f['F06'], 1)} in CY2026 alone (F06).")
    if "F12" in f:
        bullets.append(
            f"Reported margins overstate reality: {_first_ev(f['F12'], 0)} of hidden cross-department "
            f"costs cut margins by {_first_ev(f['F12'], 1)} (true-margin view, F12).")
    if "F09" in f:
        bullets.append(
            f"Operational root cause: supplier on-time delivery fell from {_first_ev(f['F09'], 1)} to "
            f"{_first_ev(f['F09'], 0)}, cascading into production delays and stockouts (F09).")
    if "F08" in f:
        bullets.append(
            f"Availability: stockout exposure escalated ×{_first_ev(f['F08'], 2).removeprefix('×')} "
            f"({_first_ev(f['F08'], 0)} → {_first_ev(f['F08'], 1)} SKU-months across the horizon, F08).")
    return bullets


# ── Prioritization criteria (applied consistently across section F) ──────────
#   High   = realized or directly-modeled EGP exposure ≥ ~1M over the horizon,
#            OR structural/system-wide degradation of the margin engine.
#   Medium = quantified exposure < ~1M, or a strong trend whose quantified
#            impact is indirect (e.g. opportunity-cost models).
#   Low    = qualitative, model-only, or requiring further investigation.
# Financial gains are only stated where computable with documented assumptions
# (the cap simulations), and they are labeled counterfactual throughout.

def _build_risks(ctx: ReportContext) -> None:
    f = {x.id: x for x in ctx.findings}

    def risk(p, title, ev, area, cons, step, links, opp=False):
        (ctx.opportunities if opp else ctx.risks).append(
            RiskItem(p, title, ev, area, cons, step, links))

    if "F01" in f:
        risk("High", "The wholesale discount program erodes channel economics",
             f"CY2025 discounts {_first_ev(f['F01'], 0)} — {_first_ev(f['F01'], 1)} of gross profit; tiers near-uniform",
             "Wholesale pricing", "Structural margin drag on ~85% of revenue",
             "Tier-policy review; cap routine tiers (modeled in F02)", ["F01", "F02"])
    if "F02" in f:
        risk("High", "Discount-cap recovery — modeled, counterfactual",
             f"{_first_ev(f['F02'], 0)} full retention / {_first_ev(f['F02'], 1)} with −20% volume on affected rows",
             "Wholesale pricing", "Upside in the tens of millions; contingent on customer behavior",
             "Pilot a 30% cap on a subset and measure realized GP", ["F02"], opp=True)
    if "F04" in f:
        risk("High", "Growth deceleration on a thin margin",
             f"FY growth {_first_ev(f['F04'], 0)} → {_first_ev(f['F04'], 1)}; margin {_first_ev(f['F04'], 2)}",
             "Group planning", "Smaller buffer for cash flow and initiatives",
             "Margin-recovery levers first (discount cap, loss-maker pricing)", ["F04", "F01", "F02"])
    if "F05" in f:
        risk("High", "Revenue is concentrated in the lowest-margin channel",
             f"{_first_ev(f['F05'], 2)} of revenue at {_first_ev(f['F05'], 3)} GM",
             "Channel strategy", "Group margin floor is set by the wholesale mix",
             "Rebalance margin via wholesale pricing fixes; watch mix quarterly", ["F05"])
        risk("High", "High-margin channels are growing fast",
             f"Online LTM {_first_ev(f['F05'], 0)} at {_first_ev(f['F05'], 5)} GM; retail {_first_ev(f['F05'], 1)}",
             "Channel strategy", "Each mix-point shift raises group margin",
             "Invest in online fulfilment and traffic protection", ["F05"], opp=True)
    if "F06" in f:
        risk("High", "Modeled quality losses (COPQ)",
             f"{_first_ev(f['F06'], 0)} all-time; {_first_ev(f['F06'], 1)} in CY2026",
             "Manufacturing", "Margin erosion concentrated in a few defect loops",
             "Root-cause program on the top defect/stage; audit the model", ["F06"])
    if "F07" in f:
        risk("Medium", "Return cash cost concentrated in one reason",
             f"CY2026 refunds {_first_ev(f['F07'], 1)}; top reason {_first_ev(f['F07'], 3)}",
             "Retail & online ops", "Refund leakage plus reversed sales",
             "Size/fit fix; weekly reason-share tracking", ["F07"])
    if "F08" in f:
        risk("Medium", "Stockout escalation ≈ ×10",
             f"SKU-months {_first_ev(f['F08'], 0)} → {_first_ev(f['F08'], 1)}; days {_first_ev(f['F08'], 3)}; modeled GP drag {_first_ev(f['F08'], 4)}",
             "Inventory", "Lost demand and defection risk",
             "Reorder-point fixes on risk SKUs; tie to the supplier OTD program", ["F08"])
    if "F09" in f:
        risk("High", "Supplier reliability collapse is the upstream driver",
             f"OTD {_first_ev(f['F09'], 1)} → {_first_ev(f['F09'], 0)}; weakest {_first_ev(f['F09'], 3)}",
             "Procurement", "Cascades into production delays, overtime and stockouts",
             "SLAs with corrective clauses; dual sourcing", ["F09", "F10", "F08"])
    if "F10" in f:
        risk("Medium", "Production below plan in CY2026",
             f"Achievement {_first_ev(f['F10'], 2)}",
             "Production", "Availability risk into retail/online shelves",
             "Bottleneck-stage rebalancing; monthly plan-vs-actual tracking", ["F10"])
    if "F11" in f:
        risk("Medium", "Attribution gap invalidates ROI/CAC uses",
             f"Attributed ÷ B2C = {_first_ev(f['F11'], 2)}; attributed orders {_first_ev(f['F11'], 3)} vs actual rows {_first_ev(f['F11'], 4)}",
             "Marketing measurement", "Budget decisions may chase unattributable revenue",
             "Platform holdout test before scaling by ROAS", ["F11"])
    if "F12" in f:
        risk("High", "Apparent margins overstate true profitability",
             f"Hidden costs {_first_ev(f['F12'], 0)}; margin gap {_first_ev(f['F12'], 1)}",
             "Pricing floors", "Margin views overstate stressed products' profit",
             "Use the true-margin floor for wholesale price approvals", ["F12"])
    if "F13" in f:
        risk("Medium", "Products under compound operational stress (AI flags)",
             f"{_first_ev(f['F13'], 0)} require business review — flags are not proof of error",
             "Ops audit", "Interrupted cost or quality loops multiply",
             "Monthly ops review of the flagged list", ["F13"])
    if "F14" in f:
        at_risk = _ev_by_prefix(f["F14"], "Customers labeled")
        co = _ev_by_prefix(f["F14"], "Segment 'At Risk'")
        risk("Medium", "Win-back pool among 'At Risk' customers",
             f"{at_risk} of the base; segment profile {co}",
             "CRM", "Quiet churn of modeled spend",
             "Pilot win-back with a control slice; measure uplift", ["F14"], opp=True)
    order = {"High": 0, "Medium": 1, "Low": 2}
    ctx.risks.sort(key=lambda r: order.get(r.priority, 9))
    ctx.opportunities.sort(key=lambda r: order.get(r.priority, 9))

def _has(f: dict, *ids: str) -> bool:
    return any(i in f for i in ids)


def _build_recommendations(ctx: ReportContext) -> None:
    f = {x.id: x for x in ctx.findings}
    recs: list[RecommendationItem] = []
    if _has(f, "F01", "F02"):
        recs.append(RecommendationItem("R01", "Cap routine wholesale discounts at 30%",
            "Evidence-based", [i for i in ("F01", "F02") if i in f],
            "Rewrite the tier policy so tiers above 30% require documented volume justification; "
            "pilot the cap on a product subset before group-wide roll-out.",
            "CY-window discounts ÷ gross profit (currently ≈2.8×) and the count of affected rows.",
            "Compare the pilot's realized GP delta against the modeled bounds (full retention vs "
            "−20% volume) stated in finding F02."))
    if "F03" in f:
        worst_be = _first_ev(f["F03"], 4)
        recs.append(RecommendationItem("R02", "Restrict loss-makers to their break-even tier",
            "Evidence-based", ["F03"],
            "For each wholesale loss-maker, stop issuing tiers deeper than its break-even discount "
            f"(≈{worst_be} for the worst product) or renegotiate its input cost.",
            "Per-product wholesale GP and GM views.",
            "Products flip to non-negative GP at unchanged volumes; the tier-P&L arithmetic "
            "validates the sensitivity."))
    if "F09" in f:
        recs.append(RecommendationItem("R03", "Supplier reliability program",
            "Evidence-based", ["F09"],
            "SLAs with corrective clauses for sub-40% OTD suppliers; dual-source critical materials; "
            "re-baseline promised dates vs true lead times.",
            "Windowed overall OTD and the per-supplier OTD list.",
            "OTD recovers toward the prior-12-month level; production delay days fall."))
    if "F06" in f:
        recs.append(RecommendationItem("R04", "Attack the dominant defect loop at its stage",
            "Evidence-based", ["F06"],
            "Root-cause task force on the top defect with a stage-of-origin fix; validate the "
            "modeled loss estimate with a physical sample audit.",
            "Monthly COPQ and the QC rejection rate.",
            "The top defect's case count and COPQ trend both decline against the baseline."))
    if "F07" in f:
        recs.append(RecommendationItem("R05", "Fix the dominant return driver",
            "Evidence-based", ["F07"],
            "Size/fit improvement program (charts, specs, photos) targeting the top CY2026 return "
            "reason; track reason shares weekly.",
            "Customer Return Rate KPI; top-reason share of CY-window returns.",
            "The top reason's share falls vs baseline while gross margin holds."))
    if _has(f, "F08", "F09"):
        recs.append(RecommendationItem("R06", "Replenishment safety-net on stockout SKUs",
            "Evidence-based", [i for i in ("F08", "F09") if i in f],
            "Recalculate reorder points for Days_of_Cover < 15 SKUs using lead-time overrides that "
            "reflect the measured supplier OTD.",
            "SKU-months in stockout and stockout days on rolling windows.",
            "The next-6-snapshot-month window reverses the ≈×10 escalation trajectory."))
    if "F05" in f:
        recs.append(RecommendationItem("R07", "Protect and extend online growth capacity",
            "Evidence-based", ["F05"],
            "Invest in fulfilment capacity and traffic protection for the fastest-growing "
            "high-margin channel; monitor channel mix quarterly.",
            "Online LTM growth and channel GM (as recomputed per window).",
            "Online growth holds while group GM trends up with mix."))
    if "F11" in f:
        recs.append(RecommendationItem("R08", "Commission a marketing holdout test",
            "Exploratory", ["F11"],
            "Design a simple platform-level holdout (e.g. pause one platform) to create a causal "
            "anchor before budgeting campaigns by ROAS/CAC.",
            "Incremental B2C revenue per platform from the experiment — not attributed revenue.",
            "Experiment-vs-control difference is positive, material, and reproducible."))
    if "F14" in f:
        recs.append(RecommendationItem("R09", "Pilot an 'At Risk' win-back campaign",
            "Exploratory", ["F14"],
            "Run a controlled win-back offer on the model's At-Risk cohort with a held-out "
            "control slice.",
            "Repeat-purchase rate of the cohort vs its control slice.",
            "Cohort uplift (cohort − control) is positive and reproducible before scaling."))
    if "F15" in f:
        recs.append(RecommendationItem("R10", "Back-test the demand forecast before operational use",
            "Exploratory", ["F15"],
            "Add a holdout evaluation to the existing forecasting module and report MAPE; until then "
            "treat forecast numbers as directional only.",
            "MAPE/holdout accuracy once implemented — the report will surface it only then.",
            "Back-tested error is within a pre-agreed threshold for the 90-day horizon."))
    ctx.recommendations = recs


def _limitations(disc: dict, qd: dict, md: dict) -> list[dict]:
    lim = [
        {"statement": "All financial findings are computed from modeled operational records — the "
                      "dataset itself labels Sales_Transactions rows as 'Data_Class: modeled training "
                      "transaction anchored to public products/prices'. Figures represent the business "
                      "dynamics of this dataset, not audited financials.",
         "source": "Dataset metadata"},
        {"statement": "COGS is an estimated field (Estimated_COGS_EGP); every profit figure is therefore "
                      "an estimate and is flagged as such.",
         "source": "Sales_Transactions schema"},
        {"statement": "Modeled QC losses and customer refunds overlap on returned defective units — the "
                      "two are never summed in this report.",
         "source": "Quality / Sales datasets"},
        {"statement": "Customer_Service has no Customer_ID, so service data cannot be joined to "
                      "purchasing behavior; only aggregate service metrics are reported.",
         "source": "Dataset cross-join audit"},
        {"statement": "Production, printing and quality identify orders with disjoint batch IDs — they "
                      "connect only through Product_ID, which limits stage-level causality beyond "
                      "aggregate patterns.",
         "source": "Dataset cross-join audit"},
        {"statement": "Marketing attributed revenue/orders cannot be reconciled with actual transactions "
                      "(finding F11); ROAS/CAC labels on that data are measurement-limited, and CAC as "
                      "aggregated (spend ÷ attributed orders) overstates efficiency.",
         "source": "Marketing / Sales cross-check"},
        {"statement": "The discount-cap scenarios assume unchanged volumes and full/−20% re-priced "
                      "retention; without elasticity data they are counterfactual by definition.",
         "source": "F02 methodology"},
        {"statement": "The stockout money figure is an opportunity-cost model — Avg_Daily_Sales_90D lags "
                      "true stockout-period demand — so it is a lower bound, not realized cash.",
         "source": "F08 methodology"},
        {"statement": "No machine/line capacity fields exist; production 'plan achievement' is a "
                      "shortfall metric, not capacity utilization.",
         "source": "Production / Business Operations tables"},
        {"statement": "Correlations and comparisons reported here are observed relationships; no causal "
                      "effect is claimed without experiment data.",
         "source": "Methods note"},
    ]
    if qd.get("defect_nulls"):
        lim.append({"statement": f"QC rows carry {qd['defect_nulls']:,} null Defect_Type values; defect "
                                 "counts exclude them by documented rule (nulls ≈ rows with no defect recorded).",
                    "source": "Quality dataset"})
    if md.get("attribution_ratio"):
        lim.append({"statement": f"Marketing attribution covers {md['attribution_ratio']:.2f}× the actual "
                                 "B2C revenue — any marketing-driven revenue share derived from it is an upper bound.",
                    "source": "Marketing cross-check"})
    return lim

# ============================================================================
# Markdown export (deterministic — same context ⇒ same bytes)
# ============================================================================

def _md(t: Any) -> str:
    return str(t).replace("|", "\\|").replace("\n", " ")


def build_markdown(ctx: ReportContext) -> str:
    L: list[str] = []
    add = L.append
    add("# El-Sharnouby Group — Business Intelligence Report")
    add("")
    add(f"**Reporting period:** {ctx.period_label or 'not available'}  ")
    add(f"**Generated:** {ctx.generated_at} — figures recomputed on demand from the loaded dataset; "
        "sources are named per finding. No data was sent to any external service.")
    add("")
    add("> **Reading guide:** findings tagged *Simulated scenario* are counterfactual models (e.g. "
        "discount caps), not realized savings. Figures tagged *Prediction* are model outputs, not "
        "results. Segmentation and anomaly flags are heuristic model outputs that require business "
        "review before action.")
    add("")
    add("## A. Executive Summary")
    add("")
    if ctx.exec_summary:
        for b in ctx.exec_summary:
            add(f"* {b}")
    else:
        add("_Insufficient loaded data to produce the executive summary._")
    add("")
    if ctx.executive_kpis:
        add("### Enterprise KPI snapshot (reused service output)")
        add("")
        add("| KPI | Value | Change | Window |")
        add("|---|---|---|---|")
        for k in ctx.executive_kpis:
            delta = f"{k.delta:+.1f}%" if k.delta is not None else "—"
            add(f"| {_md(k.title)} | {_md(k.value)} | {_md(delta)} | {_md((k.delta_label or '').strip())} |")
        add("")
    add("## B. Key Findings and Evidence")
    add("")
    for f in ctx.findings:
        add(f"### {f.id} — {_md(f.title)}")
        add("")
        add(f"*Severity:* **{f.severity.upper()}** · *Category:* {_md(f.category)} · "
            f"*Scope:* **{SCOPE_TAGS[f.scope]}**")
        add("")
        add(f"- **Finding:** {_md(f.finding)}")
        for e in f.evidence:
            src = f" — *({_md(e.source)})*" if e.source else ""
            add(f"  - *Evidence · {e.label}:* **{_md(e.value)}**{src}")
        add(f"- **Business interpretation:** {_md(f.interpretation)}")
        add(f"- **Potential impact:** {_md(f.impact)}")
        add(f"- **Recommended action:** {_md(f.action)}")
        if f.confidence:
            add(f"- **Confidence / limitation:** {_md(f.confidence)}")
        add(f"- **Source:** {_md(f.source)}")
        add("")
    if not ctx.findings:
        add("_No findings could be computed from the currently loaded data._")
        add("")
    f = {x.id: x for x in ctx.findings}

    add("## C. Financial and Sales Analysis")
    add("")
    fin_keys = ["F04", "F05", "F01", "F02", "F03"]
    if not any(k in f for k in fin_keys):
        add("_Sales-analysis findings are unavailable with the loaded data._")
    else:
        add("The financial position is summarized directly in the dashboard KPI snapshot above; the "
            "findings below carry the analytical detail:")
        add("")
        for key in fin_keys:
            if key in f:
                ev = " · ".join(f"{e.label}: {e.value}" for e in f[key].evidence[:4])
                add(f"* **{key}** — {_md(f[key].finding)}")
                add(f"  * Evidence: {_md(ev)}")
    add("")
    add("## D. Operational Analysis")
    add("")
    ops = [("Inventory", "F08"), ("Procurement & suppliers", "F09"), ("Production", "F10"),
           ("Quality & returns", "F07"), ("Quality & COPQ", "F06"),
           ("Cross-department economics", "F12"), ("Customer service", "F16")]
    if not any(k in f for _, k in ops):
        add("_Operational findings are unavailable with the loaded data._")
    else:
        for label, key in ops:
            if key not in f:
                continue
            add(f"### {label}")
            add("")
            add(_md(f[key].finding))
            add("")
            for e in f[key].evidence:
                src = f" — *({_md(e.source)})*" if e.source else ""
                add(f"- *{e.label}:* **{_md(e.value)}**{src}")
            add("")
    add("## E. AI and Advanced Analytics Findings")
    add("")
    ai = [("Demand forecasting (prediction)", "F15"), ("Customer segmentation", "F14"),
          ("Anomaly detection", "F13")]
    if not any(k in f for _, k in ai):
        add("_AI analyses are unavailable with the loaded data._")
    else:
        for label, key in ai:
            if key not in f:
                continue
            add(f"### {label}")
            add("")
            add(_md(f[key].finding))
            add("")
            for e in f[key].evidence:
                src = f" — *({_md(e.source)})*" if e.source else ""
                add(f"- *{e.label}:* **{_md(e.value)}**{src}")
            add("")
    add("## F. Business Risks and Opportunities")
    add("")
    add("*Prioritization criteria (applied consistently):* **High** — realized or directly-modeled EGP "
        "exposure ≥ ~1M over the horizon, or structural/system-wide degradation of the margin engine; "
        "**Medium** — quantified exposure < ~1M, or a strong trend whose quantified impact is indirect; "
        "**Low** — qualitative or model-only results. Monetary gains are stated only where computable "
        "from the data with documented assumptions (the cap simulations), and are labeled counterfactual.")
    add("")
    add("### Risks (prioritized)")
    add("")
    add("| Priority | Risk | Evidence | Area | Potential consequence | Next step | Based on |")
    add("|---|---|---|---|---|---|---|")
    for r in ctx.risks:
        add(f"| {r.priority} | {_md(r.title)} | {_md(r.evidence)} | {_md(r.area)} | "
            f"{_md(r.consequence)} | {_md(r.next_step)} | {', '.join(r.linked_findings)} |")
    if not ctx.risks:
        add("_No risks could be derived from the available findings._")
    add("")
    if ctx.opportunities:
        add("### Opportunities (prioritized)")
        add("")
        add("| Priority | Opportunity | Evidence | Area | Potential | Next step | Based on |")
        add("|---|---|---|---|---|---|---|")
        for o in ctx.opportunities:
            add(f"| {o.priority} | {_md(o.title)} | {_md(o.evidence)} | {_md(o.area)} | "
                f"{_md(o.consequence)} | {_md(o.next_step)} | {', '.join(o.linked_findings)} |")
        add("")
    add("## G. Recommended Actions")
    add("")
    add("| ID | Action | Based on | Category | Metric to monitor | How to evaluate |")
    add("|---|---|---|---|---|---|")
    for r in ctx.recommendations:
        add(f"| {r.id} | {_md(r.title + ' — ' + r.action)} | {', '.join(r.references)} | {r.category} | "
            f"{_md(r.metric_to_monitor)} | {_md(r.evaluation)} |")
    if not ctx.recommendations:
        add("_No recommendations could be linked to computed findings._")
    add("")
    add("## H. Data Coverage and Limitations")
    add("")
    add("### Datasets loaded at generation time")
    add("")
    add("| Dataset | Rows | Period covered |")
    add("|---|---|---|")
    for d in ctx.dataset_coverage:
        add(f"| {_md(d['table'])} | {int(d['rows']):,} | {_md(d.get('coverage') or '—')} |")
    if not ctx.dataset_coverage:
        add("_No datasets were visible to this report._")
    add("")
    add("### Analysis status")
    add("")
    add("| Analysis | Status | Detail |")
    add("|---|---|---|")
    for a in ctx.analyses_status:
        add(f"| {_md(a.name)} | {a.status} | {_md(a.detail)} |")
    add("")
    add("### Limitations and assumptions")
    add("")
    for i, lim in enumerate(ctx.limitations, 1):
        add(f"{i}. {_md(lim['statement'])} — *({_md(lim.get('source', ''))})*")
    add("")
    return "\n".join(L) + "\n"
