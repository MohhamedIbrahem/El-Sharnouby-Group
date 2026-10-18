"""
El-Sharnouby Group - Application Settings
Pydantic BaseSettings for centralized configuration.
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env file."""

    # --- Application ---
    APP_TITLE: str = "El-Sharnouby Group - Business Intelligence Platform"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # --- Paths ---
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path(__file__).resolve().parent.parent / "Sharnouby_Enterprise"
    TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"
    STATIC_DIR: Path = Path(__file__).resolve().parent / "static"

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --- Future: AI/RAG ---
    # LLM_API_KEY: str = ""
    # VECTOR_DB_PATH: Path = Path("data/vectordb")

    # --- Plotly Chart Colors ---
    # Enterprise palette: deep navy primary + orange accent. Green and red
    # are reserved for meaningful financial status and are applied by
    # services via ACCENT_GREEN / ACCENT_RED, not via the categorical palette.
    CHART_COLORS: list[str] = [
        "#17324D",  # Deep navy (primary series)
        "#F97316",  # Orange accent (secondary category)
        "#16A34A",  # Green (financial favorable)
        "#DC2626",  # Red (financial unfavorable)
        "#64748B",  # Slate (tertiary / totals)
        "#8B5CF6",  # Violet (distinct category, sparing)
        "#0891B2",  # Cyan (categorical differentiation)
        "#5B7DA6",  # Light navy (navy family)
        "#FDBA74",  # Light orange (orange family)
        "#9CA3AF",  # Light slate (neutral series)
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
