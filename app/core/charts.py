"""
Shared Charting Engine — Generates interactive, RTL-optimized Plotly figures
matching the El-Sharnouby Platform Design System.
"""
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from typing import Optional, Any
from app.core.models import ChartData
from app.settings import settings

PRIMARY = "#17324D"          # Deep navy — primary series
SECONDARY = "#F97316"        # Orange accent — meaningful second series
DARK = "#64748B"             # Slate — totals / tertiary emphasis
LIGHT_PRIMARY = "#5B7DA6"    # Light navy — navy-family secondary step
LIGHT_SECONDARY = "#FDBA74"  # Light orange — orange-family secondary step
ACCENT_RED = "#DC2626"       # Financial: unfavorable
ACCENT_GREEN = "#16A34A"     # Financial: favorable
ACCENT_BLUE = "#0891B2"      # Cyan — categorical differentiation

# Backwards-compatible names (old orange/teal scheme). All services import
# these; the values now resolve into the navy/orange enterprise palette.
PRIMARY_ORANGE = PRIMARY
SECONDARY_TEAL = SECONDARY
DARK_NAVY = DARK
LIGHT_ORANGE = LIGHT_PRIMARY
LIGHT_TEAL = LIGHT_SECONDARY

PALETTE = settings.CHART_COLORS

def get_base_layout(title: str = "", height: int = 400) -> dict:
    """Returns standard Plotly layout options matching the platform theme."""
    return dict(
        title=dict(
            text=title,
            font=dict(family="Inter, IBM Plex Sans Arabic, sans-serif", size=15, color="#1F2937", weight="bold"),
            x=0.01,
            xanchor="left",
            y=0.95,
        ) if title else None,
        font=dict(family="Inter, IBM Plex Sans Arabic, sans-serif", size=12, color="#6B7280"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=45, r=45, t=50 if title else 25, b=45),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=12, color="#64748B")
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(229, 231, 235, 0.8)",
            zerolinecolor="rgba(209, 213, 219, 0.8)",
            tickfont=dict(color="#6B7280", size=11),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(229, 231, 235, 0.8)",
            zerolinecolor="rgba(209, 213, 219, 0.8)",
            tickfont=dict(color="#6B7280", size=11),
        ),
        hoverlabel=dict(
            bgcolor="#17324D",
            font_size=12,
            font_family="Inter, IBM Plex Sans Arabic, sans-serif",
            font_color="#f8fafc",
        )
    )

def create_chart_data(fig: go.Figure, chart_id: str, title: str, height: int = 400, description: str = "") -> ChartData:
    """Helper to package a Plotly figure into the ChartData model."""
    base_opts = get_base_layout(height=height)
    fig.update_layout(**base_opts)
    return ChartData(
        chart_id=chart_id,
        title=title,
        chart_json=fig.to_json(),
        height=height,
        description=description,
    )

def format_currency_ar(val: float) -> str:
    """Format numbers to Egyptian Pounds with M/K suffixes."""
    if val is None or pd.isna(val):
        return "0 EGP"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1_000_000_000:
        return f"{sign}{abs_val / 1_000_000_000:.1f}B EGP"
    elif abs_val >= 1_000_000:
        return f"{sign}{abs_val / 1_000_000:.1f}M EGP"
    elif abs_val >= 1_000:
        return f"{sign}{abs_val / 1_000:.1f}K EGP"
    return f"{sign}{abs_val:,.0f} EGP"

def format_number_ar(val: float) -> str:
    """Format generic counts."""
    if val is None or pd.isna(val):
        return "0"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1_000_000:
        return f"{sign}{abs_val / 1_000_000:.1f}M"
    elif abs_val >= 1_000:
        return f"{sign}{abs_val / 1_000:.1f}K"
    return f"{sign}{abs_val:,.0f}"
