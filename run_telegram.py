#!/usr/bin/env python3
"""
Entry point для Telegram бота.

Использование:
    python run_telegram.py
"""
import asyncio
import logging

from config import settings
from core.database import init_db, close_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ticketbot.telegram")


async def main():
    logger.info("Инициализация базы данных...")
    await init_db()

    if not settings.telegram_token:
        logger.error("TELEGRAM_TOKEN не указан. Запуск невозможен.")
        return

    from platforms.telegram.bot import TelegramBot

    bot = TelegramBot()
    logger.info("Telegram бот запущен")
    await bot.run()

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
