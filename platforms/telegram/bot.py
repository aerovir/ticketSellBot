from typing import Optional
from uuid import UUID

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from core.database import async_session_factory
from core.models import PlatformType
from core.services import UserService, EventService, TicketService
from platforms.base import PlatformBot


class TelegramBot(PlatformBot):
    def __init__(self):
        if not settings.telegram_token:
            raise ValueError("TELEGRAM_TOKEN is not set")
        self.bot = Bot(token=settings.telegram_token)
        self.dp = Dispatcher()
        self._register_handlers()

    def _register_handlers(self):
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_events, Command("events"))
        self.dp.message.register(self.cmd_event, Command("event"))
        self.dp.message.register(self.cmd_buy, Command("buy"))
        self.dp.message.register(self.cmd_my_tickets, Command("my_tickets"))
        self.dp.message.register(self.cmd_cancel, Command("cancel"))

    async def _get_user_id(self, message: types.Message) -> UUID:
        async with async_session_factory() as session:
            user_svc = UserService(session)
            user = await user_svc.get_or_create(
                platform=PlatformType.telegram,
                platform_user_id=str(message.from_user.id),
                name=message.from_user.full_name,
            )
            return user.id

    async def cmd_start(self, message: types.Message):
        await self._get_user_id(message)
        text = (
            "🎫 <b>TicketBot</b>\n\n"
            "Доступные команды:\n"
            "/events — список мероприятий\n"
            "/event &lt;id&gt; — детали мероприятия\n"
            "/buy &lt;id&gt; — купить билет\n"
            "/my_tickets — мои билеты\n"
            "/cancel &lt;id&gt; — отменить билет"
        )
        await message.answer(text, parse_mode="HTML")

    async def cmd_events(self, message: types.Message):
        async with async_session_factory() as session:
            event_svc = EventService(session)
            events = await event_svc.list_upcoming()

        if not events:
            await message.answer("😔 Нет предстоящих мероприятий.")
            return

        lines = []
        for e in events:
            date_str = e.date.strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"📌 <b>{e.title}</b>\n"
                f"📅 {date_str}\n"
                f"📍 {e.location or 'Не указано'}\n"
                f"💰 {e.price:.0f}₽ | Осталось: {e.available_tickets}/{e.total_tickets}\n"
                f"🎫 /event {e.id}\n"
            )

        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_event(self, message: types.Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Укажите ID мероприятия: /event &lt;id&gt;")
            return

        try:
            event_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        async with async_session_factory() as session:
            event_svc = EventService(session)
            event = await event_svc.get_by_id(event_id)

        if event is None:
            await message.answer("Мероприятие не найдено.")
            return

        date_str = event.date.strftime("%d.%m.%Y %H:%M")
        text = (
            f"🎫 <b>{event.title}</b>\n\n"
            f"{event.description or 'Описание отсутствует'}\n\n"
            f"📅 {date_str}\n"
            f"📍 {event.location or 'Не указано'}\n"
            f"💰 {event.price:.0f}₽\n"
            f"🎟 Осталось билетов: {event.available_tickets}/{event.total_tickets}"
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🎟 Купить билет",
                    callback_data=f"buy:{event.id}"
                )]
            ]
        )

        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    async def cmd_buy(self, message: types.Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Укажите ID мероприятия: /buy &lt;id&gt;")
            return

        try:
            event_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                ticket = await ticket_svc.buy_ticket(user_id, event_id)
                await message.answer(
                    f"✅ Билет куплен!\n"
                    f"Номер билета: <code>{ticket.id}</code>\n\n"
                    f"Используйте /my_tickets для просмотра всех билетов.",
                    parse_mode="HTML",
                )
            except ValueError as e:
                await message.answer(f"❌ {e}")

    async def cmd_my_tickets(self, message: types.Message):
        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            tickets = await ticket_svc.get_user_tickets(user_id)

        if not tickets:
            await message.answer("У вас нет билетов.")
            return

        lines = []
        for t in tickets:
            date_str = t["purchase_date"].strftime("%d.%m.%Y %H:%M")
            status_emoji = "✅" if t["status"] == "active" else "❌"
            lines.append(
                f"{status_emoji} <b>{t['event_title']}</b>\n"
                f"🆔 <code>{t['id']}</code>\n"
                f"📅 Куплен: {date_str}\n"
                f"📌 Статус: {t['status']}\n"
            )

        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_cancel(self, message: types.Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Укажите ID билета: /cancel &lt;id&gt;")
            return

        try:
            ticket_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID билета.")
            return

        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                await ticket_svc.cancel_ticket(ticket_id, user_id)
                await message.answer("✅ Билет возвращён.")
            except ValueError as e:
                await message.answer(f"❌ {e}")

    async def run(self):
        import asyncio

        retries = 0
        max_retries = 10
        while retries < max_retries:
            try:
                await self.dp.start_polling(self.bot)
                return
            except Exception as e:
                retries += 1
                wait = min(retries * 5, 60)
                logger.warning(
                    "Telegram polling error (попытка %d/%d): %s. Ждём %dс...",
                    retries, max_retries, e, wait,
                )
                await asyncio.sleep(wait)

    async def stop(self):
        await self.bot.session.close()
