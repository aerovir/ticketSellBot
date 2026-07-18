import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import User, Event, Ticket, Payment, Channel, ChannelAdmin, TicketStatus, PaymentStatus, PlatformType
from app.core.schemas import EventOut, EventShortOut, TicketOut, UserOut


# ─── User Service ────────────────────────────────────────────────────────────

class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, platform: PlatformType, platform_user_id: str, name: Optional[str] = None) -> User:
        """Find existing user by platform+id, or create a new one."""
        stmt = select(User).where(
            and_(User.platform == platform, User.platform_user_id == platform_user_id)
        )
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                platform=platform,
                platform_user_id=platform_user_id,
                name=name,
            )
            self.session.add(user)
            await self.session.flush()

        return user


# ─── Channel Service ─────────────────────────────────────────────────────────

class ChannelService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_channel_id: str) -> Channel | None:
        """Look up a channel by its Telegram chat_id or @username."""
        stmt = select(Channel).where(Channel.telegram_channel_id == telegram_channel_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, channel_id: uuid.UUID) -> Channel | None:
        """Look up a channel by its UUID."""
        return await self.session.get(Channel, channel_id)

    async def create(
        self,
        telegram_channel_id: str,
        admin_telegram_user_id: str,
        title: str | None = None,
    ) -> Channel:
        """Create a new channel record."""
        channel = Channel(
            telegram_channel_id=telegram_channel_id,
            title=title,
            admin_telegram_user_id=admin_telegram_user_id,
            is_subscription_active=False,
        )
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def activate_subscription(self, channel_id: uuid.UUID, duration_days: int = 30) -> Channel | None:
        """Manually activate subscription for a channel."""
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            return None
        channel.is_subscription_active = True
        channel.subscription_until = datetime.now(timezone.utc) + timedelta(days=duration_days)
        await self.session.flush()
        return channel

    async def deactivate_subscription(self, channel_id: uuid.UUID) -> Channel | None:
        """Deactivate subscription."""
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            return None
        channel.is_subscription_active = False
        channel.subscription_until = None
        await self.session.flush()
        return channel

    async def is_subscription_valid(self, channel_id: uuid.UUID) -> bool:
        """Check if the channel has an active, non-expired subscription."""
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            return False
        if not channel.is_subscription_active:
            return False
        if channel.subscription_until and channel.subscription_until < datetime.now(timezone.utc):
            # Auto-deactivate expired subscriptions
            channel.is_subscription_active = False
            channel.subscription_until = None
            await self.session.flush()
            return False
        return True

    async def get_active_unassigned_channel(self) -> Channel | None:
        """Get a channel with active subscription but no admin assigned."""
        stmt = (
            select(Channel)
            .where(
                and_(
                    Channel.admin_telegram_user_id == "",
                    Channel.is_subscription_active == True,
                )
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_channel_ids_by_admin(self, telegram_user_id: str) -> list[uuid.UUID]:
        """Получить ID всех каналов, где пользователь — админ (из channel_admins)."""
        stmt = select(ChannelAdmin.channel_id).where(ChannelAdmin.telegram_user_id == telegram_user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_channels_by_admin(self, telegram_user_id: str) -> list[Channel]:
        """Получить все каналы, где пользователь — админ (через channel_admins)."""
        channel_ids = await self.get_channel_ids_by_admin(telegram_user_id)
        if not channel_ids:
            return []
        stmt = select(Channel).where(Channel.id.in_(channel_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ─── Channel Admin Service ──────────────────────────────────────────────────

class ChannelAdminService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_admin_ids(self, channel_id: uuid.UUID) -> list[str]:
        """Получить список Telegram ID админов канала."""
        stmt = select(ChannelAdmin.telegram_user_id).where(ChannelAdmin.channel_id == channel_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sync_admins(self, channel_id: uuid.UUID, admin_ids: list[str]):
        """Синхронизировать список админов канала с Telegram.

        Удаляет отсутствующих, добавляет новых, существующих не трогает.
        """
        existing = await self.get_admin_ids(channel_id)
        existing_set = set(existing)
        new_set = set(admin_ids)

        # Добавить новых
        for uid in new_set - existing_set:
            self.session.add(ChannelAdmin(channel_id=channel_id, telegram_user_id=uid))

        # Удалить отсутствующих
        to_remove = existing_set - new_set
        if to_remove:
            stmt = delete(ChannelAdmin).where(
                ChannelAdmin.channel_id == channel_id,
                ChannelAdmin.telegram_user_id.in_(to_remove),
            )
            await self.session.execute(stmt)

        await self.session.flush()

    async def user_is_admin(self, channel_id: uuid.UUID, telegram_user_id: str) -> bool:
        """Проверить, является ли пользователь админом канала."""
        stmt = select(ChannelAdmin).where(
            ChannelAdmin.channel_id == channel_id,
            ChannelAdmin.telegram_user_id == telegram_user_id,
        ).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def remove_admin(self, channel_id: uuid.UUID, telegram_user_id: str):
        """Удалить пользователя из админов канала."""
        stmt = delete(ChannelAdmin).where(
            ChannelAdmin.channel_id == channel_id,
            ChannelAdmin.telegram_user_id == telegram_user_id,
        )
        await self.session.execute(stmt)
        await self.session.flush()


# ─── Event Service ───────────────────────────────────────────────────────────

class EventService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_upcoming(self, channel_id: uuid.UUID | None = None) -> list[Event]:
        """Get all active events that haven't passed yet, optionally filtered by channel."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(Event)
            .where(
                and_(Event.is_active == True, Event.date >= now)
            )
            .order_by(Event.date.asc())
        )
        if channel_id is not None:
            stmt = stmt.where(Event.channel_id == channel_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, event_id: uuid.UUID, channel_id: uuid.UUID | None = None) -> Event | None:
        """Get event by ID, optionally scoped to a channel."""
        stmt = select(Event).where(Event.id == event_id)
        if channel_id is not None:
            stmt = stmt.where(Event.channel_id == channel_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, title: str, description: Optional[str], date: datetime,
                     location: Optional[str], price: float,
                     total_tickets: int, channel_id: uuid.UUID) -> Event:
        event = Event(
            title=title,
            description=description,
            date=date,
            location=location,
            price=price,
            total_tickets=total_tickets,
            available_tickets=total_tickets,
            is_active=True,
            channel_id=channel_id,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    # ─── Admin methods ───────────────────────────────────────────────────

    async def list_all(self, channel_id: uuid.UUID | None = None) -> list[Event]:
        """Get ALL events that are not deleted, newest first.
        Optionally filtered by channel."""
        stmt = select(Event).where(Event.deleted_at.is_(None)).order_by(Event.date.desc())
        if channel_id is not None:
            stmt = stmt.where(Event.channel_id == channel_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, event_id: uuid.UUID, **data) -> Event | None:
        """Partially update an event. Returns updated event or None."""
        event = await self.session.get(Event, event_id)
        if event is None:
            return None

        for key, value in data.items():
            if hasattr(event, key):
                setattr(event, key, value)

        # Sync available_tickets when total_tickets changes
        if "total_tickets" in data:
            old_total = event.total_tickets
            new_total = data["total_tickets"]
            diff = new_total - old_total
            event.available_tickets = max(0, event.available_tickets + diff)

        await self.session.flush()
        return event

    async def set_active(self, event_id: uuid.UUID, is_active: bool) -> Event | None:
        """Enable or disable an event. Returns updated event or None."""
        event = await self.session.get(Event, event_id)
        if event is None:
            return None
        event.is_active = is_active
        await self.session.flush()
        return event

    async def soft_delete(self, event_id: uuid.UUID) -> Event | None:
        """Soft delete an event — hides it from all lists.
        Sets is_active=False and deleted_at=now()."""
        event = await self.session.get(Event, event_id)
        if event is None:
            return None
        event.is_active = False
        event.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return event

    async def get_event_stats(self, event_id: uuid.UUID) -> dict:
        """Get sales stats for an event."""
        event = await self.session.get(Event, event_id)
        if event is None:
            raise ValueError("Мероприятие не найдено")

        # Count active tickets
        active_stmt = select(func.count(Ticket.id)).where(
            and_(Ticket.event_id == event_id, Ticket.status == TicketStatus.active)
        )
        active_result = await self.session.execute(active_stmt)
        sold = active_result.scalar() or 0

        # Count refunded tickets
        refunded_stmt = select(func.count(Ticket.id)).where(
            and_(Ticket.event_id == event_id, Ticket.status == TicketStatus.refunded)
        )
        refunded_result = await self.session.execute(refunded_stmt)
        refunded = refunded_result.scalar() or 0

        sold_pct = round((sold / event.total_tickets * 100), 1) if event.total_tickets > 0 else 0
        revenue = sold * event.price

        return {
            "total_tickets": event.total_tickets,
            "available": event.available_tickets,
            "sold": sold,
            "refunded": refunded,
            "sold_pct": sold_pct,
            "revenue": revenue,
        }


# ─── Ticket Service ──────────────────────────────────────────────────────────

class TicketService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def buy_ticket(self, user_id: uuid.UUID, event_id: uuid.UUID) -> Ticket:
        """Purchase a ticket for an event."""
        event = await self.session.get(Event, event_id)
        if event is None:
            raise ValueError("Мероприятие не найдено")
        if not event.is_active:
            raise ValueError("Мероприятие неактивно")
        if event.date < datetime.now(timezone.utc):
            raise ValueError("Мероприятие уже прошло")
        if event.available_tickets <= 0:
            raise ValueError("Билеты закончились")

        # Check if user already has an active ticket for this event
        existing_stmt = select(Ticket).where(
            and_(
                Ticket.user_id == user_id,
                Ticket.event_id == event_id,
                Ticket.status == TicketStatus.active,
            )
        )
        existing = await self.session.execute(existing_stmt)
        if existing.scalar_one_or_none() is not None:
            raise ValueError("У вас уже есть активный билет на это мероприятие")

        # Create ticket
        ticket = Ticket(
            id=uuid.uuid4(),  # явно, чтобы ticket.id не был None до flush
            event_id=event_id,
            user_id=user_id,
            status=TicketStatus.active,
        )
        self.session.add(ticket)

        # Decrease available tickets
        event.available_tickets -= 1

        # Create payment stub
        payment = Payment(
            ticket_id=ticket.id,
            amount=event.price,
            status=PaymentStatus.completed,  # stub — mark as completed
        )
        self.session.add(payment)

        await self.session.flush()
        return ticket

    async def buy_ticket_webapp(self, user_id: uuid.UUID, event_id: uuid.UUID) -> dict:
        """Purchase a ticket through the Mini App.

        Same validation as buy_ticket(), but creates Payment with
        status=pending (for future YooKassa integration) and returns
        a dict for the API response.
        """
        event = await self.session.get(Event, event_id)
        if event is None:
            raise ValueError("Мероприятие не найдено")
        if not event.is_active:
            raise ValueError("Мероприятие неактивно")
        if event.date < datetime.now(timezone.utc):
            raise ValueError("Мероприятие уже прошло")
        if event.available_tickets <= 0:
            raise ValueError("Билеты закончились")

        # Check if user already has an active ticket for this event
        existing_stmt = select(Ticket).where(
            and_(
                Ticket.user_id == user_id,
                Ticket.event_id == event_id,
                Ticket.status == TicketStatus.active,
            )
        )
        existing = await self.session.execute(existing_stmt)
        if existing.scalar_one_or_none() is not None:
            raise ValueError("У вас уже есть активный билет на это мероприятие")

        # Create ticket
        ticket = Ticket(
            id=uuid.uuid4(),
            event_id=event_id,
            user_id=user_id,
            status=TicketStatus.active,
        )
        self.session.add(ticket)

        # Decrease available tickets
        event.available_tickets -= 1

        # Create payment stub with pending status (Mini App flow)
        payment = Payment(
            ticket_id=ticket.id,
            amount=event.price,
            status=PaymentStatus.pending,
        )
        self.session.add(payment)

        await self.session.flush()

        return {
            "ticket_id": str(ticket.id),
            "event_title": event.title,
            "event_date": event.date.isoformat(),
            "amount": float(event.price),
            "payment_id": str(payment.id),
            "payment_status": payment.status.value,
            "purchase_date": ticket.purchase_date.isoformat(),
        }

    async def cancel_ticket(self, ticket_id: uuid.UUID, user_id: uuid.UUID) -> Ticket:
        """Cancel a ticket (refund)."""
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError("Билет не найден")
        if ticket.user_id != user_id:
            raise ValueError("Это не ваш билет")
        if ticket.status == TicketStatus.refunded:
            raise ValueError("Билет уже возвращён")

        # Mark ticket as refunded
        ticket.status = TicketStatus.refunded

        # Restore available tickets
        event = await self.session.get(Event, ticket.event_id)
        if event:
            event.available_tickets += 1

        # Update payment if exists
        payment_stmt = select(Payment).where(Payment.ticket_id == ticket_id)
        payment_result = await self.session.execute(payment_stmt)
        payment = payment_result.scalar_one_or_none()
        if payment:
            payment.status = PaymentStatus.refunded

        await self.session.flush()
        return ticket

    async def get_user_tickets(self, user_id: uuid.UUID, channel_id: uuid.UUID | None = None) -> list[dict]:
        """Get all tickets for a user with event info, optionally filtered by channel."""
        stmt = (
            select(Ticket, Event.title)
            .join(Event, Ticket.event_id == Event.id)
            .where(Ticket.user_id == user_id)
        )
        if channel_id is not None:
            stmt = stmt.where(Event.channel_id == channel_id)
        stmt = stmt.order_by(Ticket.purchase_date.desc())
        result = await self.session.execute(stmt)
        rows = result.all()

        tickets = []
        for ticket, event_title in rows:
            tickets.append({
                "id": ticket.id,
                "event_id": ticket.event_id,
                "event_title": event_title,
                "purchase_date": ticket.purchase_date,
                "status": ticket.status.value,
            })
        return tickets

    # ─── Admin methods ───────────────────────────────────────────────────

    async def admin_cancel_ticket(self, ticket_id: uuid.UUID) -> Ticket:
        """Cancel any ticket by admin (no ownership check)."""
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError("Билет не найден")
        if ticket.status == TicketStatus.refunded:
            raise ValueError("Билет уже возвращён")

        ticket.status = TicketStatus.refunded

        event = await self.session.get(Event, ticket.event_id)
        if event:
            event.available_tickets += 1

        payment_stmt = select(Payment).where(Payment.ticket_id == ticket_id)
        payment_result = await self.session.execute(payment_stmt)
        payment = payment_result.scalar_one_or_none()
        if payment:
            payment.status = PaymentStatus.refunded

        await self.session.flush()
        return ticket

    async def get_event_tickets(self, event_id: uuid.UUID) -> list[dict]:
        """Get all tickets for a specific event (admin view)."""
        stmt = (
            select(Ticket, User.name, User.platform_user_id)
            .join(User, Ticket.user_id == User.id)
            .where(Ticket.event_id == event_id)
            .order_by(Ticket.purchase_date.desc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        tickets = []
        for ticket, user_name, platform_user_id in rows:
            tickets.append({
                "id": ticket.id,
                "user_name": user_name or platform_user_id,
                "purchase_date": ticket.purchase_date,
                "status": ticket.status.value,
            })
        return tickets
