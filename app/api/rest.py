"""
REST API Router — JSON endpoints for programmatic access and future chatbot/RAG agents.
(Task 16 - REST API Endpoints)
"""
from fastapi import APIRouter, HTTPException, Path

from app.core.data_loader import DATA
from app.core.models import KPICard, ChartData
from app.core.logger import setup_logger, log_function

# Phase 2 Services
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

# Phase 3 Services
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
from app.services.printing import (
    get_printing_kpis, get_machine_yield, get_defect_types,
    get_reprint_cost_trend, get_downtime_by_reason, get_planned_vs_unplanned,
    get_machine_utilization_heatmap
)

# Phase 4 Services
from app.services.supply_chain import (
    get_supply_chain_kpis, get_supplier_scorecard, get_lead_time_distribution,
    get_acceptance_rate, get_cost_trend, get_supplier_risk_matrix, get_material_criticality
)
from app.services.value_chain import (
    get_value_chain_kpis, get_product_journey_waterfall,
    get_true_profitability_leaderboard, get_hidden_cost_breakdown,
    get_cross_dept_anomalies, get_profitability_gap, get_product_list
)

logger = setup_logger(__name__)
router = APIRouter(tags=["api"])


# ── Health ────────────────────────────────────────────────────
@router.get("/health")
@log_function
async def health_check():
    """Health check endpoint returning data loading status."""
    return {
        "status": "ok",
        "tables_loaded": len(DATA),
        "tables": list(DATA.keys()),
    }


# ── Executive ─────────────────────────────────────────────────
@router.get("/executive/kpis", response_model=list[KPICard])
@log_function
async def api_executive_kpis():
    """Returns Executive KPIs."""
    return get_executive_kpis(DATA)


@router.get("/executive/charts/{chart_name}", response_model=ChartData)
@log_function
async def api_executive_chart(chart_name: str = Path(..., description="Chart identifier: revenue_profit, channels, bu_efficiency, top_products, seasonality")):
    """Returns a specific Executive chart."""
    chart_map = {
        "revenue_profit": get_revenue_profit_trend,
        "channels": get_revenue_by_channel,
        "bu_efficiency": get_business_unit_efficiency,
        "top_products": get_top_products,
        "seasonality": get_seasonality_heatmap,
    }
    if chart_name not in chart_map:
        raise HTTPException(status_code=404, detail=f"Chart '{chart_name}' not found. Available: {list(chart_map.keys())}")
    return chart_map[chart_name](DATA)


# ── Sales ─────────────────────────────────────────────────────
@router.get("/sales/kpis", response_model=list[KPICard])
@log_function
async def api_sales_kpis():
    """Returns Sales KPIs."""
    return get_sales_kpis(DATA)


@router.get("/sales/charts/{chart_name}", response_model=ChartData)
@log_function
async def api_sales_chart(chart_name: str = Path(..., description="Chart identifier: trend, family, discount, growth, seasonality, margin")):
    """Returns a specific Sales chart."""
    chart_map = {
        "trend": get_revenue_vs_profit_trend,
        "family": get_revenue_by_product_family,
        "discount": get_discount_impact_analysis,
        "growth": get_growth_comparison,
        "seasonality": get_seasonality_by_family,
        "margin": get_top_bottom_margin_products,
    }
    if chart_name not in chart_map:
        raise HTTPException(status_code=404, detail=f"Chart '{chart_name}' not found. Available: {list(chart_map.keys())}")
    return chart_map[chart_name](DATA)


# ── Customers ─────────────────────────────────────────────────
@router.get("/customers/kpis", response_model=list[KPICard])
@log_function
async def api_customers_kpis():
    """Returns Customer 360 KPIs."""
    return get_customer_kpis(DATA)


@router.get("/customers/segments", response_model=ChartData)
@log_function
async def api_customers_segments():
    """Returns AI K-Means Customer Segments chart."""
    return get_customer_segments(DATA)


# ── Channels ──────────────────────────────────────────────────
@router.get("/channels/kpis", response_model=list[KPICard])
@log_function
async def api_channels_kpis():
    """Returns Channel KPIs."""
    return get_channel_kpis(DATA)


# ── Inventory ─────────────────────────────────────────────────
@router.get("/inventory/kpis", response_model=list[KPICard])
@log_function
async def api_inventory_kpis():
    """Returns Inventory KPIs."""
    return get_inventory_kpis(DATA)


@router.get("/inventory/forecast", response_model=ChartData)
@log_function
async def api_inventory_forecast():
    """Returns 30/60/90-day AI Demand Forecast chart."""
    return get_demand_forecast(DATA, horizons=[30, 60, 90])


# ── Marketing ─────────────────────────────────────────────────
@router.get("/marketing/kpis", response_model=list[KPICard])
@log_function
async def api_marketing_kpis():
    """Returns Marketing KPIs."""
    return get_marketing_kpis(DATA)


# ── Production ────────────────────────────────────────────────
@router.get("/production/kpis", response_model=list[KPICard])
@log_function
async def api_production_kpis():
    """Returns Production KPIs."""
    return get_production_kpis(DATA)


# ── Quality ───────────────────────────────────────────────────
@router.get("/quality/kpis", response_model=list[KPICard])
@log_function
async def api_quality_kpis():
    """Returns Quality KPIs."""
    return get_quality_kpis(DATA)


# ── Printing ──────────────────────────────────────────────────
@router.get("/printing/kpis", response_model=list[KPICard])
@log_function
async def api_printing_kpis():
    """Returns Printing KPIs."""
    return get_printing_kpis(DATA)


# ── Supply Chain ──────────────────────────────────────────────
@router.get("/supply-chain/kpis", response_model=list[KPICard])
@log_function
async def api_supply_chain_kpis():
    """Returns Supply Chain KPIs."""
    return get_supply_chain_kpis(DATA)


@router.get("/supply-chain/charts/{chart_name}", response_model=ChartData)
@log_function
async def api_supply_chain_chart(chart_name: str = Path(..., description="Chart identifier: scorecard, risk_matrix, acceptance, lead_time, cost_trend, criticality")):
    """Returns a specific Supply Chain chart."""
    chart_map = {
        "scorecard": get_supplier_scorecard,
        "risk_matrix": get_supplier_risk_matrix,
        "acceptance": get_acceptance_rate,
        "lead_time": get_lead_time_distribution,
        "cost_trend": get_cost_trend,
        "criticality": get_material_criticality,
    }
    if chart_name not in chart_map:
        raise HTTPException(status_code=404, detail=f"Chart '{chart_name}' not found. Available: {list(chart_map.keys())}")
    return chart_map[chart_name](DATA)


# ── Value Chain ───────────────────────────────────────────────
@router.get("/value-chain/kpis", response_model=list[KPICard])
@log_function
async def api_value_chain_kpis():
    """Returns Value Chain Profitability KPIs."""
    return get_value_chain_kpis(DATA)


@router.get("/value-chain/product/{product_id}", response_model=ChartData)
@log_function
async def api_value_chain_product(product_id: str = Path(..., description="Product ID, e.g. P001, P037")):
    """Returns Waterfall cost and margin journey for a specific product."""
    return get_product_journey_waterfall(DATA, product_id=product_id)


@router.get("/value-chain/charts/{chart_name}", response_model=ChartData)
@log_function
async def api_value_chain_chart(chart_name: str = Path(..., description="Chart identifier: leaderboard, hidden_costs, anomalies, gap")):
    """Returns a specific Value Chain chart."""
    chart_map = {
        "leaderboard": get_true_profitability_leaderboard,
        "hidden_costs": get_hidden_cost_breakdown,
        "anomalies": get_cross_dept_anomalies,
        "gap": get_profitability_gap,
    }
    if chart_name not in chart_map:
        raise HTTPException(status_code=404, detail=f"Chart '{chart_name}' not found. Available: {list(chart_map.keys())}")
    return chart_map[chart_name](DATA)
