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

from app.core.models import SubscriptionTier, Ticket, TicketStatus
from app.core.services import (
    ChannelAdminService,
    ChannelService,
    EventService,
    TicketService,
)

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

    async def test_organizer_checkin_ticket_via_check_command(self, test_engine):
        """F7: организатор вводит код билета → /check → билет отмечен на входе.

        Покупатель (9999) покупает билет через deep-link /start buy_<id> (бот),
        организатор-админ канала (12345) вводит код → «Вход разрешён», статус checked_in.
        Хендлер не зарегистрирован в режиме «только web» — вызываем метод напрямую
        с реальным Message (бот с фейк-сессией, БД реальная).
        """
        sf = _make_session_factory(test_engine)

        # ── Подготовка: канал + опубликованное мероприятие ──
        async with sf() as s:
            channel_svc = ChannelService(s)
            channel = await channel_svc.create("@sim_checkin", "", "Checkin Channel")
            channel = await channel_svc.activate_subscription(
                channel.id, duration_days=365, tier=SubscriptionTier.basic,
            )
            event_svc = EventService(s)
            event = await event_svc.create(
                title="Checkin Event",
                description=None,
                date=datetime.now(timezone.utc) + timedelta(days=7),
                location=None,
                price=0,
                total_tickets=10,
                channel_id=channel.id,
            )
            event.is_published = True
            await s.commit()
            event_id = event.id
            channel_id = channel.id

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

                # Покупатель 9999 покупает билет через deep-link (F1)
                buy_update = make_message_update(
                    user_id=9999, text=f"/start buy_{event_id}", bot=bot,
                )
                await tb.dp.feed_update(bot, buy_update)

                # Организатор 12345 — админ канала (реальная БД)
                async with sf() as s:
                    await ChannelAdminService(s).sync_admins(channel_id, ["12345"])
                    await s.commit()

                # Код купленного билета
                async with sf() as s:
                    ticket = (await s.execute(
                        select(Ticket).where(Ticket.event_id == event_id),
                    )).scalars().one()
                    code = ticket.validation_code

                # F7: организатор вводит код → check-in
                check_update = make_message_update(
                    user_id=12345, text=f"/check {code}", bot=bot,
                )
                await tb.cmd_check(check_update.message)

            # ── Проверки ──
            sent = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert any("Вход разрешён" in c.text for c in sent), [
                c.text for c in sent
            ]

            async with sf() as s:
                ticket = (await s.execute(
                    select(Ticket).where(Ticket.event_id == event_id),
                )).scalars().one()
                assert ticket.status == TicketStatus.checked_in
                assert ticket.checked_in_by == "12345"
        finally:
            await _clean_db(sf)

    async def test_admin_reposts_announcement_to_channel(self, test_engine):
        """F5: анонс мероприятия публикуется в канал (перепост анонсов).

        Организатор-админ канала (12345) запускает перепост анонсов →
        бот отправляет сообщение с анонсом в telegram_channel_id канала.
        Хендлер не зарегистрирован в режиме «только web» — вызываем метод
        напрямую с реальным Message (бот с фейк-сессией, БД реальная).
        """
        sf = _make_session_factory(test_engine)

        # ── Подготовка: канал + опубликованное предстоящее мероприятие ──
        async with sf() as s:
            channel_svc = ChannelService(s)
            channel = await channel_svc.create("@sim_announce", "", "Announce Channel")
            channel = await channel_svc.activate_subscription(
                channel.id, duration_days=365, tier=SubscriptionTier.basic,
            )
            event_svc = EventService(s)
            event = await event_svc.create(
                title="Announce Event",
                description=None,
                date=datetime.now(timezone.utc) + timedelta(days=7),
                location=None,
                price=0,
                total_tickets=10,
                channel_id=channel.id,
            )
            event.is_published = True
            await s.commit()
            channel_id = channel.id
            channel_tg_id = channel.telegram_channel_id

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

                # Организатор 12345 — админ канала (реальная БД)
                async with sf() as s:
                    await ChannelAdminService(s).sync_admins(channel_id, ["12345"])
                    await s.commit()

                # F5: перепост анонсов в канал
                repost_update = make_message_update(
                    user_id=12345, text="/repost_events", bot=bot,
                )
                await tb.admin_repost_events(repost_update.message)

            # ── Проверки: анонс ушёл в канал (chat_id = telegram_channel_id) ──
            sent_to_channel = [
                c for c in fake.calls
                if c.__class__.__name__ == "SendMessage"
                and getattr(c, "chat_id", None) == channel_tg_id
            ]
            assert len(sent_to_channel) == 1, [
                (c.__class__.__name__, getattr(c, "chat_id", None)) for c in fake.calls
            ]
            assert "Announce Event" in sent_to_channel[0].text
        finally:
            await _clean_db(sf)
