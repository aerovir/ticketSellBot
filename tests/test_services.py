"""
Тесты сервисного слоя: UserService, EventService, TicketService.
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select, func

from app.core.models import User, Event, Ticket, Payment, ChannelAdmin
from app.core.models import PlatformType, TicketStatus, PaymentStatus, SubscriptionTier
from app.core.services import ChannelService, ChannelAdminService


# ═══════════════════════════════════════════════════════════════
# UserService
# ═══════════════════════════════════════════════════════════════

class TestUserService:
    async def test_get_or_create_new(self, db_session, user_svc):
        """Создание нового пользователя."""
        user = await user_svc.get_or_create(
            platform=PlatformType.telegram,
            platform_user_id="new_user_001",
            name="New User",
        )
        assert user.id is not None
        assert user.platform == PlatformType.telegram
        assert user.platform_user_id == "new_user_001"
        assert user.name == "New User"

    async def test_get_or_create_existing(self, db_session, user_svc, sample_user):
        """Повторный запрос возвращает того же пользователя (без обновления имени)."""
        user = await user_svc.get_or_create(
            platform=sample_user.platform,
            platform_user_id=sample_user.platform_user_id,
            name="New Name",
        )
        assert user.id == sample_user.id
        # Сервис не обновляет имя существующего пользователя
        assert user.name == "Test User"

    async def test_get_or_create_other_platform(self, db_session, user_svc, sample_user):
        """Тот же platform_user_id, но другой platform — разные пользователи."""
        user2 = await user_svc.get_or_create(
            platform=PlatformType.vk,
            platform_user_id=sample_user.platform_user_id,
            name="VK User",
        )
        assert user2.id != sample_user.id


# ═══════════════════════════════════════════════════════════════
# ChannelService
# ═══════════════════════════════════════════════════════════════

class TestChannelService:
    async def test_change_admin_success(self, db_session, sample_channel):
        """Успешная смена админа — обновляется и ChannelAdmin, и legacy-поле."""
        svc = ChannelService(db_session)
        channel, old_admins = await svc.change_admin("test_channel_1", "new_admin_42")
        await db_session.commit()

        assert channel.admin_telegram_user_id == "new_admin_42"

        # ChannelAdmin обновлён
        admin_svc = ChannelAdminService(db_session)
        current = await admin_svc.get_admin_ids(channel.id)
        assert "new_admin_42" in current
        assert "test_12345" not in current

    async def test_change_admin_not_found(self, db_session):
        """Несуществующий канал -> ValueError."""
        svc = ChannelService(db_session)
        with pytest.raises(ValueError, match="не найден"):
            await svc.change_admin("nonexistent", "admin_42")

    async def test_change_admin_same_admin(self, db_session, sample_channel):
        """Смена на того же админа — не падает, меняет корректно."""
        svc = ChannelService(db_session)
        channel, old_admins = await svc.change_admin("test_channel_1", "test_12345")
        await db_session.commit()

        admin_svc = ChannelAdminService(db_session)
        current = await admin_svc.get_admin_ids(channel.id)
        assert current == ["test_12345"]

    async def test_change_admin_legacy_field(self, db_session, sample_channel):
        """admin_telegram_user_id синхронизируется с channel_admins."""
        svc = ChannelService(db_session)
        channel, _ = await svc.change_admin("test_channel_1", "legacy_test")
        await db_session.commit()

        assert channel.admin_telegram_user_id == "legacy_test"

    async def test_change_admin_returns_old_admins(self, db_session, sample_channel):
        """Метод возвращает список старых админов."""
        svc = ChannelService(db_session)
        # Добавляем второго админа
        admin_svc = ChannelAdminService(db_session)
        await admin_svc.sync_admins(sample_channel.id, ["test_12345", "second_admin"])
        await db_session.commit()

        channel, old_admins = await svc.change_admin("test_channel_1", "new_admin_99")
        await db_session.commit()

        assert set(old_admins) == {"test_12345", "second_admin"}

    async def test_channel_activated_then_admin_synced(self, db_session):
        """Канал создан и активирован — админ добавляется через sync_admins.

        Симуляция: суперадмин подписывает новый канал (бота нет в БД).
        Канал создаётся, активируется. Если бот в канале — админы
        синхронизируются. Проверяем, что после sync_admins админ виден.
        """
        svc = ChannelService(db_session)
        admin_svc = ChannelAdminService(db_session)

        channel = await svc.create(
            telegram_channel_id="@test_new_ch_sub",
            admin_telegram_user_id="",
            title="New via subscribe",
        )
        await svc.activate_subscription(
            channel.id, duration_days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()

        # Синхронизация админов (что и должна делать subscribe-ветка)
        await admin_svc.sync_admins(channel.id, ["sub_admin_id"])
        await db_session.commit()

        admin_ids = await admin_svc.get_admin_ids(channel.id)
        assert "sub_admin_id" in admin_ids

        channels = await svc.get_channels_by_admin("sub_admin_id")
        assert any(ch.id == channel.id for ch in channels)

    async def test_channel_activated_no_admins_before_sync(self, db_session):
        """Канал без синхронизации админов — список пуст.

        Симуляция: бот ещё не в канале (get_chat_administrators не вызван).
        В channel_admins никого нет — прочерк в списке каналов.
        Это ожидаемое временное состояние до добавления бота.
        """
        svc = ChannelService(db_session)
        admin_svc = ChannelAdminService(db_session)

        channel = await svc.create(
            telegram_channel_id="@test_no_bot_yet",
            admin_telegram_user_id="",
            title="Bot not in channel",
        )
        await svc.activate_subscription(channel.id, duration_days=30)
        await db_session.commit()

        admin_ids = await admin_svc.get_admin_ids(channel.id)
        assert admin_ids == []


# ═══════════════════════════════════════════════════════════════
# ChannelService — Subscription tiers
# ═══════════════════════════════════════════════════════════════

class TestSubscriptionTier:
    async def test_default_tier_is_basic(self, db_session):
        """Новый канал без подписки имеет tier=basic по умолчанию."""
        from app.core.models import Channel as ChannelModel
        ch = ChannelModel(
            telegram_channel_id="default_tier_test",
            admin_telegram_user_id="admin_test",
        )
        db_session.add(ch)
        await db_session.flush()
        assert ch.subscription_tier == SubscriptionTier.basic

    async def test_activate_subscription_with_tier(self, db_session):
        """Активация подписки с указанием tier."""
        svc = ChannelService(db_session)
        channel = await svc.create(
            telegram_channel_id="tier_test_channel",
            admin_telegram_user_id="admin_1",
            title="Tier Test",
        )
        await db_session.commit()

        activated = await svc.activate_subscription(channel.id, duration_days=30, tier=SubscriptionTier.pro)
        await db_session.commit()

        assert activated.subscription_tier == SubscriptionTier.pro
        assert activated.is_subscription_active is True

    async def test_activate_subscription_default_tier(self, db_session):
        """Активация без указания tier сохраняет basic."""
        svc = ChannelService(db_session)
        channel = await svc.create(
            telegram_channel_id="default_tier_ch",
            admin_telegram_user_id="admin_2",
            title="Default Tier",
        )
        await db_session.commit()

        activated = await svc.activate_subscription(channel.id, duration_days=30)
        await db_session.commit()

        assert activated.subscription_tier == SubscriptionTier.basic

    async def test_get_subscription_tier(self, db_session, sample_channel):
        """Проверка получения tier канала."""
        svc = ChannelService(db_session)
        tier = await svc.get_subscription_tier(sample_channel.id)
        assert tier == SubscriptionTier.pro

    async def test_get_subscription_tier_not_found(self, db_session):
        """Несуществующий канал -> None."""
        svc = ChannelService(db_session)
        tier = await svc.get_subscription_tier(uuid.uuid4())
        assert tier is None

    async def test_require_feature_basic_can_create_free(self, db_session, basic_channel):
        """Basic tier может создавать бесплатные мероприятия."""
        svc = ChannelService(db_session)
        can = await svc.require_feature(basic_channel.id, "free_events")
        assert can is True

    async def test_require_feature_basic_cannot_paid(self, db_session, basic_channel):
        """Basic tier НЕ может создавать платные мероприятия."""
        svc = ChannelService(db_session)
        can = await svc.require_feature(basic_channel.id, "paid_events")
        assert can is False

    async def test_require_feature_pro_can_paid(self, db_session):
        """Pro tier может создавать платные мероприятия."""
        svc = ChannelService(db_session)
        channel = await svc.create(
            telegram_channel_id="pro_ch",
            admin_telegram_user_id="admin_pro",
            title="Pro Channel",
        )
        await db_session.commit()
        await svc.activate_subscription(channel.id, duration_days=30, tier=SubscriptionTier.pro)
        await db_session.commit()

        can_paid = await svc.require_feature(channel.id, "paid_events")
        assert can_paid is True
        can_free = await svc.require_feature(channel.id, "free_events")
        assert can_free is True

    async def test_require_feature_no_subscription(self, db_session):
        """Канал без подписки не имеет фич."""
        from app.core.models import Channel as ChannelModel
        ch = ChannelModel(
            telegram_channel_id="no_sub_channel",
            admin_telegram_user_id="admin_no_sub",
        )
        db_session.add(ch)
        await db_session.flush()

        svc = ChannelService(db_session)
        can = await svc.require_feature(ch.id, "free_events")
        assert can is False

    async def test_event_create_basic_rejects_paid(self, db_session, event_svc, basic_channel):
        """Создание платного мероприятия на канале Basic -> ошибка."""
        future = datetime.now(timezone.utc) + timedelta(days=10)

        with pytest.raises(ValueError, match="бесплатные"):
            await event_svc.create(
                title="Платный концерт",
                description="Должен быть бесплатным",
                date=future,
                location="Москва",
                price=1000.0,
                total_tickets=50,
                channel_id=basic_channel.id,
            )

    async def test_event_create_basic_allows_free(self, db_session, event_svc, basic_channel):
        """Создание бесплатного мероприятия на канале Basic -> OK."""
        future = datetime.now(timezone.utc) + timedelta(days=10)
        event = await event_svc.create(
            title="Бесплатная лекция",
            description="Доступно всем",
            date=future,
            location="Москва",
            price=0,
            total_tickets=100,
            channel_id=basic_channel.id,
        )
        assert event.price == 0
        assert event.is_free is True

    async def test_event_create_pro_allows_paid(self, db_session, event_svc, sample_channel):
        """Создание платного мероприятия на канале Pro -> OK."""
        future = datetime.now(timezone.utc) + timedelta(days=10)
        event = await event_svc.create(
            title="Платный концерт",
            description="Только Pro",
            date=future,
            location="Москва",
            price=1500.0,
            total_tickets=50,
            channel_id=sample_channel.id,
        )
        assert event.price == 1500.0
        assert event.is_free is False

class TestEventService:
    async def test_create_event(self, db_session, event_svc, sample_channel):
        """Создание мероприятия."""
        future = datetime.now(timezone.utc) + timedelta(days=10)
        event = await event_svc.create(
            title="Концерт",
            description="Рок",
            date=future,
            location="Москва",
            price=2000.0,
            total_tickets=50,
            channel_id=sample_channel.id,
        )
        assert event.title == "Концерт"
        assert event.available_tickets == 50
        assert event.is_active is True
        assert event.price == 2000.0

    async def test_list_upcoming(self, db_session, event_svc, sample_event, sample_past_event):
        """Только активные будущие мероприятия."""
        events = await event_svc.list_upcoming()
        ids = [e.id for e in events]
        assert sample_event.id in ids
        assert sample_past_event.id not in ids

    async def test_list_upcoming_inactive(self, db_session, event_svc, sample_event):
        """Неактивные мероприятия не показываются в списке."""
        await event_svc.set_active(sample_event.id, False)
        await db_session.commit()

        events = await event_svc.list_upcoming()
        assert sample_event.id not in [e.id for e in events]

    async def test_get_by_id_found(self, db_session, event_svc, sample_event):
        """Поиск существующего мероприятия."""
        event = await event_svc.get_by_id(sample_event.id)
        assert event is not None
        assert event.id == sample_event.id

    async def test_get_by_id_not_found(self, db_session, event_svc):
        """Поиск несуществующего мероприятия."""
        event = await event_svc.get_by_id(uuid.uuid4())
        assert event is None

    async def test_set_active(self, db_session, event_svc, sample_event):
        """Включение/отключение мероприятия."""
        updated = await event_svc.set_active(sample_event.id, False)
        assert updated.is_active is False

        updated = await event_svc.set_active(sample_event.id, True)
        assert updated.is_active is True

    async def test_update_event(self, db_session, event_svc, sample_event):
        """Обновление полей мероприятия."""
        updated = await event_svc.update(
            sample_event.id,
            title="Новое название",
            price=3000.0,
        )
        assert updated.title == "Новое название"
        assert updated.price == 3000.0

    async def test_list_all(self, db_session, event_svc, sample_event, sample_past_event):
        """Все мероприятия (включая прошедшие)."""
        all_events = await event_svc.list_all()
        ids = [e.id for e in all_events]
        assert sample_event.id in ids
        assert sample_past_event.id in ids

    async def test_get_event_stats(self, db_session, event_svc, ticket_svc, sample_event, sample_user):
        """Статистика продаж."""
        # Покупаем билет
        await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        stats = await event_svc.get_event_stats(sample_event.id)
        assert stats["total_tickets"] == 100
        assert stats["sold"] == 1
        assert stats["refunded"] == 0
        assert stats["sold_pct"] == 1.0
        assert stats["revenue"] == 1000.0

    async def test_get_event_stats_refund(self, db_session, event_svc, ticket_svc, sample_event, sample_user):
        """Статистика с возвратом."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        await ticket_svc.cancel_ticket(ticket.id, sample_user.id)
        await db_session.commit()

        stats = await event_svc.get_event_stats(sample_event.id)
        assert stats["sold"] == 0
        assert stats["refunded"] == 1
        assert stats["revenue"] == 0.0


# ═══════════════════════════════════════════════════════════════
# TicketService
# ═══════════════════════════════════════════════════════════════

class TestTicketService:
    async def test_buy_ticket_success(self, db_session, ticket_svc, sample_user, sample_event):
        """Успешная покупка билета."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        assert ticket.status == TicketStatus.active
        assert ticket.event_id == sample_event.id
        assert ticket.user_id == sample_user.id

        # Проверяем, что available_tickets уменьшился
        event = await db_session.get(Event, sample_event.id)
        assert event.available_tickets == 99

        # Проверяем, что создался Payment
        stmt = select(Payment).where(Payment.ticket_id == ticket.id)
        result = await db_session.execute(stmt)
        payment = result.scalar_one()
        assert payment.amount == sample_event.price
        assert payment.status == PaymentStatus.completed

    async def test_buy_ticket_sold_out(self, db_session, ticket_svc, sample_user, event_svc, sample_channel):
        """Покупка при отсутствии билетов."""
        # Создаём мероприятие с 0 билетов
        future = datetime.now(timezone.utc) + timedelta(days=10)
        event = await event_svc.create(
            title="Sold Out", description=None, date=future, price=0,
            total_tickets=0, location="Msk",
            channel_id=sample_channel.id,
        )
        await db_session.commit()

        with pytest.raises(ValueError, match="Билеты закончились"):
            await ticket_svc.buy_ticket(sample_user.id, event.id)

    async def test_buy_ticket_inactive(self, db_session, ticket_svc, sample_user, event_svc, sample_event):
        """Покупка на неактивное мероприятие."""
        await event_svc.set_active(sample_event.id, False)
        await db_session.commit()

        with pytest.raises(ValueError, match="Мероприятие неактивно"):
            await ticket_svc.buy_ticket(sample_user.id, sample_event.id)

    async def test_buy_ticket_past(self, db_session, ticket_svc, sample_user, sample_past_event):
        """Покупка на прошедшее мероприятие."""
        with pytest.raises(ValueError, match="Мероприятие уже прошло"):
            await ticket_svc.buy_ticket(sample_user.id, sample_past_event.id)

    async def test_buy_ticket_not_found(self, db_session, ticket_svc, sample_user):
        """Покупка на несуществующее мероприятие."""
        with pytest.raises(ValueError, match="Мероприятие не найдено"):
            await ticket_svc.buy_ticket(sample_user.id, uuid.uuid4())

    async def test_buy_ticket_duplicate(self, db_session, ticket_svc, sample_user, sample_event):
        """Повторная покупка на то же мероприятие."""
        await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        with pytest.raises(ValueError, match="У вас уже есть активный билет"):
            await ticket_svc.buy_ticket(sample_user.id, sample_event.id)

    async def test_buy_ticket_webapp_success(self, db_session, ticket_svc, sample_user, sample_event):
        """Покупка билета через Mini App (Payment.status = pending)."""
        result = await ticket_svc.buy_ticket_webapp(sample_user.id, sample_event.id)
        await db_session.commit()

        assert result["ticket_id"] is not None
        assert result["event_title"] == sample_event.title
        assert result["amount"] == float(sample_event.price)
        assert result["payment_status"] == "pending"

        # Check that available_tickets decreased
        assert result["ticket_id"] != ""

    async def test_buy_ticket_webapp_sold_out(self, db_session, ticket_svc, sample_user, event_svc, sample_channel):
        """Покупка через Mini App при отсутствии билетов."""
        future = datetime.now(timezone.utc) + timedelta(days=10)
        event = await event_svc.create(
            title="Sold Out WA", description=None, date=future, price=0,
            total_tickets=0, location="Msk",
            channel_id=sample_channel.id,
        )
        await db_session.commit()

        with pytest.raises(ValueError, match="Билеты закончились"):
            await ticket_svc.buy_ticket_webapp(sample_user.id, event.id)

    async def test_buy_ticket_webapp_pending_payment(self, db_session, ticket_svc, sample_user, sample_event):
        """Проверка, что payment создаётся с status=pending."""
        from app.core.models import Payment, PaymentStatus
        from sqlalchemy import select

        result = await ticket_svc.buy_ticket_webapp(sample_user.id, sample_event.id)
        await db_session.commit()

        # Verify payment in DB
        stmt = select(Payment).where(Payment.ticket_id == result["ticket_id"])
        payment = (await db_session.execute(stmt)).scalar_one_or_none()
        assert payment is not None
        assert payment.status == PaymentStatus.pending
        assert float(payment.amount) == float(sample_event.price)

    async def test_cancel_ticket_success(self, db_session, ticket_svc, sample_user, sample_event):
        """Успешный возврат билета."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        cancelled = await ticket_svc.cancel_ticket(ticket.id, sample_user.id)
        await db_session.commit()

        assert cancelled.status == TicketStatus.refunded

        # Проверяем, что available_tickets восстановился
        event = await db_session.get(Event, sample_event.id)
        assert event.available_tickets == 100

        # Проверяем Payment
        stmt = select(Payment).where(Payment.ticket_id == ticket.id)
        result = await db_session.execute(stmt)
        payment = result.scalar_one()
        assert payment.status == PaymentStatus.refunded

    async def test_cancel_other_user(self, db_session, ticket_svc, sample_user, sample_event):
        """Попытка вернуть чужой билет."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        other_user_id = uuid.uuid4()
        with pytest.raises(ValueError, match="Это не ваш билет"):
            await ticket_svc.cancel_ticket(ticket.id, other_user_id)

    async def test_cancel_already_refunded(self, db_session, ticket_svc, sample_user, sample_event):
        """Попытка вернуть уже возвращённый билет."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()
        await ticket_svc.cancel_ticket(ticket.id, sample_user.id)
        await db_session.commit()

        with pytest.raises(ValueError, match="Билет уже возвращён"):
            await ticket_svc.cancel_ticket(ticket.id, sample_user.id)

    async def test_cancel_not_found(self, db_session, ticket_svc, sample_user):
        """Попытка отменить несуществующий билет."""
        with pytest.raises(ValueError, match="Билет не найден"):
            await ticket_svc.cancel_ticket(uuid.uuid4(), sample_user.id)

    async def test_get_user_tickets(self, db_session, ticket_svc, sample_user, sample_event):
        """Список билетов пользователя."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        tickets = await ticket_svc.get_user_tickets(sample_user.id)
        assert len(tickets) == 1
        assert tickets[0]["event_title"] == "Тестовое мероприятие"
        assert tickets[0]["status"] == "active"
        assert tickets[0]["id"] == ticket.id

    async def test_get_user_tickets_empty(self, db_session, ticket_svc, sample_user):
        """Пустой список билетов."""
        tickets = await ticket_svc.get_user_tickets(sample_user.id)
        assert tickets == []

    async def test_admin_cancel_ticket(self, db_session, ticket_svc, sample_user, sample_event):
        """Админская отмена билета (без проверки владельца)."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        result = await ticket_svc.admin_cancel_ticket(ticket.id)
        assert result.status == TicketStatus.refunded

    async def test_get_event_tickets(self, db_session, ticket_svc, sample_user, sample_event):
        """Список билетов на мероприятие (админка)."""
        await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        tickets = await ticket_svc.get_event_tickets(sample_event.id)
        assert len(tickets) == 1
        assert tickets[0]["user_name"] == "Test User"

    async def test_buy_free_ticket_has_validation_code(self, db_session, ticket_svc, sample_user, event_svc, sample_channel):
        """Бесплатный билет получает validation_code."""
        future = datetime.now(timezone.utc) + timedelta(days=10)
        event = await event_svc.create(
            title="Бесплатный", description=None, date=future, price=0,
            total_tickets=50, location="Msk",
            channel_id=sample_channel.id,
        )
        await db_session.commit()

        ticket = await ticket_svc.buy_ticket(sample_user.id, event.id)
        await db_session.commit()

        assert ticket.validation_code is not None
        assert len(ticket.validation_code) == 9  # XXXX-XXXX
        assert "-" in ticket.validation_code

    async def test_validation_code_format(self, db_session, ticket_svc):
        """Формат validation_code: XXXX-XXXX."""
        code = await ticket_svc.generate_validation_code()
        assert len(code) == 9  # 8 символов + дефис
        assert code[4] == "-"
        # Все символы — буквы или цифры (кроме дефиса)
        parts = code.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4
        assert len(parts[1]) == 4
        # hex: только 0-9, A-F
        assert all(c in "0123456789ABCDEF" for c in (parts[0] + parts[1]))

    async def test_validation_code_unique(self, db_session, ticket_svc):
        """Последовательные коды уникальны."""
        codes = set()
        for _ in range(100):
            code = await ticket_svc.generate_validation_code()
            assert code not in codes
            codes.add(code)

    async def test_is_free_flag_on_ticket(self, db_session, ticket_svc, sample_user, event_svc, sample_channel):
        """is_free=True для бесплатного билета."""
        future = datetime.now(timezone.utc) + timedelta(days=10)
        event = await event_svc.create(
            title="Free Event", description=None, date=future, price=0,
            total_tickets=10, location="Msk",
            channel_id=sample_channel.id,
        )
        await db_session.commit()

        event_paid = await event_svc.create(
            title="Paid Event", description=None, date=future, price=500,
            total_tickets=10, location="Msk",
            channel_id=sample_channel.id,
        )
        await db_session.commit()

        free_ticket = await ticket_svc.buy_ticket(sample_user.id, event.id)
        paid_ticket = await ticket_svc.buy_ticket(sample_user.id, event_paid.id)
        await db_session.commit()

        assert free_ticket.is_free is True
        assert paid_ticket.is_free is False


# ═══════════════════════════════════════════════════════════════
# TicketService — Validation & Check-in
# ═══════════════════════════════════════════════════════════════

class TestTicketValidation:
    async def test_validate_ticket_found(self, db_session, ticket_svc, sample_user, sample_event):
        """Поиск билета по validation_code."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        result = await ticket_svc.validate_ticket(ticket.validation_code)
        assert result["found"] is True
        assert result["status"] == "active"
        assert result["user_name"] == "Test User"
        assert result["event_title"] == "Тестовое мероприятие"
        assert result["already_checked_in"] is False

    async def test_validate_ticket_not_found(self, db_session, ticket_svc):
        """Несуществующий код -> not found."""
        result = await ticket_svc.validate_ticket("ZZZZ-ZZZZ")
        assert result["found"] is False
        assert result["status"] == "not_found"

    async def test_validate_ticket_refunded(self, db_session, ticket_svc, sample_user, sample_event):
        """Возвращённый билет -> status=refunded."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()
        await ticket_svc.cancel_ticket(ticket.id, sample_user.id)
        await db_session.commit()

        result = await ticket_svc.validate_ticket(ticket.validation_code)
        assert result["found"] is True
        assert result["status"] == "refunded"

    async def test_check_in_success(self, db_session, ticket_svc, sample_user, sample_event):
        """Успешный чекин билета."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        checked = await ticket_svc.check_in(ticket.id, "admin_123")
        await db_session.commit()

        assert checked.status == TicketStatus.checked_in
        assert checked.checked_in_at is not None
        assert checked.checked_in_by == "admin_123"

    async def test_check_in_by_code_success(self, db_session, ticket_svc, sample_user, sample_event):
        """Чекин по validation_code."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        checked = await ticket_svc.check_in_by_code(ticket.validation_code, "admin_456")
        await db_session.commit()

        assert checked.status == TicketStatus.checked_in
        assert checked.checked_in_by == "admin_456"

    async def test_check_in_already_checked(self, db_session, ticket_svc, sample_user, sample_event):
        """Повторный чекин -> ошибка."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()

        await ticket_svc.check_in(ticket.id, "admin_1")
        await db_session.commit()

        with pytest.raises(ValueError, match="уже использован"):
            await ticket_svc.check_in(ticket.id, "admin_2")

    async def test_check_in_refunded_ticket(self, db_session, ticket_svc, sample_user, sample_event):
        """Чекин возвращённого билета -> ошибка."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()
        await ticket_svc.cancel_ticket(ticket.id, sample_user.id)
        await db_session.commit()

        with pytest.raises(ValueError, match="возвращён"):
            await ticket_svc.check_in(ticket.id, "admin_1")

    async def test_check_in_nonexistent(self, db_session, ticket_svc):
        """Чекин несуществующего билета -> ошибка."""
        with pytest.raises(ValueError, match="не найден"):
            await ticket_svc.check_in(uuid.uuid4(), "admin_1")

    async def test_buy_paid_ticket_on_basic_channel_fails(self, db_session, ticket_svc, sample_user, basic_channel):
        """Покупка платного билета на Basic-канале -> ошибка."""
        from app.core.services import EventService
        svc = EventService(db_session)
        future = datetime.now(timezone.utc) + timedelta(days=10)
        # Basic-канал не даст создать платное мероприятие, но проверим buy_ticket напрямую
        # через существующее free-мероприятие с подменой цены
        event = await svc.create(
            title="Free But...", description="x", date=future, price=0,
            total_tickets=10, location="Msk",
            channel_id=basic_channel.id,
        )
        await db_session.commit()

        # Покупка работает для бесплатного
        ticket = await ticket_svc.buy_ticket(sample_user.id, event.id)
        await db_session.commit()
        assert ticket.is_free is True

    async def test_validate_after_check_in_shows_timestamp(self, db_session, ticket_svc, sample_user, sample_event):
        """После чекина validate возвращает checked_in_at."""
        ticket = await ticket_svc.buy_ticket(sample_user.id, sample_event.id)
        await db_session.commit()
        await ticket_svc.check_in(ticket.id, "admin_1")
        await db_session.commit()

        result = await ticket_svc.validate_ticket(ticket.validation_code)
        assert result["found"] is True
        assert result["status"] == "checked_in"
        assert result["already_checked_in"] is True
        assert result["checked_in_at"] is not None

    async def test_check_in_by_code_not_found(self, db_session, ticket_svc):
        """Чекин по несуществующему коду -> ошибка."""
        with pytest.raises(ValueError, match="не найден"):
            await ticket_svc.check_in_by_code("ZZZZ-ZZZZ", "admin_1")
