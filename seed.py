"""
Seed script — заполняет БД тестовыми мероприятиями.

Использование:
    python seed.py
"""

import asyncio
import logging
from datetime import datetime, timedelta

from core.database import async_session_factory, init_db, close_db
from core.models import Event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")


async def seed():
    await init_db()

    async with async_session_factory() as session:
        # Check if already seeded
        from sqlalchemy import select, func
        result = await session.execute(select(func.count(Event.id)))
        count = result.scalar()
        if count and count > 0:
            logger.info("В базе уже есть %d мероприятий, пропускаем сидирование.", count)
            return

        now = datetime.utcnow()
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
            ),
        ]

        for event in events:
            session.add(event)

        await session.flush()
        logger.info("✅ Добавлено %d тестовых мероприятий!", len(events))


if __name__ == "__main__":
    asyncio.run(seed())
