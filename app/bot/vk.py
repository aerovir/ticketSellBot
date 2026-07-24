#!/usr/bin/env python3
"""
Entry point для VK бота.

Использование:
    python -m bot.vk
"""
import asyncio

from app.config import settings
from app.core.database import init_db, close_db
from app.core.logging_config import setup_logging

logger = setup_logging(
    "ticketbot.vk",
    extra_fields={"platform": "vk"},
    debug=settings.debug,
)


async def main():
    logger.info("Инициализация базы данных...")
    await init_db()

    if not settings.vk_token or not settings.vk_group_id:
        logger.error("VK_TOKEN или VK_GROUP_ID не указаны. Запуск невозможен.")
        return

    from app.platforms.vk.bot import VKPlatformBot

    bot = VKPlatformBot()
    logger.info("✅ VK бот запущен")

    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки...")
    finally:
        await bot.stop()
        await close_db()
        logger.info("VK бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
