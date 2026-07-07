"""
TicketBot — кроссплатформенный бот для продажи билетов.

Поддерживаемые платформы:
- Telegram (aiogram 3.x)
- VK (vkbottle)
- MAX / max.ru (max-bot-api-client-py) — заглушка

Запуск всех доступных ботов:
    python main.py

Запуск конкретной платформы:
    python run_telegram.py
    python run_vk.py
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
logger = logging.getLogger("ticketbot")


async def main():
    logger.info("Инициализация базы данных...")
    await init_db()
    logger.info("База данных готова.")

    bots = []

    # Telegram
    if settings.telegram_token:
        try:
            from platforms.telegram.bot import TelegramBot

            tg_bot = TelegramBot()
            bots.append(("Telegram", tg_bot))
            logger.info("Telegram бот зарегистрирован")
        except (ImportError, ValueError) as e:
            logger.warning("Telegram бот не запущен: %s", e)
    else:
        logger.info("Telegram бот пропущен: токен не указан")

    # VK — закомментирован (запускать через run_vk.py)
    # if settings.vk_token and settings.vk_group_id:
    #     try:
    #         from platforms.vk.bot import VKPlatformBot
    #         vk_bot = VKPlatformBot()
    #         bots.append(("VK", vk_bot))
    #         logger.info("VK бот зарегистрирован")
    #     except (ImportError, ValueError) as e:
    #         logger.warning("VK бот не запущен: %s", e)
    # else:
    #     logger.info("VK бот пропущен: токен не указан")

    # MAX — закомментирован (запускать через run_max.py)
    # if settings.max_token:
    #     try:
    #         from platforms.max.bot import MaxPlatformBot
    #         max_bot = MaxPlatformBot()
    #         bots.append(("MAX", max_bot))
    #         logger.info("MAX бот зарегистрирован")
    #     except (ImportError, ValueError) as e:
    #         logger.warning("MAX бот не запущен: %s", e)
    # else:
    #     logger.info("MAX бот пропущен: токен не указан")

    if not bots:
        logger.warning("Нет запущенных ботов. Укажите хотя бы один токен в .env")
        return

    logger.info(
        "Запущено ботов: %d (%s)", len(bots), ", ".join(name for name, _ in bots)
    )

    try:
        await asyncio.gather(*[bot.run() for _, bot in bots])
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки...")
    finally:
        for name, bot in bots:
            await bot.stop()
        await close_db()
        logger.info("Все боты остановлены.")


if __name__ == "__main__":
    asyncio.run(main())
