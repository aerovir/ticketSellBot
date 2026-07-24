#!/usr/bin/env python3
"""
Entry point для MAX бота (заглушка).

Использование:
    python -m bot.max
"""
import asyncio

from app.config import settings
from app.core.database import init_db, close_db
from app.core.logging_config import setup_logging

logger = setup_logging(
    "ticketbot.max",
    extra_fields={"platform": "max"},
    debug=settings.debug,
)


async def main():
    logger.info("Инициализация базы данных...")
    await init_db()

    if not settings.max_token:
        logger.error("MAX_TOKEN не указан. Запуск невозможен.")
        return

    from app.platforms.max.bot import MaxPlatformBot

    bot = MaxPlatformBot()
    logger.info("✅ MAX бот запущен")

    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки...")
    finally:
        await bot.stop()
        await close_db()
        logger.info("MAX бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
