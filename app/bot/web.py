"""
Entry point for the Web (FastAPI) server.

Usage:
    python -m bot.web

Reads settings from .env / environment variables (web_host, web_port).
"""

import asyncio

import uvicorn

from app.config import settings
from app.core.logging_config import setup_logging

logger = setup_logging(
    "ticketbot.web",
    extra_fields={"platform": "web"},
    debug=settings.debug,
)


def main():
    host = settings.web_host
    port = settings.web_port

    logger.info("Starting Web server on %s:%s", host, port)

    uvicorn.run(
        "app.web.server:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
