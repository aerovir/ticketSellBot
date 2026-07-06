"""
MAX Platform Bot Adapter.

MAX (max.ru) — российский мессенджер от VK Group.
Документация API: https://dev.max.ru/docs-api
Официальный Python SDK: max-bot-api-client-py

Примечание: на момент разработки создание ботов на MAX может быть
временно недоступно. Этот адаптер реализован по официальной документации
и будет работать после получения токена от @MasterBot.
"""

from uuid import UUID
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from core.database import async_session_factory
from core.models import PlatformType
from core.services import UserService, EventService, TicketService
from platforms.base import PlatformBot

# MAX Bot API Python SDK (official)
# https://pypi.org/project/max-bot-api-client-py/
try:
    from max_bot_api import MaxBot, Message
    from max_bot_api.types import Keyboard, KeyboardButton
    MAX_AVAILABLE = True
except ImportError:
    MAX_AVAILABLE = False


class MaxPlatformBot(PlatformBot):
    def __init__(self):
        if not settings.max_token:
            raise ValueError("MAX_TOKEN is not set")
        if not MAX_AVAILABLE:
            raise ImportError(
                "max-bot-api-client-py is not installed. "
                "Install it via: pip install max-bot-api-client-py"
            )

        self.bot = MaxBot(token=settings.max_token)
        self._register_handlers()

    def _register_handlers(self):
        self.bot.on.command("start")(self.cmd_start)
        self.bot.on.command("events")(self.cmd_events)
        self.bot.on.command("event")(self.cmd_event)
        self.bot.on.command("buy")(self.cmd_buy)
        self.bot.on.command("my_tickets")(self.cmd_my_tickets)
        self.bot.on.command("cancel")(self.cmd_cancel)

    async def _get_user_id(self, message: Message) -> UUID:
        async with async_session_factory() as session:
            user_svc = UserService(session)
            user = await user_svc.get_or_create(
                platform=PlatformType.max,
                platform_user_id=str(message.from_user.id),
                name=message.from_user.name,
            )
            return user.id

    async def cmd_start(self, message: Message):
        await self._get_user_id(message)
        text = (
            "🎫 TicketBot\n\n"
            "Доступные команды:\n"
            "/events — список мероприятий\n"
            "/event <id> — детали мероприятия\n"
            "/buy <id> — купить билет\n"
            "/my_tickets — мои билеты\n"
            "/cancel <id> — отменить билет"
        )
        await self.bot.send_message(chat_id=message.chat.id, text=text)

    async def cmd_events(self, message: Message):
        async with async_session_factory() as session:
            event_svc = EventService(session)
            events = await event_svc.list_upcoming()

        if not events:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="😔 Нет предстоящих мероприятий.",
            )
            return

        lines = []
        for e in events:
            date_str = e.date.strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"📌 {e.title}\n"
                f"📅 {date_str}\n"
                f"📍 {e.location or 'Не указано'}\n"
                f"💰 {e.price:.0f}₽ | Осталось: {e.available_tickets}/{e.total_tickets}\n"
                f"🎫 /event {e.id}"
            )

        await self.bot.send_message(
            chat_id=message.chat.id,
            text="\n\n".join(lines),
        )

    async def cmd_event(self, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="Укажите ID мероприятия: /event <id>",
            )
            return

        try:
            event_id = UUID(args[1])
        except ValueError:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="Неверный ID мероприятия.",
            )
            return

        async with async_session_factory() as session:
            event_svc = EventService(session)
            event = await event_svc.get_by_id(event_id)

        if event is None:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="Мероприятие не найдено.",
            )
            return

        date_str = event.date.strftime("%d.%m.%Y %H:%M")
        text = (
            f"🎫 {event.title}\n\n"
            f"{event.description or 'Описание отсутствует'}\n\n"
            f"📅 {date_str}\n"
            f"📍 {event.location or 'Не указано'}\n"
            f"💰 {event.price:.0f}₽\n"
            f"🎟 Осталось билетов: {event.available_tickets}/{event.total_tickets}\n\n"
            f"Купить: /buy {event.id}"
        )
        await self.bot.send_message(chat_id=message.chat.id, text=text)

    async def cmd_buy(self, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="Укажите ID мероприятия: /buy <id>",
            )
            return

        try:
            event_id = UUID(args[1])
        except ValueError:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="Неверный ID мероприятия.",
            )
            return

        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                ticket = await ticket_svc.buy_ticket(user_id, event_id)
                await self.bot.send_message(
                    chat_id=message.chat.id,
                    text=(
                        f"✅ Билет куплен!\n"
                        f"Номер билета: {ticket.id}\n\n"
                        f"Используйте /my_tickets для просмотра всех билетов."
                    ),
                )
            except ValueError as e:
                await self.bot.send_message(
                    chat_id=message.chat.id,
                    text=f"❌ {e}",
                )

    async def cmd_my_tickets(self, message: Message):
        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            tickets = await ticket_svc.get_user_tickets(user_id)

        if not tickets:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="У вас нет билетов.",
            )
            return

        lines = []
        for t in tickets:
            date_str = t["purchase_date"].strftime("%d.%m.%Y %H:%M")
            status_emoji = "✅" if t["status"] == "active" else "❌"
            lines.append(
                f"{status_emoji} {t['event_title']}\n"
                f"🆔 {t['id']}\n"
                f"📅 Куплен: {date_str}\n"
                f"📌 Статус: {t['status']}"
            )

        await self.bot.send_message(
            chat_id=message.chat.id,
            text="\n\n".join(lines),
        )

    async def cmd_cancel(self, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="Укажите ID билета: /cancel <id>",
            )
            return

        try:
            ticket_id = UUID(args[1])
        except ValueError:
            await self.bot.send_message(
                chat_id=message.chat.id,
                text="Неверный ID билета.",
            )
            return

        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                await ticket_svc.cancel_ticket(ticket_id, user_id)
                await self.bot.send_message(
                    chat_id=message.chat.id,
                    text="✅ Билет возвращён.",
                )
            except ValueError as e:
                await self.bot.send_message(
                    chat_id=message.chat.id,
                    text=f"❌ {e}",
                )

    async def run(self):
        await self.bot.run_polling()

    async def stop(self):
        await self.bot.close()
