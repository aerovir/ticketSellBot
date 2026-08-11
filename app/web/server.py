"""
FastAPI application for Telegram Mini App and VK Mini App.

Serves static frontend files and provides REST API
for event browsing and ticket purchasing.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.database import init_db, close_db
from app.web.rate_limit import RateLimitMiddleware
from app.web.routes import router
from prometheus_fastapi_instrumentator import Instrumentator

logger = logging.getLogger("ticketbot.web")

STATIC_DIR = Path("app/web/static")


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
        title="TicketBot API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — allow Telegram Mini App, VK Mini App and public domain
    origins = ["*"] if settings.debug else [
        settings.webapp_url,
        "https://pochtibot.online",
        "https://vk.com",
        "https://api.vk.com",
    ] if settings.webapp_url else [
        "https://pochtibot.online",
        "https://vk.com",
        "https://api.vk.com",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Per-IP rate limiting (защита от brute-force/скрейпинга). Whitelist: /health,/metrics,/static.
    app.add_middleware(RateLimitMiddleware)

    # Mount static files (Telegram Mini App frontend) — no cache для обновлений
    import starlette.types
    class NoCacheStaticFiles(StaticFiles):
        async def __call__(self, scope, receive, send):
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = dict(message.get("headers", []))
                    headers[b"cache-control"] = b"no-cache, no-store, must-revalidate"
                    message["headers"] = list(headers.items())
                await send(message)
            await super().__call__(scope, receive, send_wrapper)
    app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")

    # VK Mini App entry point
    vk_app_html = STATIC_DIR / "vk-app.html"

    @app.get("/vk-app")
    async def vk_app():
        return FileResponse(vk_app_html)

    @app.get("/vk-app/{rest:path}")
    async def vk_app_fallback(rest: str):
        # Все пути внутри VK Mini App ведут на главную страницу (SPA-like)
        return FileResponse(vk_app_html)

    # Include API routes
    app.include_router(router, prefix="/api")

    # Prometheus metrics endpoint: /metrics
    Instrumentator().instrument(app).expose(app)

    # Root serves the Telegram Mini App directly.
    # НЕ используем редирект: Telegram передаёт initData только когда
    # страница открывается напрямую (без 30x), иначе контекст WebApp теряется.
    @app.get("/")
    async def root():
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
