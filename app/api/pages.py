"""
Page Router — All 11 HTML page routes serving Jinja2 templates.
Phases 1, 2, and 3 Pages are fully wired to active analytics and AI services.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.core.logger import setup_logger, log_function
from app.core.data_loader import DATA

# ── Phase 2 Services ──────────────────────────────────────────
from app.services.executive import (
    get_executive_kpis, get_revenue_profit_trend, get_revenue_by_channel,
    get_business_unit_efficiency, get_top_products, get_seasonality_heatmap
)
from app.services.sales import (
    get_sales_kpis, get_revenue_vs_profit_trend, get_revenue_by_product_family,
    get_discount_impact_analysis, get_growth_comparison, get_seasonality_by_family,
    get_top_bottom_margin_products
)
from app.services.customers import (
    get_customer_kpis, get_rfm_scatter, get_customer_segments,
    get_cohort_retention_heatmap, get_aov_distribution, get_new_vs_returning_trend,
    get_customer_geography
)
from app.services.channels import (
    get_channel_kpis, get_channel_comparison, get_channel_growth_trend,
    get_returns_by_channel, get_geographic_demand, get_channel_mix_evolution
)
from app.services.inventory import (
    get_inventory_kpis, get_abc_xyz_matrix, get_stock_turns,
    get_days_of_cover, get_stockout_overstock, get_demand_forecast
)

# ── Phase 3 Services ──────────────────────────────────────────
from app.services.marketing import (
    get_marketing_kpis, get_roas_by_platform, get_spend_vs_revenue,
    get_ctr_trend, get_budget_allocation, get_web_funnel, get_campaign_table
)
from app.services.production import (
    get_production_kpis, get_efficiency_by_line, get_plan_vs_actual,
    get_bottleneck_pareto, get_delay_distribution, get_overtime_trend,
    get_efficiency_trend
)
from app.services.quality import (
    get_quality_kpis, get_defect_pareto, get_root_cause_analysis,
    get_quality_by_stage, get_quality_loss_trend, get_return_reasons,
    get_quality_return_correlation
)
# ── Phase 4 Services ──────────────────────────────────────────
from app.services.supply_chain import (
    get_supply_chain_kpis, get_supplier_scorecard, get_lead_time_distribution,
    get_acceptance_rate, get_cost_trend, get_supplier_risk_matrix, get_material_criticality
)
from app.services.value_chain import (
    get_value_chain_kpis, get_product_journey_waterfall,
    get_true_profitability_leaderboard, get_hidden_cost_breakdown,
    get_cross_dept_anomalies, get_profitability_gap, get_product_list
)
# BI Report (self-contained orchestration layer over the services above)
from app.services.report import get_report_context, SCOPE_TAGS

from app.services.printing import (
    get_printing_kpis, get_machine_yield, get_defect_types,
    get_reprint_cost_trend, get_downtime_by_reason, get_planned_vs_unplanned,
    get_machine_utilization_heatmap
)

logger = setup_logger(__name__)
router = APIRouter(tags=["pages"])


# ── Task 5: Executive Command Center ────────────────────────
@router.get("/", response_class=HTMLResponse)
@log_function
async def executive_dashboard(request: Request):
    """Executive Command Center (Home Page)."""
    templates = request.app.state.templates
    kpis = get_executive_kpis(DATA)
    charts = [
        get_revenue_profit_trend(DATA),
        get_revenue_by_channel(DATA),
        get_business_unit_efficiency(DATA),
        get_top_products(DATA, n=10),
        get_seasonality_heatmap(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/executive.html", context={
        "request": request,
        "page_title": "Executive Command Center",
        "page_id": "executive",
        "kpis": kpis,
        "charts": charts,
    })


# ── Task 6: Sales & Profitability ───────────────────────────
@router.get("/sales", response_class=HTMLResponse)
@log_function
async def sales_page(request: Request):
    """Sales & Profitability."""
    templates = request.app.state.templates
    kpis = get_sales_kpis(DATA)
    charts = [
        get_revenue_vs_profit_trend(DATA),
        get_revenue_by_product_family(DATA),
        get_discount_impact_analysis(DATA),
        get_growth_comparison(DATA),
        get_seasonality_by_family(DATA),
        get_top_bottom_margin_products(DATA, n=10),
    ]
    return templates.TemplateResponse(request=request, name="pages/sales.html", context={
        "request": request,
        "page_title": "Sales & Profitability",
        "page_id": "sales",
        "kpis": kpis,
        "charts": charts,
    })


# ── Task 7: Customer 360 & Retention ────────────────────────
@router.get("/customers", response_class=HTMLResponse)
@log_function
async def customers_page(request: Request):
    """Customer 360 & Retention."""
    templates = request.app.state.templates
    kpis = get_customer_kpis(DATA)
    charts = [
        get_rfm_scatter(DATA),
        get_customer_segments(DATA),
        get_cohort_retention_heatmap(DATA),
        get_aov_distribution(DATA),
        get_new_vs_returning_trend(DATA),
        get_customer_geography(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/customers.html", context={
        "request": request,
        "page_title": "Customer 360°",
        "page_id": "customers",
        "kpis": kpis,
        "charts": charts,
    })


# ── Task 8: Branch & Channel Performance ────────────────────
@router.get("/channels", response_class=HTMLResponse)
@log_function
async def channels_page(request: Request):
    """Branch & Channel Performance."""
    templates = request.app.state.templates
    kpis = get_channel_kpis(DATA)
    charts = [
        get_channel_comparison(DATA),
        get_channel_growth_trend(DATA),
        get_returns_by_channel(DATA),
        get_geographic_demand(DATA),
        get_channel_mix_evolution(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/channels.html", context={
        "request": request,
        "page_title": "Branch & Channel Performance",
        "page_id": "channels",
        "kpis": kpis,
        "charts": charts,
    })


# ── Task 9: Inventory & Demand Planning ─────────────────────
@router.get("/inventory", response_class=HTMLResponse)
@log_function
async def inventory_page(request: Request):
    """Inventory & Demand Planning."""
    templates = request.app.state.templates
    kpis = get_inventory_kpis(DATA)
    charts = [
        get_abc_xyz_matrix(DATA),
        get_demand_forecast(DATA, horizons=[30, 60, 90]),
        get_stock_turns(DATA),
        get_days_of_cover(DATA),
        get_stockout_overstock(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/inventory.html", context={
        "request": request,
        "page_title": "Inventory & Demand Planning",
        "page_id": "inventory",
        "kpis": kpis,
        "charts": charts,
    })


# ── Task 10: Marketing Effectiveness ────────────────────────
@router.get("/marketing", response_class=HTMLResponse)
@log_function
async def marketing_page(request: Request):
    """Marketing Effectiveness."""
    templates = request.app.state.templates
    kpis = get_marketing_kpis(DATA)
    charts = [
        get_roas_by_platform(DATA),
        get_spend_vs_revenue(DATA),
        get_web_funnel(DATA),
        get_ctr_trend(DATA),
        get_budget_allocation(DATA),
    ]
    campaigns = get_campaign_table(DATA, n=15)
    return templates.TemplateResponse(request=request, name="pages/marketing.html", context={
        "request": request,
        "page_title": "Marketing Effectiveness",
        "page_id": "marketing",
        "kpis": kpis,
        "charts": charts,
        "campaigns": campaigns,
    })


# ── Task 11: Factory Production & Bottlenecks ───────────────
@router.get("/production", response_class=HTMLResponse)
@log_function
async def production_page(request: Request):
    """Factory Production & Bottlenecks."""
    templates = request.app.state.templates
    kpis = get_production_kpis(DATA)
    charts = [
        get_efficiency_by_line(DATA),
        get_plan_vs_actual(DATA),
        get_bottleneck_pareto(DATA),
        get_delay_distribution(DATA),
        get_overtime_trend(DATA),
        get_efficiency_trend(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/production.html", context={
        "request": request,
        "page_title": "Production & Bottlenecks",
        "page_id": "production",
        "kpis": kpis,
        "charts": charts,
    })


# ── Task 12: Quality, Returns & COPQ ────────────────────────
@router.get("/quality", response_class=HTMLResponse)
@log_function
async def quality_page(request: Request):
    """Quality, Returns & COPQ."""
    templates = request.app.state.templates
    kpis = get_quality_kpis(DATA)
    charts = [
        get_defect_pareto(DATA),
        get_root_cause_analysis(DATA),
        get_quality_by_stage(DATA),
        get_quality_loss_trend(DATA),
        get_return_reasons(DATA),
        get_quality_return_correlation(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/quality.html", context={
        "request": request,
        "page_title": "Quality & Returns",
        "page_id": "quality",
        "kpis": kpis,
        "charts": charts,
    })


# ── Task 13: Printing Performance & Downtime ────────────────
@router.get("/printing", response_class=HTMLResponse)
@log_function
async def printing_page(request: Request):
    """Printing Performance & Downtime."""
    templates = request.app.state.templates
    kpis = get_printing_kpis(DATA)
    charts = [
        get_machine_yield(DATA),
        get_defect_types(DATA),
        get_reprint_cost_trend(DATA),
        get_downtime_by_reason(DATA),
        get_planned_vs_unplanned(DATA),
        get_machine_utilization_heatmap(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/printing.html", context={
        "request": request,
        "page_title": "Printing Performance",
        "page_id": "printing",
        "kpis": kpis,
        "charts": charts,
    })


# ── Phase 4: Supply Chain & Materials (Task 14) ─────────────
@router.get("/supply-chain", response_class=HTMLResponse)
@log_function
async def supply_chain_page(request: Request):
    """Supply Chain & Materials."""
    templates = request.app.state.templates
    kpis = get_supply_chain_kpis(DATA)
    charts = [
        get_supplier_scorecard(DATA),
        get_supplier_risk_matrix(DATA),
        get_acceptance_rate(DATA),
        get_lead_time_distribution(DATA),
        get_cost_trend(DATA),
        get_material_criticality(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/supply_chain.html", context={
        "request": request,
        "page_title": "Supply Chain & Materials",
        "page_id": "supply_chain",
        "kpis": kpis,
        "charts": charts,
    })


# ── Phase 4: Value Chain Profitability (Task 15 - App 11) ──
@router.get("/value-chain", response_class=HTMLResponse)
@log_function
async def value_chain_page(request: Request, product_id: str | None = None):
    """Value Chain Profitability (Cross-Department)."""
    templates = request.app.state.templates
    kpis = get_value_chain_kpis(DATA)
    products = get_product_list(DATA)
    
    selected_product_id = product_id if (product_id and any(p["id"] == product_id for p in products)) else (products[0]["id"] if products else None)
    
    charts = [
        get_product_journey_waterfall(DATA, product_id=selected_product_id),
        get_true_profitability_leaderboard(DATA),
        get_hidden_cost_breakdown(DATA),
        get_cross_dept_anomalies(DATA),
        get_profitability_gap(DATA),
    ]
    return templates.TemplateResponse(request=request, name="pages/value_chain.html", context={
        "request": request,
        "page_title": "Value Chain Profit Analyzer",
        "page_id": "value_chain",
        "kpis": kpis,
        "charts": charts,
        "products": products,
        "selected_product_id": selected_product_id,
    })


# ── Phase 4: Business Intelligence Report ───
@router.get("/report", response_class=HTMLResponse)
@log_function
async def report_page(request: Request):
    """Data-driven BI report: findings, evidence, risks and recommendations."""
    templates = request.app.state.templates
    ctx = get_report_context(DATA)
    return templates.TemplateResponse(request=request, name="pages/report.html", context={
        "request": request,
        "page_title": "Business Intelligence Report",
        "page_id": "report",
        "ctx": ctx,
        "scope_tags": SCOPE_TAGS,
    })
