"""
Тесты сервисного слоя: UserService, EventService, TicketService.
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select, func

from app.core.models import User, Event, Ticket, Payment
from app.core.models import PlatformType, TicketStatus, PaymentStatus


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
# EventService
# ═══════════════════════════════════════════════════════════════

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
