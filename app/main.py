"""
El-Sharnouby Group - FastAPI Application Factory
Main entry point with lifespan events, middleware, and router mounting.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.settings import settings
from app.core.data_loader import load_all_data, DATA
from app.core.logger import setup_logger, log_function

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load all CSV data. Shutdown: cleanup."""
    logger.info("=" * 60)
    logger.info("🚀 Starting El-Sharnouby BI Platform")
    logger.info("=" * 60)

    # Load all CSV data into global DATA dict
    loaded = load_all_data(settings.DATA_DIR)
    DATA.update(loaded)
    logger.info(f"✓ {len(DATA)} datasets loaded and ready")

    yield  # App is running

    # Shutdown
    DATA.clear()
    logger.info("👋 El-Sharnouby BI Platform shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_TITLE,
        description="Business intelligence and AI platform for El-Sharnouby Group",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware (for future chatbot integration) — localhost origins only
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    app.mount(
        "/static",
        StaticFiles(directory=str(settings.STATIC_DIR)),
        name="static",
    )

    # Setup Jinja2 templates
    templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))
    app.state.templates = templates

    # Include routers
    from app.api.pages import router as pages_router
    from app.api.rest import router as rest_router

    app.include_router(pages_router)
    app.include_router(rest_router, prefix="/api/v1")

    logger.info("✓ Application configured successfully")
    return app


app = create_app()
