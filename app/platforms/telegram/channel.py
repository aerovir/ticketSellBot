"""
ChannelManager — отправка анонсов в Telegram канал.

Бот должен быть добавлен в канал как администратор с правами:
- Отправлять сообщения
- Читать сообщения

Privacy Mode в BotFather должен быть выключен.
"""
import logging
from uuid import UUID

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import async_session_factory
from app.core.models import Event
from app.core.services import EventService

logger = logging.getLogger("ticketbot.telegram.channel")


class ChannelManager:
    """Управляет отправкой анонсов в Telegram канал."""

    def __init__(self, bot: Bot, bot_username: str | None = None):
        self.bot = bot
        self.bot_username = bot_username
        self.channel_id = settings.telegram_channel_id

    @property
    def is_configured(self) -> bool:
        """Проверяет, настроен ли канал для анонсов."""
        return bool(self.channel_id)

    async def post_event_announcement(self, event: Event):
        """Отправляет анонс мероприятия в канал с inline-кнопками."""
        if not self.is_configured:
            logger.info("Канал не настроен, пропускаем анонс")
            return

        date_str = event.date.strftime("%d.%m.%Y %H:%M")
        text = (
            f"🎫 <b>{event.title}</b>\n\n"
            f"{event.description or 'Описание отсутствует'}\n\n"
            f"📅 {date_str}\n"
            f"📍 {event.location or 'Не указано'}\n"
            f"💰 {event.price:.0f}₽\n"
            f"🎟 Билетов: {event.available_tickets}/{event.total_tickets}"
        )

        # Inline-кнопки: покупка в личку + детали
        lines = []
        if self.bot_username:
            buy_url = f"https://t.me/{self.bot_username}?start=buy_{event.id}"
            lines.append(InlineKeyboardButton(
                text="🎟 Купить билет",
                url=buy_url,
            ))
        lines.append(InlineKeyboardButton(
            text="📋 Все мероприятия",
            callback_data=f"ev_page:0",
        ))

        kb = InlineKeyboardMarkup(inline_keyboard=[lines]) if lines else None

        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=kb,
            )
            logger.info("Анонс отправлен в канал %s: %s", self.channel_id, event.title)
        except Exception as e:
            logger.error("Ошибка отправки анонса в канал %s: %s", self.channel_id, e)

    async def post_events_list(self, events: list[Event]):
        """Отправляет список предстоящих мероприятий в канал."""
        if not self.is_configured:
            return

        if not events:
            await self.bot.send_message(
                chat_id=self.channel_id,
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
            chat_id=self.channel_id,
            text="\n".join(lines),
            parse_mode="HTML",
        )
