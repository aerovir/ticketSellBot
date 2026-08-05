import uuid
from datetime import datetime, timezone
import secrets

from sqlalchemy import String, Integer, Numeric, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

import enum


class SubscriptionTier(str, enum.Enum):
    """Уровень подписки канала."""
    basic = "basic"  # только бесплатные мероприятия, короткий код
    pro = "pro"      # платные мероприятия + QR


class TicketStatus(str, enum.Enum):
    active = "active"
    checked_in = "checked_in"
    refunded = "refunded"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    refunded = "refunded"


class PlatformType(str, enum.Enum):
    telegram = "telegram"
    vk = "vk"
    max = "max"


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_channel_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_telegram_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    is_subscription_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_tier: Mapped[SubscriptionTier] = mapped_column(
        SAEnum(SubscriptionTier), default=SubscriptionTier.basic, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    events = relationship("Event", back_populates="channel", lazy="raise")
    admins = relationship("ChannelAdmin", back_populates="channel", lazy="raise", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Channel {self.telegram_channel_id}>"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    platform: Mapped[PlatformType] = mapped_column(
        SAEnum(PlatformType), nullable=False
    )
    platform_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tickets = relationship("Ticket", back_populates="user", lazy="raise")

    def __repr__(self):
        return f"<User {self.platform}:{self.platform_user_id}>"


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float] = mapped_column(Numeric(precision=10, scale=2), nullable=False, default=0.0)
    total_tickets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_tickets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    media_telegram_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "photo" или "video"
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invites_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tickets = relationship("Ticket", back_populates="event", lazy="raise")
    channel = relationship("Channel", back_populates="events", lazy="raise")

    def __repr__(self):
        return f"<Event {self.title}>"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False
    )
    # user_id nullable: пригласительные (is_invite=True) не привязаны к пользователю
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    purchase_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus), default=TicketStatus.active, nullable=False
    )
    validation_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_invite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    invited_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qr_code_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

    event = relationship("Event", back_populates="tickets", lazy="raise")
    user = relationship("User", back_populates="tickets", lazy="raise")
    payment = relationship("Payment", back_populates="ticket", uselist=False, lazy="raise")

    def __repr__(self):
        return f"<Ticket {self.id} — {self.event_id}>"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False, unique=True
    )
    amount: Mapped[float] = mapped_column(Numeric(precision=10, scale=2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus), default=PaymentStatus.pending, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    ticket = relationship("Ticket", back_populates="payment", lazy="raise")

    def __repr__(self):
        return f"<Payment {self.id} — {self.status.value}>"


class ChannelAdmin(Base):
    __tablename__ = "channel_admins"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    telegram_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    channel = relationship("Channel", back_populates="admins", lazy="raise")

    __table_args__ = (UniqueConstraint("channel_id", "telegram_user_id", name="uq_channel_admin"),)

    def __repr__(self):
        return f"<ChannelAdmin {self.channel_id}:{self.telegram_user_id}>"
