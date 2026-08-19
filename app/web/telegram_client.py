"""Общий доступ к Telegram Bot из web-контейнера.

Web-контейнер использует тот же TELEGRAM_TOKEN (env_file: .env.telegram),
что и telegram-бот, поэтому может ходить в Telegram API напрямую:
анонсы (announce.py) и скачивание постеров мероприятий (routes.py).
"""
import logging

from aiogram import Bot

from app.config import settings

logger = logging.getLogger("ticketbot.web.telegram_client")

_bot: Bot | None = None


def get_telegram_bot() -> Bot | None:
    """Lazily create a Bot from settings; None if no token configured."""
    global _bot
    if not settings.telegram_token:
        logger.warning("TELEGRAM_TOKEN не настроен — Telegram API недоступен из web")
        return None
    if _bot is None:
        _bot = Bot(token=settings.telegram_token)
    return _bot
