"""
FastAPI application for Telegram Mini App.

Serves static frontend files and provides REST API
for event browsing and ticket purchasing.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.database import init_db, close_db
from app.web.routes import router

logger = logging.getLogger("ticketbot.web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Web server starting up...")
    await init_db()
    logger.info("Database initialized")
    yield
    logger.info("Web server shutting down...")
    await close_db()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="TicketBot Mini App",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — allow the Telegram Mini App origin
    origins = ["*"] if settings.debug else [settings.webapp_url] if settings.webapp_url else []

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files (Mini App frontend)
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

    # Include API routes
    app.include_router(router, prefix="/api")

    # Root redirects to static index.html
    @app.get("/")
    async def root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/static/index.html")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
