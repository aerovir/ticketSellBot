#!/usr/bin/env python3
"""
Entry point для MAX бота (заглушка).

Использование:
    python run_max.py
"""
import asyncio
import logging

from config import settings
from core.database import init_db, close_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ticketbot.max")


async def main():
    logger.info("Инициализация базы данных...")
    await init_db()

    if not settings.max_token:
        logger.error("MAX_TOKEN не указан. Запуск невозможен.")
        return

    from platforms.max.bot import MaxPlatformBot

    bot = MaxPlatformBot()
    logger.info("MAX бот запущен")
    await bot.run()

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
