"""Публикация анонсов мероприятий из web-кабинета в Telegram канал.

Web-контейнер использует тот же TELEGRAM_TOKEN (env_file: .env.telegram),
что и telegram-бот, поэтому может постить анонсы напрямую через ChannelManager.
"""
import logging
from uuid import UUID

from aiogram import Bot
from sqlalchemy import select

from app.config import settings
from app.core.database import async_session_factory
from app.core.models import Channel
from app.core.services import ChannelService, EventService
from app.platforms.telegram.channel import ChannelManager
from app.platforms.telegram.formatting import format_event_text

logger = logging.getLogger("ticketbot.web.announce")

_bot: Bot | None = None


def _get_bot() -> Bot | None:
    """Lazily create a Bot from settings; None if no token configured."""
    global _bot
    if not settings.telegram_token:
        logger.warning("TELEGRAM_TOKEN не настроен — анонсы из web недоступны")
        return None
    if _bot is None:
        _bot = Bot(token=settings.telegram_token)
    return _bot


async def post_event_announcement(event_id: UUID) -> bool:
    """Post an event announcement to its Telegram channel.

    Returns True on success, False on failure (logged, not raised).
    """
    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(event_id)
        if event is None:
            logger.warning("Анонс: мероприятие %s не найдено", event_id)
            return False
        channel_svc = ChannelService(session)
        channel = await channel_svc.get_by_id(event.channel_id)
        if channel is None:
            logger.warning("Анонс: канал мероприятия %s не найден", event_id)
            return False

    bot = _get_bot()
    if bot is None:
        return False

    text = format_event_text(event, mode="full")
    manager = ChannelManager(bot)
    try:
        await manager.post_event_announcement(
            text,
            event.id,
            channel.telegram_channel_id,
            event=event,
        )
        logger.info("Анонс мероприятия %s отправлен в канал %s", event.id, channel.telegram_channel_id)
        return True
    except Exception as e:
        logger.error("Ошибка публикации анонса %s: %s", event_id, e)
        return False


async def send_announcement_dm(event_id: UUID, user_telegram_id: str) -> bool:
    """Отправить анонс мероприятия в личные сообщения пользователю.

    Fallback когда бот не в канале: пользователь всё равно получает анонс.
    """
    async with async_session_factory() as session:
        event_svc = EventService(session)
        event = await event_svc.get_by_id(event_id)
        if event is None:
            return False

    bot = _get_bot()
    if bot is None:
        return False

    text = format_event_text(event, mode="full")
    try:
        await bot.send_message(
            chat_id=int(user_telegram_id),
            text=f"📢 <b>Анонс мероприятия</b>\n\n{text}\n\n"
                 f"<i>Бот не в канале — анонс отправлен вам в личные сообщения.</i>",
            parse_mode="HTML",
        )
        logger.info("Анонс мероприятия %s отправлен в DM пользователю %s", event_id, user_telegram_id)
        return True
    except Exception as e:
        logger.error("Ошибка отправки анонса в DM %s: %s", event_id, e)
        return False


async def send_broadcast(text: str) -> tuple[int, int]:
    """Разослать сообщение во все активные каналы.

    Нефатально по каждому каналу: ошибка одного не прерывает остальные.

    Returns:
        tuple[int, int]: (sent, total)
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Channel).where(Channel.is_subscription_active == True)
        )
        channels = list(result.scalars().all())

    if not channels:
        return 0, 0

    bot = _get_bot()
    if bot is None:
        return 0, len(channels)

    sent = 0
    body = f"📢 <b>Сообщение администрации</b>\n\n{text}"
    for ch in channels:
        try:
            await bot.send_message(
                chat_id=ch.telegram_channel_id,
                text=body,
                parse_mode="HTML",
            )
            sent += 1
        except Exception as e:
            logger.error("Ошибка рассылки в %s: %s", ch.telegram_channel_id, e)

    return sent, len(channels)
