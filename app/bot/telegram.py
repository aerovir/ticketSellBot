#!/usr/bin/env python3
"""
Entry point для Telegram бота.

Использование:
    python -m bot.telegram
"""
import asyncio

from app.config import settings
from app.core.database import init_db, close_db
from app.core.logging_config import setup_logging

logger = setup_logging(
    "ticketbot.telegram",
    extra_fields={"platform": "telegram"},
    debug=settings.debug,
)


async def main():
    logger.info("Инициализация базы данных...")
    await init_db()

    if not settings.telegram_token:
        logger.error("TELEGRAM_TOKEN не указан. Запуск невозможен.")
        return

    from app.platforms.telegram.bot import TelegramBot

    bot = TelegramBot()
    logger.info("✅ Telegram бот запущен")

    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки...")
    finally:
        await bot.stop()
        await close_db()
        logger.info("Telegram бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
