"""
REST API endpoints for Telegram Mini App.

All endpoints (except health) require initData validation.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.database import async_session_factory
from app.core.models import PlatformType
from app.core.services import EventService, TicketService, UserService
from app.web.dependencies import validate_init_data

logger = logging.getLogger("ticketbot.web.routes")
router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# Events
# ═══════════════════════════════════════════════════════════════


@router.get("/events")
async def list_events(
    auth_data: dict = Depends(validate_init_data),
    channel_id: str | None = None,
):
    """Get list of upcoming events, optionally filtered by channel."""
    async with async_session_factory() as session:
        svc = EventService(session)
        if channel_id:
            try:
                cid = UUID(channel_id)
            except ValueError:
                cid = None
            events = await svc.list_upcoming(channel_id=cid)
        else:
            events = await svc.list_upcoming()

    return [
        {
            "id": str(e.id),
            "title": e.title,
            "date": e.date.isoformat(),
            "location": e.location,
            "price": float(e.price),
            "available_tickets": e.available_tickets,
            "total_tickets": e.total_tickets,
        }
        for e in events
    ]


@router.get("/events/{event_id}")
async def get_event(event_id: str, auth_data: dict = Depends(validate_init_data)):
    """Get event details."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        svc = EventService(session)
        event = await svc.get_by_id(uid)

    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")

    return {
        "id": str(event.id),
        "title": event.title,
        "description": event.description,
        "date": event.date.isoformat(),
        "location": event.location,
        "price": float(event.price),
        "available_tickets": event.available_tickets,
        "total_tickets": event.total_tickets,
        "is_active": event.is_active,
    }


@router.post("/events/{event_id}/buy", status_code=status.HTTP_201_CREATED)
async def buy_ticket(event_id: str, auth_data: dict = Depends(validate_init_data)):
    """Purchase a ticket for an event."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    # Get or create user
    user_data = auth_data.get("user", {})
    platform_user_id = str(user_data.get("id", "0"))
    name = user_data.get("first_name", "")

    async with async_session_factory() as session:
        # Get/create user
        user_svc = UserService(session)
        user = await user_svc.get_or_create(
            platform=PlatformType.telegram,
            platform_user_id=platform_user_id,
            name=name,
        )

        # Buy ticket via Mini App flow
        ticket_svc = TicketService(session)
        try:
            result = await ticket_svc.buy_ticket_webapp(user.id, uid)
            await session.commit()
            return result
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# Tickets
# ═══════════════════════════════════════════════════════════════


@router.get("/tickets")
async def list_tickets(auth_data: dict = Depends(validate_init_data)):
    """Get user's tickets."""
    user_data = auth_data.get("user", {})
    platform_user_id = str(user_data.get("id", "0"))

    async with async_session_factory() as session:
        user_svc = UserService(session)
        user = await user_svc.get_or_create(
            platform=PlatformType.telegram,
            platform_user_id=platform_user_id,
            name=user_data.get("first_name", ""),
        )

        ticket_svc = TicketService(session)
        tickets = await ticket_svc.get_user_tickets(user.id)
        await session.commit()

    return tickets


@router.post("/tickets/{ticket_id}/cancel")
async def cancel_ticket(ticket_id: str, auth_data: dict = Depends(validate_init_data)):
    """Cancel a ticket."""
    try:
        tid = UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID билета")

    user_data = auth_data.get("user", {})
    platform_user_id = str(user_data.get("id", "0"))

    async with async_session_factory() as session:
        user_svc = UserService(session)
        user = await user_svc.get_or_create(
            platform=PlatformType.telegram,
            platform_user_id=platform_user_id,
            name=user_data.get("first_name", ""),
        )

        ticket_svc = TicketService(session)
        try:
            ticket = await ticket_svc.cancel_ticket(tid, user.id)
            await session.commit()
            return {
                "ticket_id": str(ticket.id),
                "status": ticket.status.value,
                "event_id": str(ticket.event_id),
            }
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
