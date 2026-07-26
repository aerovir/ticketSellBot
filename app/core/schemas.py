from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel, Field

from app.core.models import SubscriptionTier


# ─── User ────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    platform: str
    platform_user_id: str
    name: Optional[str] = None


class UserOut(BaseModel):
    id: UUID
    platform: str
    platform_user_id: str
    name: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Event ───────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    date: datetime
    location: Optional[str] = None
    price: float = Field(default=0.0, ge=0)
    total_tickets: int = Field(default=0, ge=0)
    available_tickets: int = Field(default=0, ge=0)
    channel_id: UUID


class EventOut(BaseModel):
    id: UUID
    channel_id: UUID
    title: str
    description: Optional[str]
    date: datetime
    location: Optional[str]
    price: float
    total_tickets: int
    available_tickets: int
    is_active: bool
    is_free: bool

    model_config = {"from_attributes": True}


class EventShortOut(BaseModel):
    """Short version for event listings."""
    id: UUID
    channel_id: UUID
    title: str
    date: datetime
    location: Optional[str]
    price: float
    available_tickets: int

    model_config = {"from_attributes": True}


# ─── Channel ─────────────────────────────────────────────────────────────────

class ChannelCreate(BaseModel):
    telegram_channel_id: str
    title: Optional[str] = None
    admin_telegram_user_id: str


class ChannelOut(BaseModel):
    id: UUID
    telegram_channel_id: str
    title: Optional[str]
    admin_telegram_user_id: str
    is_subscription_active: bool
    subscription_until: Optional[datetime]
    subscription_tier: SubscriptionTier = SubscriptionTier.basic
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Ticket ──────────────────────────────────────────────────────────────────

class TicketOut(BaseModel):
    id: UUID
    event_id: UUID
    event_title: str = ""
    purchase_date: datetime
    status: str
    validation_code: Optional[str] = None
    checked_in_at: Optional[datetime] = None
    is_free: bool = False

    model_config = {"from_attributes": True}


# ─── Payment ─────────────────────────────────────────────────────────────────

class PaymentOut(BaseModel):
    id: UUID
    ticket_id: UUID
    amount: float
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
