"""
REST API endpoints for Telegram Mini App.

All endpoints (except health) require initData validation.
"""

import csv
import io
import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.database import async_session_factory
from app.core.models import PlatformType, Event
from app.core.qr import generate_qr_png
from app.core.schemas import (
    BroadcastIn,
    ChangeAdminIn,
    ChangeTierIn,
    ChannelRegisterIn,
    ChannelSubscribeIn,
    CheckInIn,
    EventCreate,
    EventUpdateIn,
    InviteIssueIn,
    MeUpdateIn,
    SubscribeIn,
    SubscribeMeIn,
    UpdateSubscriptionIn,
)
from app.core.services import (
    ChannelAdminService,
    ChannelService,
    EventService,
    StatsService,
    TicketService,
    UserService,
)
from app.web.dependencies import (
    CurrentUser,
    get_current_user,
    require_admin,
    require_super_admin,
    validate_init_data,
)
from app.web.announce import _get_bot, post_event_announcement, send_announcement_dm, send_broadcast

logger = logging.getLogger("ticketbot.web.routes")
router = APIRouter()


async def _send_ticket_dm(telegram_user_id: str, text: str) -> bool:
    """Отправить сообщение о билете в личные сообщения пользователю."""
    bot = _get_bot()
    if bot is None:
        return False
    try:
        await bot.send_message(
            chat_id=int(telegram_user_id),
            text=text,
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        logger.warning("Не удалось отправить DM пользователю %s: %s", telegram_user_id, e)
        return False


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

            # Отправить билет в личные сообщения Telegram
            code_text = f"\n🔑 Код: <code>{result['validation_code']}</code>" if result.get("validation_code") else ""
            await _send_ticket_dm(
                platform_user_id,
                f"✅ Билет куплен!\n"
                f"🎫 {result['event_title']}\n"
                f"📅 {result['event_date']}{code_text}",
            )

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

            # Отправить уведомление о возврате в личные сообщения
            try:
                event = await session.get(Event, ticket.event_id)
                event_title = event.title if event else "—"
            except Exception:
                event_title = "—"
            await _send_ticket_dm(
                platform_user_id,
                f"↩️ <b>Билет возвращён</b>\n"
                f"🎫 {event_title}\n"
                f"🔑 Код: <code>{ticket.validation_code or '—'}</code>",
            )

            return {
                "ticket_id": str(ticket.id),
                "status": ticket.status.value,
                "event_id": str(ticket.event_id),
            }
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# VK Mini App
# ═══════════════════════════════════════════════════════════════


@router.get("/vk/me")
async def vk_me(user_id: str, user_name: str = ""):
    """VK Mini App: приветствие пользователя и регистрация в БД.

    Вызывается из VK Mini App после инициализации VK Bridge.
    """
    async with async_session_factory() as session:
        user_svc = UserService(session)
        user = await user_svc.get_or_create(
            platform=PlatformType.vk,
            platform_user_id=user_id,
            name=user_name or None,
        )
        await session.commit()

        return {
            "user_id": user_id,
            "name": user_name or "Гость",
            "greeting": f"Привет, {user_name or 'Гость'}!",
            "platform": "vk",
            "registered": user is not None,
        }


# ═══════════════════════════════════════════════════════════════
# Личный кабинет
# ═══════════════════════════════════════════════════════════════


@router.get("/me")
async def get_me(current: CurrentUser = Depends(get_current_user)):
    """Профиль текущего пользователя: роль + каналы, где он админ."""
    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        channels = await channel_svc.get_channels_by_admin(current.telegram_user_id)
        # Подписка пользователя (организатор без канала)
        user_svc = UserService(session)
        user = await user_svc.get_by_platform_user_id(PlatformType.telegram, current.telegram_user_id)

    return {
        "id": str(current.user_id),
        "telegram_user_id": current.telegram_user_id,
        "name": current.name,
        "role": current.role,
        "is_super_admin": current.is_super_admin,
        "subscription_tier": user.subscription_tier.value if user else None,
        "is_subscription_active": user.is_subscription_active if user else False,
        "subscription_until": user.subscription_until.isoformat() if user and user.subscription_until else None,
        "channels": [
            {
                "id": str(ch.id),
                "telegram_channel_id": ch.telegram_channel_id,
                "title": ch.title,
                "is_subscription_active": ch.is_subscription_active,
                "subscription_tier": ch.subscription_tier.value,
                "subscription_until": ch.subscription_until.isoformat() if ch.subscription_until else None,
            }
            for ch in channels
        ],
    }


@router.patch("/me")
async def update_me(
    body: MeUpdateIn,
    current: CurrentUser = Depends(get_current_user),
):
    """Обновить имя пользователя в профиле."""
    async with async_session_factory() as session:
        user_svc = UserService(session)
        user = await user_svc.update_name(current.user_id, body.name)
        await session.commit()
    return {"id": str(current.user_id), "name": user.name if user else None}


@router.post("/me/subscription")
async def subscribe_me(
    body: SubscribeMeIn,
    current: CurrentUser = Depends(get_current_user),
):
    """Покупка/активация подписки пользователя (факт покупки = активация функций).

    MVP: активация подписки без реальной оплаты. Выбор tier (basic/pro).
    """
    async with async_session_factory() as session:
        user_svc = UserService(session)
        user = await user_svc.activate_subscription(
            current.user_id, days=30, tier=body.tier,
        )
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
        await session.commit()

    return {
        "subscription_tier": user.subscription_tier.value,
        "subscription_until": user.subscription_until.isoformat() if user.subscription_until else None,
    }


# ─── Мои каналы (самообслуживание) ────────────────────────────


def _channel_dict(ch) -> dict:
    """Сериализация канала для /api/me/channels."""
    return {
        "id": str(ch.id),
        "telegram_channel_id": ch.telegram_channel_id,
        "title": ch.title,
    }


@router.get("/me/channels")
async def list_my_channels(current: CurrentUser = Depends(get_current_user)):
    """Список каналов текущего пользователя (где он админ)."""
    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        channels = await channel_svc.get_channels_by_admin(current.telegram_user_id)

    return [_channel_dict(ch) for ch in channels]


@router.post("/me/channels")
async def register_my_channel(
    body: ChannelRegisterIn,
    current: CurrentUser = Depends(get_current_user),
):
    """Добавить Telegram-канал в свой кабинет.

    Канал создаётся без подписки (inactive). Когда бот будет добавлен в канал,
    my_chat_member обновит telegram_channel_id и синхронизирует админов.

    Returns 201 если канал создан, 200 если уже был привязан.
    """
    from fastapi.responses import JSONResponse

    telegram_channel_id = body.telegram_channel_id.strip()
    if not telegram_channel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Укажите @username или ID канала",
        )

    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        admin_svc = ChannelAdminService(session)

        channel = await channel_svc.get_by_telegram_id(telegram_channel_id)

        if channel is None:
            # Новый канал: создать и привязать пользователя как админа
            channel = await channel_svc.create(
                telegram_channel_id=telegram_channel_id,
                admin_telegram_user_id=current.telegram_user_id,
                title=body.title or f"Канал {telegram_channel_id}",
            )
            await admin_svc.sync_admins(channel.id, [current.telegram_user_id])
            await session.commit()
            logger.info("", extra={
                "event_type": "channel.self_registered",
                "channel_id": str(channel.id),
                "telegram_channel_id": telegram_channel_id,
                "user_id": current.telegram_user_id,
            })
            return JSONResponse(
                content=_channel_dict(channel),
                status_code=status.HTTP_201_CREATED,
            )

        # Канал уже существует — проверить что пользователь админ
        is_admin = await admin_svc.user_is_admin(channel.id, current.telegram_user_id)
        if is_admin:
            # Идемпотентно: канал уже привязан
            return _channel_dict(channel)

        # Защита от захвата: канал принадлежит другому пользователю
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Канал уже зарегистрирован. Добавьте бота в канал — он привяжет вас автоматически.",
        )


# ═══════════════════════════════════════════════════════════════
# Админ: мероприятия
# ═══════════════════════════════════════════════════════════════


@router.get("/admin/events")
async def admin_list_events(current: CurrentUser = Depends(get_current_user)):
    """Список мероприятий доступных текущему пользователю.

    Суперадмин видит всё. Организатор — свои каналы + owner-мероприятия.
    Обычный пользователь — свои owner-мероприятия (открытое создание).
    """
    async with async_session_factory() as session:
        event_svc = EventService(session)
        channel_svc = ChannelService(session)
        if current.is_super_admin:
            events = await event_svc.list_all()
        elif current.is_admin:
            events = []
            # мероприятия по каналам организатора
            for cid in current.managed_channel_ids:
                events.extend(await event_svc.list_all(channel_id=cid))
            # мероприятия организатора без канала (по owner)
            events.extend(await event_svc.list_all(owner_user_id=current.user_id))
        else:
            # Обычный пользователь: только свои owner-мероприятия
            events = await event_svc.list_all(owner_user_id=current.user_id)

        # Карта каналов для названий (owner-события без канала — пропускаем None)
        channel_ids = {e.channel_id for e in events if e.channel_id is not None}
        channels = {}
        for cid in channel_ids:
            ch = await channel_svc.get_by_id(cid)
            if ch:
                channels[cid] = ch

    return [
        {
            "id": str(e.id),
            "channel_id": str(e.channel_id) if e.channel_id else None,
            "channel_title": channels.get(e.channel_id).title if e.channel_id and e.channel_id in channels else None,
            "owner_user_id": str(e.owner_user_id) if e.owner_user_id else None,
            "title": e.title,
            "date": e.date.isoformat(),
            "location": e.location,
            "price": float(e.price),
            "total_tickets": e.total_tickets,
            "available_tickets": e.available_tickets,
            "is_active": e.is_active,
            "is_published": e.is_published,
            "is_free": e.is_free,
        }
        for e in events
    ]


@router.post("/admin/events", status_code=status.HTTP_201_CREATED)
async def admin_create_event(
    body: EventCreate,
    current: CurrentUser = Depends(get_current_user),
):
    """Создать мероприятие (черновик).

    Мероприятие принадлежит каналу (если указан) ИЛИ организатору-пользователю
    (owner_user_id = текущий организатор). Проверка доступа.
    """
    # Канальный путь: организатор должен управлять каналом
    if body.channel_id is not None and not current.can_manage(body.channel_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет доступа к этому каналу",
        )
    # Путь организатора без канала: owner_user_id должен быть текущим пользователем
    if body.channel_id is None:
        if body.owner_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Укажите канал или владельца мероприятия",
            )
        if not current.is_super_admin and body.owner_user_id != current.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Вы не можете создавать мероприятия от имени другого пользователя",
            )

    async with async_session_factory() as session:
        event_svc = EventService(session)
        try:
            event = await event_svc.create(
                title=body.title,
                description=body.description,
                date=body.date,
                location=body.location,
                price=body.price,
                total_tickets=body.total_tickets,
                channel_id=body.channel_id,
                invites_quota=body.invites_quota,
                owner_user_id=body.owner_user_id,
            )
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {"id": str(event.id), "is_published": event.is_published}


@router.get("/admin/events/{event_id}")
async def admin_get_event(
    event_id: str,
    current: CurrentUser = Depends(get_current_user),
):
    """Детали мероприятия (админ)."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        # Доступ: организатор-владелец ИЛИ супер-админ ИЛИ управляет каналом
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        channel_svc = ChannelService(session)
        channel = await channel_svc.get_by_id(event.channel_id) if event.channel_id else None

    return {
        "id": str(event.id),
        "channel_id": str(event.channel_id) if event.channel_id else None,
        "owner_user_id": str(event.owner_user_id) if event.owner_user_id else None,
        "channel_title": channel.title if channel else None,
        "title": event.title,
        "description": event.description,
        "date": event.date.isoformat(),
        "location": event.location,
        "price": float(event.price),
        "total_tickets": event.total_tickets,
        "available_tickets": event.available_tickets,
        "is_active": event.is_active,
        "is_published": event.is_published,
        "is_free": event.is_free,
    }


@router.patch("/admin/events/{event_id}")
async def admin_update_event(
    event_id: str,
    body: EventUpdateIn,
    current: CurrentUser = Depends(get_current_user),
):
    """Частичное обновление мероприятия."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    data = body.model_dump(exclude_unset=True)

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        if not data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет полей для обновления")
        try:
            event = await event_svc.update(uid, **data)
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {"id": str(uid), "updated": True}


@router.post("/admin/events/{event_id}/toggle")
async def admin_toggle_event(
    event_id: str,
    current: CurrentUser = Depends(get_current_user),
):
    """Включить/отключить мероприятие."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        event = await event_svc.set_active(uid, not event.is_active)
        await session.commit()

    return {"id": str(uid), "is_active": event.is_active}


@router.post("/admin/events/{event_id}/delete")
async def admin_delete_event(
    event_id: str,
    current: CurrentUser = Depends(get_current_user),
):
    """Мягко удалить мероприятие."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        await event_svc.soft_delete(uid)
        await session.commit()

    return {"id": str(uid), "deleted": True}


@router.post("/admin/events/{event_id}/publish")
async def admin_publish_event(
    event_id: str,
    current: CurrentUser = Depends(get_current_user),
    channel_id: str | None = Body(None, embed=True),
):
    """Опубликовать мероприятие + отправить анонс в выбранный канал.

    Если channel_id передан — мероприятие привязывается к этому каналу
    и анонс отправляется туда. Если не передан — используется текущий канал
    мероприятия. Ошибка анонса не откатывает флаг публикации.

    Публикацию можно делать многократно (разные каналы, репосты).
    """
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    target_channel_id: UUID | None = None
    if channel_id:
        try:
            target_channel_id = UUID(channel_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID канала")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        channel_svc = ChannelService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")

        # Если указан канал — проверить доступ и привязать мероприятие
        if target_channel_id:
            if not current.can_manage(target_channel_id) and not current.is_super_admin:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа к этому каналу")
            # Привязать мероприятие к выбранному каналу
            await event_svc.update(uid, channel_id=target_channel_id, is_published=True)
        else:
            await event_svc.update(uid, is_published=True)
        await session.commit()

    announced = await post_event_announcement(uid)
    dm_sent = False
    if not announced:
        dm_sent = await send_announcement_dm(uid, current.telegram_user_id)
    return {
        "id": str(uid),
        "is_published": True,
        "announced": announced,
        "dm_sent": dm_sent,
    }


@router.post("/admin/events/{event_id}/repost")
async def admin_repost_event(
    event_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """Переотправить анонс в канал."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")

    announced = await post_event_announcement(uid)
    return {"id": str(uid), "announced": announced}


@router.get("/admin/events/{event_id}/stats")
async def admin_event_stats(
    event_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """Статистика продаж мероприятия (всем админам, без тарифного гейта)."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        stats = await event_svc.get_event_stats(uid)

    return {"event_id": str(uid), **stats}


@router.get("/admin/events/{event_id}/tickets")
async def admin_event_tickets(
    event_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """Список билетов на мероприятие (админ)."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        ticket_svc = TicketService(session)
        tickets = await ticket_svc.get_event_tickets(uid)

    return {"event_id": str(uid), "tickets": tickets}


@router.get("/admin/events/{event_id}/tickets.csv")
async def admin_event_tickets_csv(
    event_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """Экспорт билетов на мероприятие в CSV."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        ticket_svc = TicketService(session)
        tickets = await ticket_svc.export_event_tickets(uid)

    if not tickets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет билетов для экспорта")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(tickets[0].keys()))
    writer.writeheader()
    writer.writerows(tickets)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="event-{uid}-tickets.csv"'},
    )


# ═══════════════════════════════════════════════════════════════
# Админ: билеты и вход
# ═══════════════════════════════════════════════════════════════


@router.get("/admin/tickets/validate")
async def admin_validate_ticket(
    code: str,
    current: CurrentUser = Depends(require_admin),
):
    """Проверить билет по коду (без отметки входа)."""
    async with async_session_factory() as session:
        ticket_svc = TicketService(session)
        result = await ticket_svc.validate_ticket(code.strip().upper())
    return result


@router.post("/admin/tickets/checkin")
async def admin_checkin_ticket(
    body: CheckInIn,
    current: CurrentUser = Depends(require_admin),
):
    """Отметить вход по коду билета."""
    code = body.code.strip().upper()
    # Нормализация: AB3XK7M9 (8 символов без дефиса) → AB3X-K7M9
    if len(code) == 8 and "-" not in code:
        code = f"{code[:4]}-{code[4:]}"

    async with async_session_factory() as session:
        ticket_svc = TicketService(session)
        try:
            ticket = await ticket_svc.check_in_by_code(code, current.telegram_user_id)
            # Проверка доступа: организатор должен управлять мероприятием билета
            event_svc = EventService(session)
            event = await event_svc.get_by_id(ticket.event_id)
            if event is not None and not _can_manage_event(current, event):
                await session.rollback()
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа к этому билету")
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {
        "ok": True,
        "ticket_id": str(ticket.id),
        "status": ticket.status.value,
        "event_id": str(ticket.event_id),
        "checked_in_at": ticket.checked_in_at.isoformat() if ticket.checked_in_at else None,
    }


@router.post("/admin/tickets/{ticket_id}/cancel")
async def admin_cancel_ticket(
    ticket_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """Отменить билет (админ). Канальный доступ по мероприятию билета."""
    try:
        tid = UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID билета")

    async with async_session_factory() as session:
        ticket_svc = TicketService(session)
        pair = await ticket_svc.get_ticket_event(tid)
        if pair is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Билет не найден")
        ticket, event = pair
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")
        try:
            ticket = await ticket_svc.admin_cancel_ticket(tid)
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {"ticket_id": str(tid), "status": ticket.status.value}


# ═══════════════════════════════════════════════════════════════
# Админ: каналы и подписки (super-admin)
# ═══════════════════════════════════════════════════════════════


@router.get("/admin/channels")
async def admin_list_channels(current: CurrentUser = Depends(require_super_admin)):
    """Список всех каналов со статусом подписки и админами."""
    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        admin_svc = ChannelAdminService(session)
        channels = await channel_svc.list_all()
        admins_by_channel = {
            str(ch.id): await admin_svc.get_admin_ids(ch.id)
            for ch in channels
        }

    return [
        {
            "id": str(ch.id),
            "telegram_channel_id": ch.telegram_channel_id,
            "title": ch.title,
            "is_subscription_active": ch.is_subscription_active,
            "subscription_tier": ch.subscription_tier.value,
            "subscription_until": ch.subscription_until.isoformat() if ch.subscription_until else None,
            "admins": admins_by_channel.get(str(ch.id), []),
        }
        for ch in channels
    ]


@router.get("/admin/channels/{channel_id}")
async def admin_channel_info(
    channel_id: str,
    current: CurrentUser = Depends(require_super_admin),
):
    """Детальная информация о канале."""
    try:
        cid = UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID канала")

    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        summary = await channel_svc.get_channel_summary(cid)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Канал не найден")
    return summary


@router.post("/admin/channels/{channel_id}/subscribe")
async def admin_subscribe(
    channel_id: str,
    body: SubscribeIn,
    current: CurrentUser = Depends(require_super_admin),
):
    """Активировать подписку каналу."""
    try:
        cid = UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID канала")

    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        channel = await channel_svc.activate_subscription(
            cid,
            duration_days=body.duration_days,
            tier=body.tier,
        )
        if channel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Канал не найден")
        await session.commit()

    return {
        "channel_id": str(cid),
        "is_subscription_active": channel.is_subscription_active,
        "subscription_tier": channel.subscription_tier.value,
        "subscription_until": channel.subscription_until.isoformat() if channel.subscription_until else None,
    }


@router.post("/admin/channels/{channel_id}/unsubscribe")
async def admin_unsubscribe(
    channel_id: str,
    current: CurrentUser = Depends(require_super_admin),
):
    """Отключить подписку канала."""
    try:
        cid = UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID канала")

    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        channel = await channel_svc.deactivate_subscription(cid)
        if channel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Канал не найден")
        await session.commit()

    return {"channel_id": str(cid), "is_subscription_active": False}


@router.post("/admin/channels/{channel_id}/change_admin")
async def admin_change_admin(
    channel_id: str,
    body: ChangeAdminIn,
    current: CurrentUser = Depends(require_super_admin),
):
    """Сменить администратора канала."""
    try:
        cid = UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID канала")

    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        channel = await channel_svc.get_by_id(cid)
        if channel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Канал не найден")
        try:
            _, old_admins = await channel_svc.change_admin(
                channel.telegram_channel_id,
                body.new_admin_id,
            )
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {"channel_id": str(cid), "new_admin_id": body.new_admin_id, "old_admins": old_admins}


@router.post("/admin/channels/check_expired")
async def admin_check_expired(current: CurrentUser = Depends(require_super_admin)):
    """Проверить и деактивировать просроченные подписки."""
    async with async_session_factory() as session:
        from sqlalchemy import select as _select
        from app.core.models import Channel as _Channel

        result = await session.execute(_select(_Channel).where(_Channel.is_subscription_active == True))
        channels = list(result.scalars().all())
        channel_svc = ChannelService(session)
        deactivated = 0
        for ch in channels:
            if not await channel_svc.is_subscription_valid(ch.id):
                deactivated += 1
        await session.commit()

    return {"checked": len(channels), "deactivated": deactivated}


@router.post("/admin/channels/{channel_id}/subscription")
async def admin_update_subscription(
    channel_id: str,
    body: UpdateSubscriptionIn,
    current: CurrentUser = Depends(require_super_admin),
):
    """Сменить подписку канала: тип + срок (дни/месяцы/годы)."""
    try:
        cid = UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID канала")

    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        channel = await channel_svc.change_subscription(
            cid,
            tier=body.tier,
            period=body.period,
            period_unit=body.period_unit,
        )
        if channel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Канал не найден")
        await session.commit()

    return {
        "channel_id": str(cid),
        "subscription_tier": channel.subscription_tier.value,
        "subscription_until": channel.subscription_until.isoformat() if channel.subscription_until else None,
    }


@router.post("/admin/channels/{channel_id}/tier")
async def admin_change_tier(
    channel_id: str,
    body: ChangeTierIn,
    current: CurrentUser = Depends(require_super_admin),
):
    """Сменить только тип подписки канала (срок не меняется)."""
    try:
        cid = UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID канала")

    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        channel = await channel_svc.change_tier(cid, tier=body.tier)
        if channel is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Канал не найден")
        await session.commit()

    return {
        "channel_id": str(cid),
        "subscription_tier": channel.subscription_tier.value,
    }


# ═══════════════════════════════════════════════════════════════
# Админ: общая статистика (super-admin)
# ═══════════════════════════════════════════════════════════════


@router.get("/admin/stats")
async def admin_global_stats(current: CurrentUser = Depends(require_super_admin)):
    """Общая статистика по всем каналам/мероприятиям/билетам."""
    async with async_session_factory() as session:
        stats_svc = StatsService(session)
        stats = await stats_svc.get_global_stats()
    return stats


# ═══════════════════════════════════════════════════════════════
# Админ: создать канал + подписка, инфо о пользователе,
#        рассылка, здоровье (super-admin)
# ═══════════════════════════════════════════════════════════════


@router.post("/admin/channels", status_code=status.HTTP_201_CREATED)
async def admin_create_channel(
    body: ChannelSubscribeIn,
    current: CurrentUser = Depends(require_super_admin),
):
    """Создать канал (если нет в БД) и активировать подписку.

    Зеркалит бота admin_subscribe: по @username/ID создаёт канал,
    если он ещё не зарегистрирован, затем активирует подписку.
    """
    async with async_session_factory() as session:
        channel_svc = ChannelService(session)
        try:
            channel = await channel_svc.get_by_telegram_id(body.telegram_channel_id)
            if channel is None:
                channel = await channel_svc.create(
                    telegram_channel_id=body.telegram_channel_id,
                    admin_telegram_user_id="",
                    title=body.title or f"Канал {body.telegram_channel_id}",
                )
            channel = await channel_svc.activate_subscription(
                channel.id,
                duration_days=body.duration_days,
                tier=body.tier,
            )
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {
        "channel_id": str(channel.id),
        "telegram_channel_id": channel.telegram_channel_id,
        "is_subscription_active": channel.is_subscription_active,
        "subscription_tier": channel.subscription_tier.value,
        "subscription_until": channel.subscription_until.isoformat() if channel.subscription_until else None,
    }


@router.get("/admin/users/{telegram_user_id}")
async def admin_user_info(
    telegram_user_id: str,
    current: CurrentUser = Depends(require_super_admin),
):
    """Информация о пользователе по Telegram ID (без создания).

    Зеркалит бота sa_user_info, но без side-effect get_or_create.
    """
    async with async_session_factory() as session:
        user_svc = UserService(session)
        user = await user_svc.get_by_platform_user_id(PlatformType.telegram, telegram_user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
        channel_svc = ChannelService(session)
        channels = await channel_svc.get_channels_by_admin(telegram_user_id)

    return {
        "id": str(user.id),
        "telegram_user_id": telegram_user_id,
        "name": user.name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "channels": [
            {
                "id": str(ch.id),
                "telegram_channel_id": ch.telegram_channel_id,
                "title": ch.title,
                "is_subscription_active": ch.is_subscription_active,
                "subscription_tier": ch.subscription_tier.value,
            }
            for ch in channels
        ],
    }


@router.get("/admin/users")
async def admin_list_users(current: CurrentUser = Depends(require_super_admin)):
    """Список всех пользователей (не удалённых)."""
    async with async_session_factory() as session:
        user_svc = UserService(session)
        users = await user_svc.list_all()

    return [
        {
            "id": str(u.id),
            "telegram_user_id": u.platform_user_id,
            "name": u.name,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "is_subscription_active": u.is_subscription_active,
            "subscription_tier": u.subscription_tier.value,
        }
        for u in users
    ]


@router.delete("/admin/users/{telegram_user_id}")
async def admin_delete_user(
    telegram_user_id: str,
    current: CurrentUser = Depends(require_super_admin),
):
    """Мягкое удаление пользователя (super-admin only)."""
    async with async_session_factory() as session:
        user_svc = UserService(session)
        user = await user_svc.get_by_platform_user_id(PlatformType.telegram, telegram_user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
        if user.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь уже удалён")
        await user_svc.soft_delete(user.id)
        await session.commit()

    return {"id": str(user.id), "deleted": True}


@router.post("/admin/broadcast")
async def admin_broadcast(
    body: BroadcastIn,
    current: CurrentUser = Depends(require_super_admin),
):
    """Разослать сообщение во все активные каналы."""
    if not body.text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сообщение не может быть пустым")
    sent, total = await send_broadcast(body.text.strip())
    return {"sent": sent, "total": total}


@router.get("/admin/health")
async def admin_health(current: CurrentUser = Depends(require_super_admin)):
    """Здоровье бота: статус, username, БД."""
    from sqlalchemy import text as sqltext

    db_ok = False
    async with async_session_factory() as session:
        try:
            await session.execute(sqltext("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False

    bot_username = None
    bot = _get_bot()
    if bot is not None:
        try:
            me = await bot.get_me()
            bot_username = me.username
        except Exception:
            bot_username = None

    return {
        "status": "ok" if db_ok else "degraded",
        "bot_username": bot_username,
        "db_ok": db_ok,
    }


# ═══════════════════════════════════════════════════════════════
# Админ: пригласительные (pro, только админ канала)
# ═══════════════════════════════════════════════════════════════


def _can_manage_event(current: CurrentUser, event) -> bool:
    """Доступ к мероприятию: супер-админ, организатор-владелец (без канала)
    или организатор канала."""
    if current.is_super_admin:
        return True
    # Сначала владелец (owner-событие) — даже если event привязан к каналу
    if event.owner_user_id == current.user_id:
        return True
    # Затем канал — организатор управляет мероприятиями своего канала
    if event.channel_id is not None:
        return current.can_manage(event.channel_id)
    return False


def _can_issue_invites(current: CurrentUser, event) -> bool:
    """Правило: пригласительные выдаёт организатор (не суперадмин).

    Канальный организатор — управляет каналом; организатор без канала —
    владелец (owner) мероприятия. Pro-подписка проверяется в эндпоинте.
    """
    if current.is_super_admin:
        return False
    if event.channel_id is not None:
        return event.channel_id in current.managed_channel_ids
    return event.owner_user_id == current.user_id


@router.post("/admin/events/{event_id}/invites", status_code=status.HTTP_201_CREATED)
async def admin_issue_invite(
    event_id: str,
    body: InviteIssueIn,
    current: CurrentUser = Depends(require_admin),
):
    """Выдать пригласительное (только админ канала, pro-подписка)."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_issue_invites(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Пригласительные выдаёт только админ канала")

        # Pro-гейт: канальный организатор — подписка канала; организатор без канала — подписка пользователя
        if event.channel_id is not None:
            channel_svc = ChannelService(session)
            has_feature = await channel_svc.require_feature(event.channel_id, "invite_tickets")
        else:
            user_svc = UserService(session)
            has_feature = await user_svc.require_feature(event.owner_user_id, "invite_tickets")
        if not has_feature:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Для пригласительных нужна подписка Pro")

        ticket_svc = TicketService(session)
        try:
            invite = await ticket_svc.issue_invite(uid, seats=body.seats, issued_by=current.telegram_user_id)
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {
        "ticket_id": str(invite.id),
        "validation_code": invite.validation_code,
        "seats": invite.seats,
        "status": invite.status.value,
    }


@router.post("/admin/events/{event_id}/invites/{ticket_id}/cancel")
async def admin_cancel_invite(
    event_id: str,
    ticket_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """Отменить пригласительное (вернуть места)."""
    try:
        uid = UUID(event_id)
        tid = UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_issue_invites(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Пригласительные управляет админ канала")

        ticket_svc = TicketService(session)
        try:
            invite = await ticket_svc.cancel_invite(tid)
            await session.commit()
        except ValueError as e:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {"ticket_id": str(tid), "status": invite.status.value}


@router.get("/admin/events/{event_id}/invites")
async def admin_list_invites(
    event_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """Список пригласительных по мероприятию."""
    try:
        uid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID мероприятия")

    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(uid)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мероприятие не найдено")
        if not _can_issue_invites(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Пригласительные управляет админ канала")
        ticket_svc = TicketService(session)
        invites = await ticket_svc.get_event_invites(uid)

    return {"event_id": str(uid), "invites": invites}


@router.get("/admin/tickets/{ticket_id}/qr")
async def admin_ticket_qr(
    ticket_id: str,
    current: CurrentUser = Depends(require_admin),
):
    """PNG-картинка QR-кода билета/пригласительного."""
    try:
        tid = UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный ID билета")

    async with async_session_factory() as session:
        ticket_svc = TicketService(session)
        pair = await ticket_svc.get_ticket_event(tid)
        if pair is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Билет не найден")
        ticket, event = pair
        if not _can_manage_event(current, event):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа")

        # QR-коды — фича pro (матрица qr_codes)
        if event.channel_id is not None:
            channel_svc = ChannelService(session)
            has_qr = await channel_svc.require_feature(event.channel_id, "qr_codes")
        else:
            user_svc = UserService(session)
            has_qr = await user_svc.require_feature(event.owner_user_id, "qr_codes")
        if not has_qr:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="QR-коды доступны на подписке Pro")

    code = ticket.validation_code or str(ticket.id)
    png = generate_qr_png(code)
    return StreamingResponse(
        iter([png]),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="ticket-{ticket.id}-qr.png"'},
    )
