import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Numeric, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

import enum


class TicketStatus(str, enum.Enum):
    active = "active"
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
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float] = mapped_column(Numeric(precision=10, scale=2), nullable=False, default=0.0)
    total_tickets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_tickets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tickets = relationship("Ticket", back_populates="event", lazy="raise")

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
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    purchase_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus), default=TicketStatus.active, nullable=False
    )

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
