"""
Pydantic response schemas used by all services.
These models define the contract between services and the presentation layer.
"""
from pydantic import BaseModel, Field
from typing import Any, Optional
from app.core.logger import setup_logger

logger = setup_logger(__name__)


class KPICard(BaseModel):
    """A single KPI card displayed at the top of dashboard pages."""
    title: str = Field(..., description="Arabic label for the KPI")
    value: str = Field(..., description="Formatted display value (e.g., '12.5M EGP')")
    raw_value: float = Field(0, description="Raw numeric value for calculations")
    delta: Optional[float] = Field(None, description="Percentage change (positive = growth)")
    delta_label: Optional[str] = Field(None, description="Label for the delta (e.g., 'vs prior year')")
    icon: str = Field("", description="Unused (kept for API compatibility); UI renders no icons")
    color: str = Field("neutral", description="Unused (kept for API compatibility); cards are uniform")
    favorable: Optional[bool] = Field(
        None,
        description="Business meaning of the delta: True = increase is good, "
        "False = increase is bad. None = infer from the sign of delta.",
    )
    neutral_delta: bool = Field(
        False,
        description="True = the delta is informational (neither good nor bad); "
        "it is rendered in neutral gray instead of red/green.",
    )


class ChartData(BaseModel):
    """Wrapper for a Plotly chart to be rendered in a template."""
    chart_id: str = Field(..., description="Unique HTML id for the chart container")
    title: str = Field(..., description="Arabic chart title")
    chart_json: str = Field(..., description="Plotly figure JSON string")
    height: int = Field(400, description="Chart height in pixels")
    description: Optional[str] = Field(None, description="Optional Arabic description below the chart")


class TableData(BaseModel):
    """Data for rendering an HTML table."""
    table_id: str = Field(..., description="Unique HTML id for the table")
    title: str = Field(..., description="Arabic table title")
    headers: list[str] = Field(..., description="Column header labels in Arabic")
    rows: list[list[Any]] = Field(..., description="Row data")


class PageContext(BaseModel):
    """Full context passed to a Jinja2 page template."""
    page_title: str = Field(..., description="Page title in Arabic")
    page_id: str = Field(..., description="Unique page identifier for sidebar active state")
    kpis: list[KPICard] = Field(default_factory=list)
    charts: list[ChartData] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict, description="Additional page-specific data")
