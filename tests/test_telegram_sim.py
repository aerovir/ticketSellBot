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

from app.core.models import ChannelAdmin, SubscriptionTier, Ticket, Event
from app.core.services import ChannelService, ChannelAdminService, EventService, TicketService

from tests.harness import (
    FakeTelegramSession,
    make_callback_update,
    make_channel_post_update,
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


# ═══════════════════════════════════════════════════════════════
# Расширенный контур: весь user-flow пользователя
# ═══════════════════════════════════════════════════════════════

async def _seed_channel_event(sf, *, price=500.0, channel_id="pro_channel", total=10):
    """Создать pro-канал + мероприятие, вернуть (channel, event)."""
    async with sf() as s:
        channel_svc = ChannelService(s)
        channel = await channel_svc.create(channel_id, "", f"Channel {channel_id}")
        channel = await channel_svc.activate_subscription(
            channel.id, duration_days=365, tier=SubscriptionTier.pro,
        )
        event_svc = EventService(s)
        event = await event_svc.create(
            title=f"Event {channel_id}", description=None,
            date=datetime.now(timezone.utc) + timedelta(days=7),
            location=None, price=price, total_tickets=total,
            channel_id=channel.id,
        )
        event.is_published = True
        await s.commit()
        return channel, event


async def _seed_channel_admin(sf, channel_id, admin_tg_id):
    """Назначить админа канала (channel_admins)."""
    async with sf() as s:
        admin_svc = ChannelAdminService(s)
        await admin_svc.sync_admins(channel_id, [admin_tg_id])
        await s.commit()


@pytest.mark.integration
class TestBotFlows:
    """Имитация полного user-flow через Dispatcher.feed_update."""

    async def _make_bot(self, sf, *, webapp_url="https://pochtibot.online"):
        """Собрать бота с фейк-сессией и патчами. Возвращает (bot, tb, fake)."""
        fake = FakeTelegramSession()
        bot = Bot(token="123456789:TESTTOKEN", session=fake)
        import app.platforms.telegram.bot as _bot_mod
        patch.object(_bot_mod.settings, "telegram_token", "123456789:TESTTOKEN").start()
        patch.object(_bot_mod.settings, "webapp_url", webapp_url).start()
        patch.object(_bot_mod, "async_session_factory", sf).start()
        patch.object(_bot_mod, "Bot", lambda token, **kw: bot).start()
        from app.platforms.telegram.bot import TelegramBot
        tb = TelegramBot()
        return bot, tb, fake

    async def test_inline_buy_legacy(self, test_engine):
        """Старая inline-кнопка buy:<id> (webapp_url='') — покупка."""
        sf = _make_session_factory(test_engine)
        try:
            channel, event = await _seed_channel_event(sf)
            bot, tb, fake = await self._make_bot(sf)
            with patch("app.platforms.telegram.bot.settings.webapp_url", ""):
                update = make_callback_update(12345, f"buy:{event.id}", bot)
                await tb.dp.feed_update(bot, update)

            async with sf() as s:
                tickets = (await s.execute(select(Ticket))).scalars().all()
            assert len(tickets) == 1
            assert tickets[0].validation_code is not None
            # DM с кодом билета отправлен
            assert tb.bot is bot, "tb.bot != bot"
            dm = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert any("Код:" in c.text or "Ваш билет" in c.text for c in dm), \
                f"DM с кодом не найден. SendMessage texts: {[getattr(c,'text','') for c in dm]}; calls: {[c.__class__.__name__ for c in fake.calls]}"
        finally:
            await _clean_db(sf)

    async def test_channel_buy_redirect_webapp(self, test_engine):
        """channel_buy:<id> при webapp_url — редирект в кабинет, БД не тронута."""
        sf = _make_session_factory(test_engine)
        try:
            channel, event = await _seed_channel_event(sf)
            bot, tb, fake = await self._make_bot(sf, webapp_url="https://pochtibot.online")
            # кнопка из канала
            msg = {"message_id": 5, "chat": {"id": -100123, "type": "channel", "title": "Chan"}}
            update = make_callback_update(12345, f"channel_buy:{event.id}", bot, message=msg)
            await tb.dp.feed_update(bot, update)

            async with sf() as s:
                tickets = (await s.execute(select(Ticket))).scalars().all()
            assert len(tickets) == 0  # БД не тронута
            # DM с WebApp-кнопкой (кнопка в reply_markup)
            dm = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert any("кабинет" in (c.text or "").lower() for c in dm), \
                f"DM о кабинете не найден: {[getattr(c,'text','') for c in dm]}"
            # В DM должна быть WebApp-кнопка ?event_id=
            webapp_found = False
            for c in dm:
                if c.reply_markup:
                    for row in c.reply_markup.model_dump().get("inline_keyboard", []):
                        for b in row:
                            if b.get("web_app") and "?event_id=" in b["web_app"]["url"]:
                                webapp_found = True
            assert webapp_found, "WebApp-кнопка с event_id не найдена в DM"
        finally:
            await _clean_db(sf)

    async def test_fsm_create_event(self, test_engine):
        """Создание мероприятия через FSM-мастер (админ канала)."""
        sf = _make_session_factory(test_engine)
        try:
            channel, _ = await _seed_channel_event(sf)
            await _seed_channel_admin(sf, channel.id, "12345")
            bot, tb, fake = await self._make_bot(sf)

            with patch("app.platforms.telegram.bot.settings.webapp_url", ""):
                # /menu
                await tb.dp.feed_update(bot, make_message_update(12345, "/menu", bot))
                # admin_menu:create_event
                await tb.dp.feed_update(bot, make_callback_update(12345, "admin_menu:create_event", bot))
                # FSM шаги
                await tb.dp.feed_update(bot, make_message_update(12345, "Новое мероприятие", bot))  # title
                await tb.dp.feed_update(bot, make_callback_update(12345, "fsm_skip:description", bot))  # skip desc
                await tb.dp.feed_update(bot, make_message_update(12345, "25.12.2026 19:00", bot))  # date
                await tb.dp.feed_update(bot, make_callback_update(12345, "fsm_skip:location", bot))  # skip loc
                await tb.dp.feed_update(bot, make_message_update(12345, "300", bot))  # price
                await tb.dp.feed_update(bot, make_message_update(12345, "50", bot))  # tickets
                await tb.dp.feed_update(bot, make_callback_update(12345, "fsm_skip:media", bot))  # skip media
                # подтвердить
                await tb.dp.feed_update(bot, make_callback_update(12345, "admin:confirm_create", bot))

            async with sf() as s:
                events = (await s.execute(select(Event))).scalars().all()
            assert len(events) == 2  # исходное + новое
            created = [e for e in events if e.title == "Новое мероприятие"][0]
            assert created.is_published is False  # черновик
            assert created.price == 300
        finally:
            await _clean_db(sf)

    async def test_check_ticket(self, test_engine):
        """Админ /check <code> — вход разрешён."""
        sf = _make_session_factory(test_engine)
        try:
            channel, event = await _seed_channel_event(sf)
            await _seed_channel_admin(sf, channel.id, "12345")
            # пользователь покупает билет
            async with sf() as s:
                ticket_svc = TicketService(s)
                from app.core.services import UserService
                from app.core.models import PlatformType
                user = await UserService(s).get_or_create(PlatformType.telegram, "999", "Buyer")
                ticket = await ticket_svc.buy_ticket(user.id, event.id)
                await s.commit()
                code = ticket.validation_code

            bot, tb, fake = await self._make_bot(sf)
            await tb.dp.feed_update(bot, make_message_update(12345, f"/check {code}", bot))

            async with sf() as s:
                t = (await s.execute(select(Ticket))).scalars().first()
            assert t.status.value == "checked_in"
            sent = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert any("Вход разрешён" in c.text for c in sent)
        finally:
            await _clean_db(sf)

    async def test_invite_deep_link(self, test_engine):
        """/start invite_<code> — показывает пригласительное с QR (SendPhoto)."""
        sf = _make_session_factory(test_engine)
        try:
            channel, event = await _seed_channel_event(sf)
            # создать пригласительное
            async with sf() as s:
                event_svc = EventService(s)
                await event_svc.update(event.id, invites_quota=5)
                ticket_svc = TicketService(s)
                invite = await ticket_svc.issue_invite(event.id, seats=1, issued_by="12345")
                await s.commit()
                code = invite.validation_code

            bot, tb, fake = await self._make_bot(sf)
            await tb.dp.feed_update(bot, make_message_update(999, f"/start invite_{code}", bot))

            photos = [c for c in fake.calls if c.__class__.__name__ == "SendPhoto"]
            assert len(photos) >= 1, f"QR-фото не отправлено. Вызовы: {[c.__class__.__name__ for c in fake.calls]}"
        finally:
            await _clean_db(sf)

    async def test_my_tickets_and_cancel(self, test_engine):
        """/my_tickets затем ticket_cancel:<id> — возврат билета."""
        sf = _make_session_factory(test_engine)
        try:
            channel, event = await _seed_channel_event(sf)
            async with sf() as s:
                from app.core.services import UserService
                from app.core.models import PlatformType
                ticket_svc = TicketService(s)
                user = await UserService(s).get_or_create(PlatformType.telegram, "777", "User")
                ticket = await ticket_svc.buy_ticket(user.id, event.id)
                await s.commit()
                ticket_id = ticket.id

            bot, tb, fake = await self._make_bot(sf)
            await tb.dp.feed_update(bot, make_message_update(777, "/my_tickets", bot))
            await tb.dp.feed_update(bot, make_callback_update(777, f"ticket_cancel:{ticket_id}", bot))

            async with sf() as s:
                t = (await s.execute(select(Ticket))).scalars().first()
            assert t.status.value == "refunded"
        finally:
            await _clean_db(sf)

    async def test_announcement_has_webapp_button(self, test_engine):
        """Анонс в канал — WebApp-кнопка без callback_data."""
        sf = _make_session_factory(test_engine)
        try:
            # числовой telegram_channel_id, чтобы send_message прошёл через fake
            channel, event = await _seed_channel_event(sf, channel_id="-1001234567890")
            bot, tb, fake = await self._make_bot(sf, webapp_url="https://pochtibot.online")

            from app.platforms.telegram.channel import ChannelManager
            manager = ChannelManager(bot)
            await manager.post_event_announcement(
                "Анонс", event.id, channel.telegram_channel_id, event=event,
            )

            sent = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert len(sent) >= 1
            # WebApp-кнопка: reply_markup с web_app url ?event_id=, без callback_data
            for s in sent:
                if s.reply_markup:
                    kb = s.reply_markup.model_dump()
                    buttons = [b for row in kb.get("inline_keyboard", []) for b in row]
                    for b in buttons:
                        if b.get("web_app"):
                            assert "?event_id=" in b["web_app"]["url"]
                            assert not b.get("callback_data"), "кнопка с web_app не должна иметь callback_data"
                            return
            raise AssertionError("WebApp-кнопка с event_id не найдена в анонсе")
        finally:
            await _clean_db(sf)

    async def test_channel_post_events(self, test_engine):
        """Команда /events в канале (channel_post) — список мероприятий."""
        sf = _make_session_factory(test_engine)
        try:
            channel, event = await _seed_channel_event(sf, channel_id="@chan_post")
            bot, tb, fake = await self._make_bot(sf)
            update = make_channel_post_update(-100777, "/events", bot)
            await tb.dp.feed_update(bot, update)

            sent = [c for c in fake.calls if c.__class__.__name__ == "SendMessage"]
            assert any("Мероприятия" in c.text or event.title in c.text for c in sent)
        finally:
            await _clean_db(sf)
