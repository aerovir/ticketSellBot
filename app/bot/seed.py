"""
Seed script — заполняет БД тестовыми мероприятиями.

Использование:
    python seed.py
"""

import asyncio
from datetime import datetime, timezone, timedelta

from app.core.database import async_session_factory, init_db, close_db
from app.core.models import Event, Channel
from app.core.logging_config import setup_logging

logger = setup_logging("seed", debug=False)


async def seed():
    await init_db()

    async with async_session_factory() as session:
        from sqlalchemy import select, func

        # Check if already seeded
        result = await session.execute(select(func.count(Event.id)))
        count = result.scalar()
        if count and count > 0:
            logger.info("В базе уже есть %d мероприятий, пропускаем сидирование.", count)
            return

        # Create or find a default channel (skip if channels already exist from migration)
        result = await session.execute(select(func.count(Channel.id)))
        channel_count = result.scalar()
        if channel_count and channel_count > 0:
            # Use the first existing channel
            result = await session.execute(select(Channel).limit(1))
            default_channel = result.scalar_one()
        else:
            # Create a seed channel
            default_channel = Channel(
                telegram_channel_id="__seed__",
                title="Seed Events Channel",
                admin_telegram_user_id="0",
                is_subscription_active=True,
            )
            session.add(default_channel)
            await session.flush()
            logger.info("📢 Создан seed-канал: %s", default_channel.id)

        now = datetime.now(timezone.utc)
        events = [
            Event(
                title="Концерт 'Рок-хиты'",
                description="Грандиозный концерт с лучшими рок-хитами в исполнении симфонического оркестра.",
                date=now + timedelta(days=14),
                location="Москва, Крокус Сити Холл",
                price=2500.0,
                total_tickets=500,
                available_tickets=500,
                is_active=True,
                is_published=True,
                channel_id=default_channel.id,
            ),
            Event(
                title="Stand-up вечер",
                description="Вечер юмора с лучшими комиками страны. Гарантированный смех до слёз!",
                date=now + timedelta(days=7),
                location="Санкт-Петербург, ДК им. Ленсовета",
                price=1500.0,
                total_tickets=200,
                available_tickets=200,
                is_active=True,
                is_published=True,
                channel_id=default_channel.id,
            ),
            Event(
                title="Театральная премьера: 'Гамлет'",
                description="Новая постановка классической трагедии Шекспира. Режиссёр — народный артист РФ.",
                date=now + timedelta(days=21),
                location="Казань, Театр им. Камала",
                price=1800.0,
                total_tickets=300,
                available_tickets=300,
                is_active=True,
                is_published=True,
                channel_id=default_channel.id,
            ),
            Event(
                title="Фестиваль электронной музыки",
                description="Двухдневный фестиваль с участием топовых диджеев со всего мира.",
                date=now + timedelta(days=30),
                location="Екатеринбург, Екатеринбург-Экспо",
                price=3500.0,
                total_tickets=1000,
                available_tickets=1000,
                is_active=True,
                is_published=True,
                channel_id=default_channel.id,
            ),
            Event(
                title="Мастер-класс по фотографии",
                description="Практический семинар от известного фотографа. Научитесь снимать как профессионал!",
                date=now + timedelta(days=5),
                location="Москва, Лофт 'Среда'",
                price=2000.0,
                total_tickets=50,
                available_tickets=50,
                is_active=True,
                is_published=True,
                channel_id=default_channel.id,
            ),
            Event(
                title="Спектакль 'Три сестры'",
                description="Классическая постановка по пьесе А.П. Чехова. Продолжительность: 2 часа 30 минут.",
                date=now + timedelta(days=45),
                location="Новосибирск, Театр 'Красный факел'",
                price=1200.0,
                total_tickets=400,
                available_tickets=400,
                is_active=True,
                is_published=True,
                channel_id=default_channel.id,
            ),
        ]

        for event in events:
            session.add(event)

        await session.commit()
        logger.info("✅ Добавлено %d тестовых мероприятий!", len(events))

        # Отправляем анонсы в Telegram канал (если настроен)
        app_settings = __import__("app.config", fromlist=["settings"]).settings
        if app_settings.telegram_token and not default_channel.telegram_channel_id.startswith("__"):
            try:
                from aiogram import Bot as AiogramBot
                from app.platforms.telegram.channel import ChannelManager

                bot = AiogramBot(token=app_settings.telegram_token)
                channel_mgr = ChannelManager(bot)
                for event in events:
                    await channel_mgr.post_event_announcement(event, default_channel.telegram_channel_id)
                await bot.session.close()
                logger.info("📢 Анонсы отправлены в Telegram канал")
            except Exception as e:
                logger.warning("Не удалось отправить анонсы: %s", e)
        else:
            logger.info("📢 Канал не настроен или используется seed-канал, пропускаем отправку анонсов")


if __name__ == "__main__":
    asyncio.run(seed())
