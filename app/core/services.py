import uuid
import logging
import time
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import User, Event, Ticket, Payment, Channel, ChannelAdmin, TicketStatus, PaymentStatus, PlatformType, SubscriptionTier
from app.core.schemas import EventOut, EventShortOut, TicketOut, UserOut

logger = logging.getLogger("ticketbot.services")


def _ms(start: float) -> int:
    """Convert perf_counter start to integer milliseconds."""
    return int((time.perf_counter() - start) * 1000)


# ─── User Service ────────────────────────────────────────────────────────────

class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, platform: PlatformType, platform_user_id: str, name: Optional[str] = None) -> User:
        """Find existing user by platform+id, or create a new one."""
        start = time.perf_counter()
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
            logger.info("", extra={
                "event_type": "user.created",
                "platform": platform.value,
                "user_id": platform_user_id,
                "status": "success",
                "duration_ms": _ms(start),
            })
        else:
            logger.info("", extra={
                "event_type": "user.found",
                "platform": platform.value,
                "user_id": platform_user_id,
                "status": "success",
                "duration_ms": _ms(start),
            })

        return user

    async def get_by_platform_user_id(self, platform: PlatformType, platform_user_id: str) -> User | None:
        """Find a user by platform+id WITHOUT creating (unlike get_or_create).

        Used for admin lookups — do not create a side-effect user on view.
        """
        stmt = select(User).where(
            and_(User.platform == platform, User.platform_user_id == platform_user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_name(self, user_id: uuid.UUID, name: str | None) -> User | None:
        """Update a user's display name. Returns updated user or None."""
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        user.name = name
        await self.session.flush()
        return user


# ─── Channel Service ─────────────────────────────────────────────────────────

class ChannelService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_channel_id: str) -> Channel | None:
        """Look up a channel by its Telegram chat_id or @username."""
        start = time.perf_counter()
        stmt = select(Channel).where(Channel.telegram_channel_id == telegram_channel_id)
        result = await self.session.execute(stmt)
        channel = result.scalar_one_or_none()
        logger.info("", extra={
            "event_type": "channel.get_by_telegram_id",
            "telegram_channel_id": telegram_channel_id,
            "found": channel is not None,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channel

    async def get_by_id(self, channel_id: uuid.UUID) -> Channel | None:
        """Look up a channel by its UUID."""
        start = time.perf_counter()
        channel = await self.session.get(Channel, channel_id)
        logger.info("", extra={
            "event_type": "channel.get_by_id",
            "channel_id": str(channel_id),
            "found": channel is not None,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channel

    async def create(
        self,
        telegram_channel_id: str,
        admin_telegram_user_id: str,
        title: str | None = None,
    ) -> Channel:
        """Create a new channel record."""
        start = time.perf_counter()
        channel = Channel(
            telegram_channel_id=telegram_channel_id,
            title=title,
            admin_telegram_user_id=admin_telegram_user_id,
            is_subscription_active=False,
        )
        self.session.add(channel)
        await self.session.flush()
        logger.info("", extra={
            "event_type": "channel.created",
            "channel_id": str(channel.id),
            "telegram_channel_id": telegram_channel_id,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channel

    async def activate_subscription(
        self,
        channel_id: uuid.UUID,
        duration_days: int = 30,
        tier: SubscriptionTier | None = None,
    ) -> Channel | None:
        """Manually activate subscription for a channel.

        Args:
            channel_id: UUID канала.
            duration_days: Срок подписки в днях.
            tier: Уровень подписки (basic/pro). Если None — остаётся текущий.
        """
        start = time.perf_counter()
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            logger.warning("", extra={
                "event_type": "subscription.activate_failed",
                "channel_id": str(channel_id),
                "status": "error",
                "error": "Channel not found",
                "duration_ms": _ms(start),
            })
            return None
        channel.is_subscription_active = True
        channel.subscription_until = datetime.now(timezone.utc) + timedelta(days=duration_days)
        if tier is not None:
            channel.subscription_tier = tier
        await self.session.flush()
        logger.info("", extra={
            "event_type": "subscription.activated",
            "channel_id": str(channel.id),
            "telegram_channel_id": channel.telegram_channel_id,
            "duration_days": duration_days,
            "tier": channel.subscription_tier.value,
            "subscription_until": channel.subscription_until.isoformat(),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channel

    async def deactivate_subscription(self, channel_id: uuid.UUID) -> Channel | None:
        """Deactivate subscription."""
        start = time.perf_counter()
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            logger.warning("", extra={
                "event_type": "subscription.deactivate_failed",
                "channel_id": str(channel_id),
                "status": "error",
                "error": "Channel not found",
                "duration_ms": _ms(start),
            })
            return None
        channel.is_subscription_active = False
        channel.subscription_until = None
        await self.session.flush()
        logger.info("", extra={
            "event_type": "subscription.deactivated",
            "channel_id": str(channel.id),
            "telegram_channel_id": channel.telegram_channel_id,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channel

    async def is_subscription_valid(self, channel_id: uuid.UUID) -> bool:
        """Check if the channel has an active, non-expired subscription."""
        start = time.perf_counter()
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            logger.info("", extra={
                "event_type": "channel.subscription_check",
                "channel_id": str(channel_id),
                "valid": False,
                "reason": "not_found",
                "status": "success",
                "duration_ms": _ms(start),
            })
            return False
        if not channel.is_subscription_active:
            logger.info("", extra={
                "event_type": "channel.subscription_check",
                "channel_id": str(channel_id),
                "valid": False,
                "reason": "not_active",
                "status": "success",
                "duration_ms": _ms(start),
            })
            return False
        if channel.subscription_until and channel.subscription_until < datetime.now(timezone.utc):
            # Auto-deactivate expired subscriptions
            channel.is_subscription_active = False
            channel.subscription_until = None
            await self.session.flush()
            logger.info("", extra={
                "event_type": "subscription.auto_expired",
                "channel_id": str(channel.id),
                "telegram_channel_id": channel.telegram_channel_id,
                "status": "success",
                "duration_ms": _ms(start),
            })
            return False
        logger.info("", extra={
            "event_type": "channel.subscription_check",
            "channel_id": str(channel_id),
            "valid": True,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return True

    async def get_subscription_tier(self, channel_id: uuid.UUID) -> SubscriptionTier | None:
        """Получить уровень подписки канала."""
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            return None
        return channel.subscription_tier

    async def require_feature(self, channel_id: uuid.UUID, feature: str) -> bool:
        """Проверить, поддерживает ли канал указанную фичу.

        Args:
            channel_id: UUID канала.
            feature: Название фичи ('free_events', 'paid_events', 'qr_codes', 'promo_codes').

        Returns:
            True если фича доступна, False если нет.
        """
        if not await self.is_subscription_valid(channel_id):
            return False

        tier = await self.get_subscription_tier(channel_id)
        if tier is None:
            return False

        # Матрица фич по уровням подписки
        FEATURES = {
            "free_events": {SubscriptionTier.basic, SubscriptionTier.pro},
            "paid_events": {SubscriptionTier.pro},
            "qr_codes": {SubscriptionTier.pro},
        }

        return tier in FEATURES.get(feature, set())

    async def get_active_unassigned_channel(self) -> Channel | None:
        """Get a channel with active subscription but no admin assigned."""
        start = time.perf_counter()
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
        channel = result.scalar_one_or_none()
        logger.info("", extra={
            "event_type": "channel.get_active_unassigned",
            "found": channel is not None,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channel

    async def get_channel_ids_by_admin(self, telegram_user_id: str) -> list[uuid.UUID]:
        """Получить ID всех каналов, где пользователь — админ (из channel_admins)."""
        start = time.perf_counter()
        stmt = select(ChannelAdmin.channel_id).where(ChannelAdmin.telegram_user_id == telegram_user_id)
        result = await self.session.execute(stmt)
        ids = list(result.scalars().all())
        logger.info("", extra={
            "event_type": "channel.get_ids_by_admin",
            "admin_id": telegram_user_id,
            "count": len(ids),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return ids

    async def get_channels_by_admin(self, telegram_user_id: str) -> list[Channel]:
        """Получить все каналы, где пользователь — админ (через channel_admins)."""
        start = time.perf_counter()
        channel_ids = await self.get_channel_ids_by_admin(telegram_user_id)
        if not channel_ids:
            logger.info("", extra={
                "event_type": "channel.get_channels_by_admin",
                "admin_id": telegram_user_id,
                "count": 0,
                "status": "success",
                "duration_ms": _ms(start),
            })
            return []
        stmt = select(Channel).where(Channel.id.in_(channel_ids))
        result = await self.session.execute(stmt)
        channels = list(result.scalars().all())
        logger.info("", extra={
            "event_type": "channel.get_channels_by_admin",
            "admin_id": telegram_user_id,
            "count": len(channels),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channels

    async def change_admin(self, channel_telegram_id: str, new_admin_id: str) -> tuple[Channel, list[str]]:
        """Сменить администратора канала.

        Обновляет channel_admins (M2M) и legacy-поле admin_telegram_user_id.
        Использует ChannelAdminService внутренне для синхронизации.

        Args:
            channel_telegram_id: @username или ID канала.
            new_admin_id: Telegram ID нового администратора.

        Returns:
            tuple[Channel, list[str]]: (канал, список старых admin_id).

        Raises:
            ValueError: если канал с таким channel_telegram_id не найден.
        """
        start = time.perf_counter()
        channel = await self.get_by_telegram_id(channel_telegram_id)
        if not channel:
            logger.warning("", extra={
                "event_type": "channel.change_admin_failed",
                "telegram_channel_id": channel_telegram_id,
                "new_admin_id": new_admin_id,
                "status": "error",
                "error": "Channel not found",
                "duration_ms": _ms(start),
            })
            raise ValueError(f"Канал {channel_telegram_id} не найден")

        admin_svc = ChannelAdminService(self.session)
        old_admin_ids = await admin_svc.get_admin_ids(channel.id)
        await admin_svc.sync_admins(channel.id, [new_admin_id])
        channel.admin_telegram_user_id = new_admin_id
        await self.session.flush()

        logger.info("", extra={
            "event_type": "channel.admin_changed",
            "channel_id": str(channel.id),
            "telegram_channel_id": channel.telegram_channel_id,
            "old_admin_ids": old_admin_ids,
            "new_admin_id": new_admin_id,
            "status": "success",
            "duration_ms": _ms(start),
        })

        return channel, old_admin_ids

    async def list_all(self) -> list[Channel]:
        """Get all channels, newest first (super-admin view)."""
        start = time.perf_counter()
        stmt = select(Channel).order_by(Channel.created_at.desc())
        result = await self.session.execute(stmt)
        channels = list(result.scalars().all())
        logger.info("", extra={
            "event_type": "channel.list_all",
            "count": len(channels),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return channels

    async def get_channel_summary(self, channel_id: uuid.UUID) -> dict | None:
        """Aggregated channel info for the admin panel.

        Returns dict with channel fields + admins, events_count,
        upcoming_count, tickets_sold; None if channel missing.
        """
        channel = await self.session.get(Channel, channel_id)
        if channel is None:
            return None

        now = datetime.now(timezone.utc)

        events_result = await self.session.execute(
            select(func.count()).select_from(Event).where(Event.channel_id == channel.id)
        )
        events_count = events_result.scalar() or 0

        upcoming_result = await self.session.execute(
            select(func.count()).select_from(Event).where(
                and_(Event.channel_id == channel.id, Event.date >= now)
            )
        )
        upcoming = upcoming_result.scalar() or 0

        tickets_result = await self.session.execute(
            select(func.count()).select_from(Ticket)
            .join(Event, Ticket.event_id == Event.id)
            .where(Event.channel_id == channel.id, Ticket.status == TicketStatus.active)
        )
        tickets_sold = tickets_result.scalar() or 0

        admin_svc = ChannelAdminService(self.session)
        admins = await admin_svc.get_admin_ids(channel.id)

        return {
            "id": str(channel.id),
            "telegram_channel_id": channel.telegram_channel_id,
            "title": channel.title,
            "admin_telegram_user_id": channel.admin_telegram_user_id,
            "is_subscription_active": channel.is_subscription_active,
            "subscription_until": channel.subscription_until.isoformat() if channel.subscription_until else None,
            "subscription_tier": channel.subscription_tier.value,
            "admins": admins,
            "events_count": events_count,
            "upcoming_count": upcoming,
            "tickets_sold": tickets_sold,
        }


# ─── Channel Admin Service ──────────────────────────────────────────────────

class ChannelAdminService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_admin_ids(self, channel_id: uuid.UUID) -> list[str]:
        """Получить список Telegram ID админов канала."""
        start = time.perf_counter()
        stmt = select(ChannelAdmin.telegram_user_id).where(ChannelAdmin.channel_id == channel_id)
        result = await self.session.execute(stmt)
        ids = list(result.scalars().all())
        logger.info("", extra={
            "event_type": "channel_admin.get_ids",
            "channel_id": str(channel_id),
            "count": len(ids),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return ids

    async def sync_admins(self, channel_id: uuid.UUID, admin_ids: list[str]):
        """Синхронизировать список админов канала с Telegram.

        Удаляет отсутствующих, добавляет новых, существующих не трогает.
        """
        start = time.perf_counter()
        existing = await self.get_admin_ids(channel_id)
        existing_set = set(existing)
        new_set = set(admin_ids)

        # Добавить новых
        added = []
        for uid in new_set - existing_set:
            self.session.add(ChannelAdmin(channel_id=channel_id, telegram_user_id=uid))
            added.append(uid)

        # Удалить отсутствующих
        removed = []
        to_remove = existing_set - new_set
        if to_remove:
            removed = list(to_remove)
            stmt = delete(ChannelAdmin).where(
                ChannelAdmin.channel_id == channel_id,
                ChannelAdmin.telegram_user_id.in_(to_remove),
            )
            await self.session.execute(stmt)

        await self.session.flush()

        if added or removed:
            logger.info("", extra={
                "event_type": "channel_admins.synced",
                "channel_id": str(channel_id),
                "added": added,
                "removed": removed,
                "status": "success",
                "duration_ms": _ms(start),
            })

    async def user_is_admin(self, channel_id: uuid.UUID, telegram_user_id: str) -> bool:
        """Проверить, является ли пользователь админом канала."""
        start = time.perf_counter()
        stmt = select(ChannelAdmin).where(
            ChannelAdmin.channel_id == channel_id,
            ChannelAdmin.telegram_user_id == telegram_user_id,
        ).limit(1)
        result = await self.session.execute(stmt)
        is_admin = result.scalar_one_or_none() is not None
        logger.info("", extra={
            "event_type": "channel_admin.user_is_admin",
            "channel_id": str(channel_id),
            "user_id": telegram_user_id,
            "is_admin": is_admin,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return is_admin

    async def remove_admin(self, channel_id: uuid.UUID, telegram_user_id: str):
        """Удалить пользователя из админов канала."""
        start = time.perf_counter()
        stmt = delete(ChannelAdmin).where(
            ChannelAdmin.channel_id == channel_id,
            ChannelAdmin.telegram_user_id == telegram_user_id,
        )
        await self.session.execute(stmt)
        await self.session.flush()
        logger.info("", extra={
            "event_type": "channel_admin.removed",
            "channel_id": str(channel_id),
            "user_id": telegram_user_id,
            "status": "success",
            "duration_ms": _ms(start),
        })


# ─── Event Service ───────────────────────────────────────────────────────────

class EventService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_upcoming(self, channel_id: uuid.UUID | None = None) -> list[Event]:
        """Get all active, published events that haven't passed yet, optionally filtered by channel."""
        start = time.perf_counter()
        now = datetime.now(timezone.utc)
        stmt = (
            select(Event)
            .where(
                and_(Event.is_active == True, Event.is_published == True, Event.date >= now)
            )
            .order_by(Event.date.asc())
        )
        if channel_id is not None:
            stmt = stmt.where(Event.channel_id == channel_id)
        result = await self.session.execute(stmt)
        events = list(result.scalars().all())
        logger.info("", extra={
            "event_type": "event.list_upcoming",
            "channel_id": str(channel_id) if channel_id else "all",
            "count": len(events),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return events

    async def get_by_id(self, event_id: uuid.UUID, channel_id: uuid.UUID | None = None) -> Event | None:
        """Get event by ID, optionally scoped to a channel."""
        start = time.perf_counter()
        stmt = select(Event).where(Event.id == event_id)
        if channel_id is not None:
            stmt = stmt.where(Event.channel_id == channel_id)
        result = await self.session.execute(stmt)
        event = result.scalar_one_or_none()
        logger.info("", extra={
            "event_type": "event.get_by_id",
            "event_id": str(event_id),
            "found": event is not None,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return event

    async def create(self, title: str, description: Optional[str], date: datetime,
                     location: Optional[str], price: float,
                     total_tickets: int, channel_id: uuid.UUID) -> Event:
        start = time.perf_counter()

        # Проверка: если мероприятие платное, канал должен иметь Pro-подписку
        if price > 0:
            channel_svc = ChannelService(self.session)
            if not await channel_svc.require_feature(channel_id, "paid_events"):
                raise ValueError(
                    "Ваш тариф поддерживает только бесплатные мероприятия. "
                    "Для платных мероприятий необходима подписка Pro."
                )

        is_free = (price == 0)
        event = Event(
            title=title,
            description=description,
            date=date,
            location=location,
            price=price,
            total_tickets=total_tickets,
            available_tickets=total_tickets,
            is_active=True,
            is_free=is_free,
            channel_id=channel_id,
        )
        self.session.add(event)
        await self.session.flush()
        logger.info("", extra={
            "event_type": "event.created",
            "event_id": str(event.id),
            "event_title": title,
            "channel_id": str(channel_id),
            "price": price,
            "total_tickets": total_tickets,
            "is_free": is_free,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return event

    # ─── Admin methods ───────────────────────────────────────────────────

    async def list_all(self, channel_id: uuid.UUID | None = None) -> list[Event]:
        """Get ALL events that are not deleted, newest first.
        Optionally filtered by channel."""
        start = time.perf_counter()
        stmt = select(Event).where(Event.deleted_at.is_(None)).order_by(Event.date.desc())
        if channel_id is not None:
            stmt = stmt.where(Event.channel_id == channel_id)
        result = await self.session.execute(stmt)
        events = list(result.scalars().all())
        logger.info("", extra={
            "event_type": "event.list_all",
            "channel_id": str(channel_id) if channel_id else "all",
            "count": len(events),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return events

    async def update(self, event_id: uuid.UUID, **data) -> Event | None:
        """Partially update an event. Returns updated event or None."""
        start = time.perf_counter()
        event = await self.session.get(Event, event_id)
        if event is None:
            logger.warning("", extra={
                "event_type": "event.update_failed",
                "event_id": str(event_id),
                "status": "error",
                "error": "Event not found",
                "duration_ms": _ms(start),
            })
            return None

        changed = {}
        for key, value in data.items():
            if hasattr(event, key):
                old = getattr(event, key)
                if old != value:
                    changed[key] = {"from": str(old), "to": str(value)}
                setattr(event, key, value)

        # Sync available_tickets when total_tickets changes
        if "total_tickets" in data:
            old_total = event.total_tickets
            new_total = data["total_tickets"]
            diff = new_total - old_total
            event.available_tickets = max(0, event.available_tickets + diff)

        await self.session.flush()
        logger.info("", extra={
            "event_type": "event.updated",
            "event_id": str(event.id),
            "event_title": event.title,
            "changed": changed,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return event

    async def set_active(self, event_id: uuid.UUID, is_active: bool) -> Event | None:
        """Enable or disable an event. Returns updated event or None."""
        start = time.perf_counter()
        event = await self.session.get(Event, event_id)
        if event is None:
            logger.warning("", extra={
                "event_type": "event.toggle_failed",
                "event_id": str(event_id),
                "status": "error",
                "error": "Event not found",
                "duration_ms": _ms(start),
            })
            return None
        event.is_active = is_active
        await self.session.flush()
        logger.info("", extra={
            "event_type": "event.toggled",
            "event_id": str(event.id),
            "event_title": event.title,
            "is_active": is_active,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return event

    async def soft_delete(self, event_id: uuid.UUID) -> Event | None:
        """Soft delete an event — hides it from all lists.
        Sets is_active=False and deleted_at=now()."""
        start = time.perf_counter()
        event = await self.session.get(Event, event_id)
        if event is None:
            logger.warning("", extra={
                "event_type": "event.delete_failed",
                "event_id": str(event_id),
                "status": "error",
                "error": "Event not found",
                "duration_ms": _ms(start),
            })
            return None
        event.is_active = False
        event.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        logger.info("", extra={
            "event_type": "event.deleted",
            "event_id": str(event.id),
            "event_title": event.title,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return event

    async def get_event_stats(self, event_id: uuid.UUID) -> dict:
        """Get sales stats for an event."""
        start = time.perf_counter()
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

        logger.info("", extra={
            "event_type": "event.get_stats",
            "event_id": str(event_id),
            "total_tickets": event.total_tickets,
            "sold": sold,
            "refunded": refunded,
            "revenue": revenue,
            "status": "success",
            "duration_ms": _ms(start),
        })

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

    @staticmethod
    async def generate_validation_code() -> str:
        """Сгенерировать уникальный короткий код для входа.

        Формат: XXXX-XXXX (hex, 8 символов + дефис).
        Пример: AB3X-K7M9
        """
        raw = secrets.token_hex(4).upper()
        return f"{raw[:4]}-{raw[4:]}"

    async def buy_ticket(self, user_id: uuid.UUID, event_id: uuid.UUID) -> Ticket:
        """Purchase a ticket for an event."""
        start = time.perf_counter()
        event = await self.session.get(Event, event_id)
        if event is None:
            logger.warning("", extra={
                "event_type": "ticket.purchase_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "status": "error",
                "error": "Event not found",
                "duration_ms": _ms(start),
            })
            raise ValueError("Мероприятие не найдено")
        if not event.is_active:
            logger.warning("", extra={
                "event_type": "ticket.purchase_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Event not active",
                "duration_ms": _ms(start),
            })
            raise ValueError("Мероприятие неактивно")
        if event.date < datetime.now(timezone.utc):
            logger.warning("", extra={
                "event_type": "ticket.purchase_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Event already passed",
                "duration_ms": _ms(start),
            })
            raise ValueError("Мероприятие уже прошло")
        if event.available_tickets <= 0:
            logger.warning("", extra={
                "event_type": "ticket.purchase_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Sold out",
                "duration_ms": _ms(start),
            })
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
            logger.warning("", extra={
                "event_type": "ticket.purchase_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Already has ticket",
                "duration_ms": _ms(start),
            })
            raise ValueError("У вас уже есть активный билет на это мероприятие")

        # Create ticket
        ticket = Ticket(
            id=uuid.uuid4(),  # явно, чтобы ticket.id не был None до flush
            event_id=event_id,
            user_id=user_id,
            status=TicketStatus.active,
            validation_code=await self.generate_validation_code(),
            is_free=event.is_free,
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

        logger.info("", extra={
            "event_type": "ticket.purchased",
            "ticket_id": str(ticket.id),
            "event_id": str(event_id),
            "event_title": event.title,
            "user_id": str(user_id),
            "amount": float(event.price),
            "is_free": ticket.is_free,
            "validation_code": ticket.validation_code,
            "payment_status": "completed",
            "platform": "telegram",
            "status": "success",
            "duration_ms": _ms(start),
        })
        return ticket

    async def buy_ticket_webapp(self, user_id: uuid.UUID, event_id: uuid.UUID) -> dict:
        """Purchase a ticket through the Mini App.

        Same validation as buy_ticket(), but creates Payment with
        status=pending (for future YooKassa integration) and returns
        a dict for the API response.
        """
        start = time.perf_counter()
        event = await self.session.get(Event, event_id)
        if event is None:
            logger.warning("", extra={
                "event_type": "ticket.purchase_webapp_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "status": "error",
                "error": "Event not found",
                "duration_ms": _ms(start),
            })
            raise ValueError("Мероприятие не найдено")
        if not event.is_active:
            logger.warning("", extra={
                "event_type": "ticket.purchase_webapp_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Event not active",
                "duration_ms": _ms(start),
            })
            raise ValueError("Мероприятие неактивно")
        if event.date < datetime.now(timezone.utc):
            logger.warning("", extra={
                "event_type": "ticket.purchase_webapp_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Event already passed",
                "duration_ms": _ms(start),
            })
            raise ValueError("Мероприятие уже прошло")
        if event.available_tickets <= 0:
            logger.warning("", extra={
                "event_type": "ticket.purchase_webapp_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Sold out",
                "duration_ms": _ms(start),
            })
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
            logger.warning("", extra={
                "event_type": "ticket.purchase_webapp_failed",
                "event_id": str(event_id),
                "user_id": str(user_id),
                "event_title": event.title,
                "status": "error",
                "error": "Already has ticket",
                "duration_ms": _ms(start),
            })
            raise ValueError("У вас уже есть активный билет на это мероприятие")

        # Create ticket
        ticket = Ticket(
            id=uuid.uuid4(),
            event_id=event_id,
            user_id=user_id,
            status=TicketStatus.active,
            validation_code=await self.generate_validation_code(),
            is_free=event.is_free,
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

        logger.info("", extra={
            "event_type": "ticket.purchased_webapp",
            "ticket_id": str(ticket.id),
            "event_id": str(event_id),
            "event_title": event.title,
            "user_id": str(user_id),
            "amount": float(event.price),
            "is_free": ticket.is_free,
            "validation_code": ticket.validation_code,
            "payment_status": "pending",
            "platform": "web",
            "status": "success",
            "duration_ms": _ms(start),
        })

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
        start = time.perf_counter()
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            logger.warning("", extra={
                "event_type": "ticket.cancel_failed",
                "ticket_id": str(ticket_id),
                "user_id": str(user_id),
                "status": "error",
                "error": "Ticket not found",
                "duration_ms": _ms(start),
            })
            raise ValueError("Билет не найден")
        if ticket.user_id != user_id:
            logger.warning("", extra={
                "event_type": "ticket.cancel_failed",
                "ticket_id": str(ticket_id),
                "user_id": str(user_id),
                "status": "error",
                "error": "Not owner",
                "duration_ms": _ms(start),
            })
            raise ValueError("Это не ваш билет")
        if ticket.status == TicketStatus.refunded:
            logger.warning("", extra={
                "event_type": "ticket.cancel_failed",
                "ticket_id": str(ticket_id),
                "user_id": str(user_id),
                "status": "error",
                "error": "Already refunded",
                "duration_ms": _ms(start),
            })
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

        logger.info("", extra={
            "event_type": "ticket.cancelled",
            "ticket_id": str(ticket_id),
            "event_id": str(ticket.event_id),
            "event_title": event.title if event else "",
            "user_id": str(user_id),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return ticket

    async def admin_cancel_ticket(self, ticket_id: uuid.UUID) -> Ticket:
        """Cancel any ticket by admin (no ownership check)."""
        start = time.perf_counter()
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            logger.warning("", extra={
                "event_type": "ticket.admin_cancel_failed",
                "ticket_id": str(ticket_id),
                "status": "error",
                "error": "Ticket not found",
                "duration_ms": _ms(start),
            })
            raise ValueError("Билет не найден")
        if ticket.status == TicketStatus.refunded:
            logger.warning("", extra={
                "event_type": "ticket.admin_cancel_failed",
                "ticket_id": str(ticket_id),
                "status": "error",
                "error": "Already refunded",
                "duration_ms": _ms(start),
            })
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

        logger.info("", extra={
            "event_type": "ticket.admin_cancelled",
            "ticket_id": str(ticket_id),
            "event_id": str(ticket.event_id),
            "event_title": event.title if event else "",
            "status": "success",
            "duration_ms": _ms(start),
        })
        return ticket

    async def get_user_tickets(self, user_id: uuid.UUID, channel_id: uuid.UUID | None = None) -> list[dict]:
        """Get all tickets for a user with event info, optionally filtered by channel."""
        start = time.perf_counter()
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
                "validation_code": ticket.validation_code,
                "checked_in_at": ticket.checked_in_at.isoformat() if ticket.checked_in_at else None,
                "is_free": ticket.is_free,
            })

        logger.info("", extra={
            "event_type": "ticket.get_user_tickets",
            "user_id": str(user_id),
            "channel_id": str(channel_id) if channel_id else None,
            "count": len(tickets),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return tickets

    # ─── Admin methods ───────────────────────────────────────────────────

    async def get_event_tickets(self, event_id: uuid.UUID) -> list[dict]:
        """Get all tickets for a specific event (admin view)."""
        start = time.perf_counter()
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
                "validation_code": ticket.validation_code,
                "checked_in_at": ticket.checked_in_at.isoformat() if ticket.checked_in_at else None,
                "checked_in_by": ticket.checked_in_by,
                "is_free": ticket.is_free,
            })

        logger.info("", extra={
            "event_type": "ticket.get_event_tickets",
            "event_id": str(event_id),
            "count": len(tickets),
            "status": "success",
            "duration_ms": _ms(start),
        })
        return tickets

    async def get_ticket_event(self, ticket_id: uuid.UUID) -> tuple[Ticket, Event] | None:
        """Load a ticket together with its event (for channel-scoping admin actions)."""
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            return None
        event = await self.session.get(Event, ticket.event_id)
        if event is None:
            return None
        return ticket, event

    async def export_event_tickets(self, event_id: uuid.UUID) -> list[dict]:
        """Full ticket rows for an event (CSV export)."""
        stmt = (
            select(Ticket, User.name, Event.title)
            .join(User, Ticket.user_id == User.id)
            .join(Event, Ticket.event_id == Event.id)
            .where(Ticket.event_id == event_id)
            .order_by(Ticket.purchase_date.desc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        tickets = []
        for ticket, user_name, event_title in rows:
            tickets.append({
                "ticket_id": str(ticket.id),
                "event_title": event_title,
                "user_name": user_name or "",
                "purchase_date": ticket.purchase_date.isoformat(),
                "status": ticket.status.value,
                "validation_code": ticket.validation_code or "",
                "checked_in_at": ticket.checked_in_at.isoformat() if ticket.checked_in_at else "",
                "checked_in_by": ticket.checked_in_by or "",
                "is_free": "да" if ticket.is_free else "нет",
            })
        return tickets

    # ─── Validation & Check-in ────────────────────────────────────────

    async def validate_ticket(self, code: str) -> dict:
        """Проверить билет по validation_code.

        Args:
            code: Код билета (формат XXXX-XXXX).

        Returns:
            dict с результатами проверки:
                found: bool — найден ли билет
                status: str — статус (active/checked_in/refunded/not_found)
                user_name: str — имя покупателя (если найден)
                event_title: str — название мероприятия
                already_checked_in: bool — уже ли использован
                checked_in_at: str|None — время чекина (если был)
        """
        start = time.perf_counter()
        stmt = (
            select(Ticket, User.name, Event.title)
            .join(User, Ticket.user_id == User.id)
            .join(Event, Ticket.event_id == Event.id)
            .where(Ticket.validation_code == code)
        )
        result = await self.session.execute(stmt)
        row = result.one_or_none()

        if row is None:
            logger.info("", extra={
                "event_type": "ticket.validate_not_found",
                "code": code,
                "status": "not_found",
                "duration_ms": _ms(start),
            })
            return {"found": False, "status": "not_found"}

        ticket, user_name, event_title = row

        result_data = {
            "found": True,
            "status": ticket.status.value,
            "user_name": user_name or "—",
            "event_title": event_title,
            "already_checked_in": ticket.status == TicketStatus.checked_in,
            "checked_in_at": ticket.checked_in_at.isoformat() if ticket.checked_in_at else None,
        }

        logger.info("", extra={
            "event_type": "ticket.validate",
            "ticket_id": str(ticket.id),
            "code": code,
            "status": ticket.status.value,
            "duration_ms": _ms(start),
        })
        return result_data

    async def check_in(self, ticket_id: uuid.UUID, admin_id: str) -> Ticket:
        """Отметить билет как использованный на входе.

        Args:
            ticket_id: UUID билета.
            admin_id: Telegram ID проверяющего.

        Returns:
            Ticket с обновлённым статусом.

        Raises:
            ValueError: если билет не найден, уже использован или возвращён.
        """
        start = time.perf_counter()
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            logger.warning("", extra={
                "event_type": "ticket.checkin_failed",
                "ticket_id": str(ticket_id),
                "status": "error",
                "error": "Ticket not found",
                "duration_ms": _ms(start),
            })
            raise ValueError("Билет не найден")

        if ticket.status == TicketStatus.checked_in:
            logger.warning("", extra={
                "event_type": "ticket.checkin_failed",
                "ticket_id": str(ticket_id),
                "status": "error",
                "error": "Already checked in",
                "checked_in_at": ticket.checked_in_at.isoformat() if ticket.checked_in_at else "",
                "duration_ms": _ms(start),
            })
            raise ValueError(f"Билет уже использован (вход: {ticket.checked_in_at.strftime('%H:%M')})")

        if ticket.status == TicketStatus.refunded:
            logger.warning("", extra={
                "event_type": "ticket.checkin_failed",
                "ticket_id": str(ticket_id),
                "status": "error",
                "error": "Ticket refunded",
                "duration_ms": _ms(start),
            })
            raise ValueError("Билет возвращён")

        ticket.status = TicketStatus.checked_in
        ticket.checked_in_at = datetime.now(timezone.utc)
        ticket.checked_in_by = admin_id
        await self.session.flush()

        logger.info("", extra={
            "event_type": "ticket.checked_in",
            "ticket_id": str(ticket.id),
            "event_id": str(ticket.event_id),
            "user_id": str(ticket.user_id),
            "admin_id": admin_id,
            "status": "success",
            "duration_ms": _ms(start),
        })
        return ticket

    async def check_in_by_code(self, code: str, admin_id: str) -> Ticket:
        """Отметить билет по validation_code.

        Args:
            code: Код билета (XXXX-XXXX).
            admin_id: Telegram ID проверяющего.

        Returns:
            Ticket с обновлённым статусом.

        Raises:
            ValueError: если билет с таким кодом не найден.
        """
        stmt = select(Ticket).where(Ticket.validation_code == code)
        result = await self.session.execute(stmt)
        ticket = result.scalar_one_or_none()
        if ticket is None:
            raise ValueError(f"Билет с кодом {code} не найден")
        return await self.check_in(ticket.id, admin_id)


# ─── Stats Service ──────────────────────────────────────────────────────────

class StatsService:
    """Aggregated statistics for the admin panel (super-admin)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_global_stats(self) -> dict:
        """Global counts across all tenants (mirrors bot sa_stats_all)."""
        start = time.perf_counter()
        users_count = (await self.session.execute(
            select(func.count()).select_from(User)
        )).scalar() or 0

        channels_count = (await self.session.execute(
            select(func.count()).select_from(Channel)
        )).scalar() or 0

        active_subs = (await self.session.execute(
            select(func.count()).select_from(Channel).where(Channel.is_subscription_active == True)
        )).scalar() or 0

        events_count = (await self.session.execute(
            select(func.count()).select_from(Event)
        )).scalar() or 0

        upcoming_count = (await self.session.execute(
            select(func.count()).select_from(Event).where(Event.date >= datetime.now(timezone.utc))
        )).scalar() or 0

        tickets_active = (await self.session.execute(
            select(func.count()).select_from(Ticket).where(Ticket.status == TicketStatus.active)
        )).scalar() or 0

        revenue = float((await self.session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.status == PaymentStatus.completed)
        )).scalar() or 0)

        logger.info("", extra={
            "event_type": "stats.global",
            "users": users_count,
            "channels": channels_count,
            "active_subs": active_subs,
            "events": events_count,
            "upcoming": upcoming_count,
            "tickets_active": tickets_active,
            "revenue": revenue,
            "status": "success",
            "duration_ms": _ms(start),
        })

        return {
            "users_count": users_count,
            "channels_count": channels_count,
            "active_subs": active_subs,
            "events_count": events_count,
            "upcoming_count": upcoming_count,
            "tickets_active": tickets_active,
            "revenue": revenue,
        }
