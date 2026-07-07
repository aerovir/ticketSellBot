import logging
from uuid import UUID

from vkbottle import Bot as VKBot
from vkbottle.bot import Message

from app.config import settings
from app.core.database import async_session_factory
from app.core.models import PlatformType
from app.core.services import UserService, EventService, TicketService
from app.platforms.base import PlatformBot

logger = logging.getLogger("ticketbot.vk")


class VKPlatformBot(PlatformBot):
    def __init__(self):
        if not settings.vk_token:
            raise ValueError("VK_TOKEN is not set")
        self.bot = VKBot(token=settings.vk_token)
        self._register_handlers()

    def _register_handlers(self):
        self.bot.on.message(text="/start")(self.cmd_start)
        self.bot.on.message(text="/events")(self.cmd_events)
        self.bot.on.message(text="/event <event_id>")(self.cmd_event)
        self.bot.on.message(text="/buy <event_id>")(self.cmd_buy)
        self.bot.on.message(text="/my_tickets")(self.cmd_my_tickets)
        self.bot.on.message(text="/cancel <ticket_id>")(self.cmd_cancel)

    async def _get_user_name(self, message: Message) -> str:
        """Безопасно получает имя пользователя."""
        if message.sender:
            parts = [message.sender.first_name or "", message.sender.last_name or ""]
            return " ".join(parts).strip() or str(message.from_id)
        return str(message.from_id)

    async def _get_user_id(self, message: Message) -> UUID:
        async with async_session_factory() as session:
            user_svc = UserService(session)
            user = await user_svc.get_or_create(
                platform=PlatformType.vk,
                platform_user_id=str(message.from_id),
                name=await self._get_user_name(message),
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
        await message.answer(text)

    async def cmd_events(self, message: Message):
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
                f"📌 {e.title}\n"
                f"📅 {date_str}\n"
                f"📍 {e.location or 'Не указано'}\n"
                f"💰 {e.price:.0f}₽ | Осталось: {e.available_tickets}/{e.total_tickets}\n"
                f"🎫 /event {e.id}"
            )

        await message.answer("\n\n".join(lines))

    async def cmd_event(self, message: Message, event_id: str):
        try:
            eid = UUID(event_id)
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        async with async_session_factory() as session:
            event_svc = EventService(session)
            event = await event_svc.get_by_id(eid)

        if event is None:
            await message.answer("Мероприятие не найдено.")
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
        await message.answer(text)

    async def cmd_buy(self, message: Message, event_id: str):
        try:
            eid = UUID(event_id)
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                ticket = await ticket_svc.buy_ticket(user_id, eid)
                await message.answer(
                    f"✅ Билет куплен!\n"
                    f"Номер билета: {ticket.id}\n\n"
                    f"Используйте /my_tickets для просмотра всех билетов."
                )
            except ValueError as e:
                await message.answer(f"❌ {e}")

    async def cmd_my_tickets(self, message: Message):
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
                f"{status_emoji} {t['event_title']}\n"
                f"🆔 {t['id']}\n"
                f"📅 Куплен: {date_str}\n"
                f"📌 Статус: {t['status']}"
            )

        await message.answer("\n\n".join(lines))

    async def cmd_cancel(self, message: Message, ticket_id: str):
        try:
            tid = UUID(ticket_id)
        except ValueError:
            await message.answer("Неверный ID билета.")
            return

        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                await ticket_svc.cancel_ticket(tid, user_id)
                await message.answer("✅ Билет возвращён.")
            except ValueError as e:
                await message.answer(f"❌ {e}")

    async def run(self):
        import asyncio

        retries = 0
        max_retries = 10
        while retries < max_retries:
            try:
                await self.bot.run()
                return
            except Exception as e:
                retries += 1
                wait = min(retries * 5, 60)
                logger.warning(
                    "VK polling error (попытка %d/%d): %s. Ждём %dс...",
                    retries, max_retries, e, wait,
                )
                await asyncio.sleep(wait)

    async def stop(self):
        await self.bot.close()
