#!/usr/bin/env python3
"""
Entry point для VK бота.

Использование:
    python -m bot.vk
"""
import asyncio
import logging

from app.config import settings
from app.core.database import init_db, close_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ticketbot.vk")


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
