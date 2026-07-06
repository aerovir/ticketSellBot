from datetime import datetime
from uuid import UUID
from typing import Optional

from pydantic import BaseModel, Field


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


class EventOut(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    date: datetime
    location: Optional[str]
    price: float
    total_tickets: int
    available_tickets: int
    is_active: bool

    model_config = {"from_attributes": True}


class EventShortOut(BaseModel):
    """Short version for event listings."""
    id: UUID
    title: str
    date: datetime
    location: Optional[str]
    price: float
    available_tickets: int

    model_config = {"from_attributes": True}


# ─── Ticket ──────────────────────────────────────────────────────────────────

class TicketOut(BaseModel):
    id: UUID
    event_id: UUID
    event_title: str = ""
    purchase_date: datetime
    status: str

    model_config = {"from_attributes": True}


# ─── Payment ─────────────────────────────────────────────────────────────────

class PaymentOut(BaseModel):
    id: UUID
    ticket_id: UUID
    amount: float
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
