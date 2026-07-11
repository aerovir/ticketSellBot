"""
ChannelManager — отправка анонсов в Telegram каналы.

Бот должен быть добавлен в канал как администратор с правами:
- Отправлять сообщения
- Читать сообщения

Поддерживает работу с несколькими каналами (multi-tenant).
Канал указывается динамически, не из конфига.
"""
import logging
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.core.database import async_session_factory
from app.core.models import Event, Channel
from app.core.services import EventService

logger = logging.getLogger("ticketbot.telegram.channel")


class ChannelManager:
    """Управляет отправкой анонсов в Telegram каналы.

    В отличие от предыдущей версии, не привязан к одному каналу из конфига.
    Все методы принимают telegram_channel_id — куда постить.
    """

    def __init__(self, bot: Bot, bot_username: str | None = None):
        self.bot = bot
        self.bot_username = bot_username

    async def post_event_announcement(self, event: Event, channel_telegram_id: str):
        """Отправляет анонс мероприятия в указанный канал с inline-кнопками."""
        date_str = event.date.strftime("%d.%m.%Y %H:%M")
        text = (
            f"🎫 <b>{event.title}</b>\n\n"
            f"{event.description or 'Описание отсутствует'}\n\n"
            f"📅 {date_str}\n"
            f"📍 {event.location or 'Не указано'}\n"
            f"💰 {event.price:.0f}₽\n"
            f"🎟 Билетов: {event.available_tickets}/{event.total_tickets}"
        )

        # Inline-кнопки: всё в канале через callback_data
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎟 Купить", callback_data=f"channel_buy:{event.id}"),
                InlineKeyboardButton(text="🎫 Мои билеты", callback_data="channel_my_tickets"),
            ],
            [
                InlineKeyboardButton(text="📋 Все мероприятия", callback_data="channel_events"),
            ],
        ])

        try:
            await self.bot.send_message(
                chat_id=channel_telegram_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=kb,
            )
            logger.info("Анонс отправлен в канал %s: %s", channel_telegram_id, event.title)
        except Exception as e:
            logger.error("Ошибка отправки анонса в канал %s: %s", channel_telegram_id, e)

    async def post_event_announcement_for_channel(self, event: Event, channel: Channel):
        """Удобная обёртка: постит анонс в telegram_channel_id канала."""
        await self.post_event_announcement(event, channel.telegram_channel_id)

    async def post_events_list(self, events: list[Event], channel_telegram_id: str):
        """Отправляет список предстоящих мероприятий в указанный канал."""
        if not events:
            await self.bot.send_message(
                chat_id=channel_telegram_id,
                text="😔 Нет предстоящих мероприятий.",
            )
            return

        lines = ["🎫 <b>Предстоящие мероприятия:</b>\n"]
        for e in events:
            date_str = e.date.strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"📌 <b>{e.title}</b>\n"
                f"📅 {date_str}\n"
                f"📍 {e.location or 'Не указано'}\n"
                f"💰 {e.price:.0f}₽ | Осталось: {e.available_tickets}/{e.total_tickets}\n"
            )

        await self.bot.send_message(
            chat_id=channel_telegram_id,
            text="\n".join(lines),
            parse_mode="HTML",
        )
