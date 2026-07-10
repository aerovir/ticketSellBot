#!/usr/bin/env python3
"""
Entry point для Telegram бота.

Использование:
    python -m bot.telegram
"""
import asyncio
import logging

from app.config import settings
from app.core.database import init_db, close_db

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
