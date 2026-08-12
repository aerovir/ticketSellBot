from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel, Field

from app.core.models import SubscriptionTier, PeriodUnit, PlatformType


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
    channel_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    invites_quota: int = Field(default=0, ge=0)


class EventUpdateIn(BaseModel):
    """Partial update for an event (all fields optional)."""
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[datetime] = None
    location: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    total_tickets: Optional[int] = Field(default=None, ge=0)
    invites_quota: Optional[int] = Field(default=None, ge=0)


class InviteIssueIn(BaseModel):
    """Выдать пригласительный: вместимость 1/2/3 человека."""
    seats: int = Field(default=1, ge=1, le=3)


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


# ─── Admin Panel ─────────────────────────────────────────────────────────────

class SubscribeIn(BaseModel):
    duration_days: int = Field(default=30, gt=0)
    tier: SubscriptionTier = SubscriptionTier.basic


class ChangeAdminIn(BaseModel):
    new_admin_id: str


class CheckInIn(BaseModel):
    code: str


class MeUpdateIn(BaseModel):
    name: Optional[str] = None


class ChannelSubscribeIn(BaseModel):
    """Создать канал (если нет) и активировать подписку."""
    telegram_channel_id: str  # @username или числовой ID
    title: Optional[str] = None
    duration_days: int = Field(default=30, gt=0)
    tier: SubscriptionTier = SubscriptionTier.basic


class BroadcastIn(BaseModel):
    text: str


class UpdateSubscriptionIn(BaseModel):
    """Сменить подписку канала: тип + срок (дни/месяцы/годы)."""
    tier: SubscriptionTier
    period: int = Field(gt=0)
    period_unit: PeriodUnit = PeriodUnit.months


class ChangeTierIn(BaseModel):
    """Сменить только тип подписки (срок не меняется)."""
    tier: SubscriptionTier


class SubscribeMeIn(BaseModel):
    """Покупка/активация подписки пользователя."""
    tier: SubscriptionTier = SubscriptionTier.basic


class ChannelRegisterIn(BaseModel):
    """Связать Telegram-канал с пользователем (без активации подписки)."""
    telegram_channel_id: str   # @username или числовой ID
    title: Optional[str] = None


class LinkCodeIn(BaseModel):
    """Создать одноразовый код привязки площадки (organizer-only)."""
    target_platform: PlatformType
    ttl_minutes: int = Field(default=10, ge=1, le=60)


class LinkConsumeIn(BaseModel):
    """Ввести код привязки на целевой площадке (VK-сторона)."""
    code: str


class AddManagerIn(BaseModel):
    """Добавить соработника мероприятия по платформенному ID."""
    platform: PlatformType
    platform_user_id: str


class VKGroupRegisterIn(BaseModel):
    """Зарегистрировать VK-группу как цель публикации (self-service)."""
    group_id: str  # VK community id (число или -id)
    title: Optional[str] = None
    community_token: Optional[str] = None  # от VKWebAppGetCommunityToken, шифруется


class PublishIn(BaseModel):
    """Публикация мероприятия: цель — TG-канал (channel_id) или VK-группа (vk_group_id)."""
    channel_id: Optional[UUID] = None
    vk_group_id: Optional[str] = None


# ─── Payment ─────────────────────────────────────────────────────────────────

class PaymentOut(BaseModel):
    id: UUID
    ticket_id: UUID
    amount: float
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Per-event premium (единовременная оплата) ───────────────────

class EventPremiumIn(BaseModel):
    """Покупка премиума на одно мероприятие (stub-оплата)."""
    amount: float = 0
    provider: Optional[str] = None
