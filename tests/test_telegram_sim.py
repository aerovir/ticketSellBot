"""
Имитация поведения пользователя в Telegram (Подход A — внутренний харнесс).

Гоняет полный конвейер бота через Dispatcher.feed_update с фейк-сессией,
которая перехватывает исходящие вызовы Telegram API (без реального Telegram).

Сценарий: виртуальный пользователь шлёт /start buy_<event_id> → бот
обрабатывает через реальные фильтры/FSM/хендлеры → покупает билет в БД →
отвечает в Telegram (перехвачено фейк-сессией).
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from aiogram import Bot
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.models import SubscriptionTier, Ticket
from app.core.services import ChannelService, EventService, TicketService

from tests.harness import (
    FakeTelegramSession,
    make_message_update,
)


def _make_session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def _clean_db(sf):
    """Очистить тестовые таблицы после сценария."""
    async with sf() as s:
        await s.execute(text("DELETE FROM payments"))
        await s.execute(text("DELETE FROM tickets"))
        await s.execute(text("DELETE FROM events"))
        await s.execute(text("DELETE FROM channel_admins"))
        await s.execute(text("DELETE FROM channels"))
        await s.execute(text("DELETE FROM users"))
        await s.commit()


@pytest.mark.integration
class TestTelegramSimulation:
    """Симуляция пользователя через полный конвейер бота."""

    async def test_user_buys_ticket_via_full_pipeline(self, test_engine):
        sf = _make_session_factory(test_engine)

        # ── Подготовка данных (канал pro + мероприятие) ──
        async with sf() as s:
            channel_svc = ChannelService(s)
            channel = await channel_svc.create("@sim_chan", "", "Sim Channel")
            channel = await channel_svc.activate_subscription(
                channel.id, duration_days=365, tier=SubscriptionTier.pro,
            )
            event_svc = EventService(s)
            event = await event_svc.create(
                title="Sim Event",
                description=None,
                date=datetime.now(timezone.utc) + timedelta(days=7),
                location=None,
                price=500.0,
                total_tickets=10,
                channel_id=channel.id,
            )
            event.is_published = True
            await s.commit()
            event_id = event.id

        try:
            # ── Бот с фейк-сессией ──
            fake = FakeTelegramSession()
            bot = Bot(token="123456789:TESTTOKEN", session=fake)

            import app.platforms.telegram.bot as _bot_mod
            with (
                patch.object(_bot_mod.settings, "telegram_token", "123456789:TESTTOKEN"),
                patch.object(_bot_mod, "Bot", lambda token, **kw: bot),
                patch.object(_bot_mod, "async_session_factory", sf),
            ):
                from app.platforms.telegram.bot import TelegramBot
                tb = TelegramBot()

                # ── Пользователь шлёт /start buy_<event_id> ──
                update = make_message_update(
                    user_id=12345,
                    text=f"/start buy_{event_id}",
                    bot=bot,
                )
                await tb.dp.feed_update(bot, update)

            # ── Проверки ──
            # бот ответил в Telegram (перехвачено)
            sent = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert len(sent) >= 1, f"Бот не ответил. Вызовы: {[c.__class__.__name__ for c in fake.calls]}"
            assert "Билет куплен" in sent[0].text

            # билет создан в БД
            async with sf() as s:
                tickets = (await s.execute(select(Ticket))).scalars().all()
            assert len(tickets) == 1
            assert tickets[0].event_id == event_id
            assert tickets[0].validation_code is not None
        finally:
            await _clean_db(sf)

    async def test_user_start_welcome(self, test_engine):
        """Простое /start без payload → приветствие в Telegram."""
        sf = _make_session_factory(test_engine)

        try:
            fake = FakeTelegramSession()
            bot = Bot(token="123456789:TESTTOKEN", session=fake)

            import app.platforms.telegram.bot as _bot_mod
            with (
                patch.object(_bot_mod.settings, "telegram_token", "123456789:TESTTOKEN"),
                patch.object(_bot_mod, "Bot", lambda token, **kw: bot),
                patch.object(_bot_mod, "async_session_factory", sf),
            ):
                from app.platforms.telegram.bot import TelegramBot
                tb = TelegramBot()

                update = make_message_update(user_id=999, text="/start", bot=bot)
                await tb.dp.feed_update(bot, update)

            sent = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert len(sent) >= 1
            assert "TicketBot" in sent[0].text
        finally:
            await _clean_db(sf)
