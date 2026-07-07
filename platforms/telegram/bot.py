import logging
from uuid import UUID

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from core.database import async_session_factory
from core.models import PlatformType
from core.services import UserService, EventService, TicketService
from platforms.base import PlatformBot
from platforms.telegram.channel import ChannelManager

logger = logging.getLogger("ticketbot.telegram")


# ─── FSM States для создания мероприятия ──────────────────────────────────
class CreateEvent(StatesGroup):
    title = State()
    description = State()
    date = State()
    location = State()
    price = State()
    tickets = State()
    confirm = State()


class TelegramBot(PlatformBot):
    def __init__(self):
        if not settings.telegram_token:
            raise ValueError("TELEGRAM_TOKEN is not set")
        self.bot = Bot(token=settings.telegram_token)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.channel = ChannelManager(self.bot)
        self._register_handlers()

    def _register_handlers(self):
        # ─── Личные сообщения (DM) ─────────────────────
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_events, Command("events"))
        self.dp.message.register(self.cmd_event, Command("event"))
        self.dp.message.register(self.cmd_buy, Command("buy"))
        self.dp.message.register(self.cmd_my_tickets, Command("my_tickets"))
        self.dp.message.register(self.cmd_cancel, Command("cancel"))

        # ─── Админ-команды ─────────────────────────────
        self.dp.message.register(self.admin_menu, Command("admin"))
        self.dp.message.register(self.admin_create_event, Command("create_event"))
        self.dp.message.register(self.admin_events_all, Command("events_all"))
        self.dp.message.register(self.admin_deactivate, Command("deactivate"))
        self.dp.message.register(self.admin_activate, Command("activate"))
        self.dp.message.register(self.admin_stats, Command("stats"))

        # ─── FSM: шаги создания мероприятия ────────────
        self.dp.message.register(self.fsm_title, CreateEvent.title)
        self.dp.message.register(self.fsm_description, CreateEvent.description)
        self.dp.message.register(self.fsm_date, CreateEvent.date)
        self.dp.message.register(self.fsm_location, CreateEvent.location)
        self.dp.message.register(self.fsm_price, CreateEvent.price)
        self.dp.message.register(self.fsm_tickets, CreateEvent.tickets)
        self.dp.message.register(self.fsm_confirm, CreateEvent.confirm)

        # Отмена во время FSM
        self.dp.message.register(self.fsm_cancel, Command("cancel"), StateFilter(CreateEvent))

        # ─── Callback-запросы (инлайн-кнопки) ──────────
        self.dp.callback_query.register(self.cmd_callback)

        # ─── Сообщения из канала (channel_post) ────────
        self.dp.channel_post.register(self.channel_cmd_events, Command("events"))
        self.dp.channel_post.register(self.channel_cmd_event, Command("event"))

    # ═══════════════════════════════════════════════════════
    # ХЕНДЛЕРЫ ЛИЧНЫХ СООБЩЕНИЙ
    # ═══════════════════════════════════════════════════════

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
            "Я помогаю покупать билеты на мероприятия.\n\n"
            "Подпишитесь на наш канал, чтобы получать анонсы:\n"
            f"{self._channel_link()}\n\n"
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
                await session.commit()
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
                await session.commit()
                await message.answer("✅ Билет возвращён.")
            except ValueError as e:
                await message.answer(f"❌ {e}")

    # ═══════════════════════════════════════════════════════
    # АДМИН-ХЕНДЛЕРЫ
    # ═══════════════════════════════════════════════════════

    def _is_admin(self, user_id: int) -> bool:
        """Check if a Telegram user is in the admin list."""
        if not settings.admin_telegram_ids:
            return False
        admin_ids = [x.strip() for x in settings.admin_telegram_ids.split(",") if x.strip()]
        return str(user_id) in admin_ids

    async def admin_menu(self, message: types.Message):
        """Show admin panel menu."""
        if not self._is_admin(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return
        text = (
            "🎫 <b>Панель администратора</b>\n\n"
            "/create_event — создать мероприятие\n"
            "/events_all — все мероприятия\n"
            "/stats &lt;id&gt; — статистика продаж\n"
            "/deactivate &lt;id&gt; — отключить мероприятие\n"
            "/activate &lt;id&gt; — включить мероприятие"
        )
        await message.answer(text, parse_mode="HTML")

    # ─── FSM: Создание мероприятия ──────────────────────────────────────

    async def admin_create_event(self, message: types.Message, state: FSMContext):
        """Start the create-event wizard."""
        if not self._is_admin(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return
        await state.set_state(CreateEvent.title)
        await message.answer(
            "📝 Введите <b>название</b> мероприятия:",
            parse_mode="HTML",
        )

    async def fsm_cancel(self, message: types.Message, state: FSMContext):
        """Cancel the FSM at any step."""
        await state.clear()
        await message.answer("❌ Создание мероприятия отменено.")

    async def fsm_title(self, message: types.Message, state: FSMContext):
        await state.update_data(title=message.text.strip())
        await state.set_state(CreateEvent.description)
        await message.answer(
            "📝 Введите <b>описание</b> мероприятия\n"
            "Или отправьте <code>-</code> чтобы пропустить.",
            parse_mode="HTML",
        )

    async def fsm_description(self, message: types.Message, state: FSMContext):
        text = message.text.strip()
        if text == "-":
            await state.update_data(description=None)
        else:
            await state.update_data(description=text)
        await state.set_state(CreateEvent.date)
        await message.answer(
            "📅 Введите <b>дату и время</b> в формате:\n"
            "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Пример: <code>25.12.2026 19:00</code>",
            parse_mode="HTML",
        )

    async def fsm_date(self, message: types.Message, state: FSMContext):
        text = message.text.strip()
        try:
            from datetime import datetime
            date = datetime.strptime(text, "%d.%m.%Y %H:%M")
        except ValueError:
            await message.answer(
                "❌ Неверный формат. Используйте <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
                "Пример: <code>25.12.2026 19:00</code>",
                parse_mode="HTML",
            )
            return
        await state.update_data(date=date.isoformat())
        await state.set_state(CreateEvent.location)
        await message.answer(
            "📍 Введите <b>место проведения</b>\n"
            "Или отправьте <code>-</code> чтобы пропустить.",
            parse_mode="HTML",
        )

    async def fsm_location(self, message: types.Message, state: FSMContext):
        text = message.text.strip()
        if text == "-":
            await state.update_data(location=None)
        else:
            await state.update_data(location=text)
        await state.set_state(CreateEvent.price)
        await message.answer(
            "💰 Введите <b>цену билета</b> (число, в рублях):",
            parse_mode="HTML",
        )

    async def fsm_price(self, message: types.Message, state: FSMContext):
        text = message.text.strip().replace(",", ".")
        try:
            price = float(text)
            if price < 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Введите число (например: <code>1500</code> или <code>0</code> для бесплатного):", parse_mode="HTML")
            return
        await state.update_data(price=price)
        await state.set_state(CreateEvent.tickets)
        await message.answer(
            "🎟 Введите <b>количество билетов</b> (целое число):",
            parse_mode="HTML",
        )

    async def fsm_tickets(self, message: types.Message, state: FSMContext):
        text = message.text.strip()
        try:
            tickets = int(text)
            if tickets <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Введите целое число больше 0 (например: <code>100</code>):", parse_mode="HTML")
            return
        data = await state.update_data(tickets=tickets)
        await state.set_state(CreateEvent.confirm)

        # Показать сводку
        from datetime import datetime
        date = datetime.fromisoformat(data["date"])
        date_str = date.strftime("%d.%m.%Y %H:%M")
        desc = data.get("description") or "—"
        loc = data.get("location") or "—"
        summary = (
            f"📝 <b>Проверьте данные:</b>\n\n"
            f"📌 Название: {data['title']}\n"
            f"📖 Описание: {desc}\n"
            f"📅 Дата: {date_str}\n"
            f"📍 Место: {loc}\n"
            f"💰 Цена: {data['price']:.0f}₽\n"
            f"🎟 Билетов: {data['tickets']}\n\n"
            f"Подтвердить создание?"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data="admin:confirm_create"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel_create"),
                ]
            ]
        )
        await message.answer(summary, parse_mode="HTML", reply_markup=kb)

    async def fsm_confirm(self, message: types.Message, state: FSMContext):
        """Handle text messages in confirm state (ignore, only buttons work)."""
        await message.answer("Используйте кнопки ниже для подтверждения или отмены.")

    # ─── /events_all ─────────────────────────────────────────────────────

    async def admin_events_all(self, message: types.Message):
        """Show ALL events (admin view)."""
        if not self._is_admin(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return
        async with async_session_factory() as session:
            svc = EventService(session)
            events = await svc.list_all()

        if not events:
            await message.answer("Нет мероприятий.")
            return

        lines = ["🎫 <b>Все мероприятия:</b>\n"]
        for e in events:
            status = "🟢" if e.is_active else "🔴"
            date_str = e.date.strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"{status} <b>{e.title}</b>\n"
                f"📅 {date_str}\n"
                f"🎟 {e.available_tickets}/{e.total_tickets}\n"
            )
            if e.is_active:
                lines.append(f"/stats {e.id} | /deactivate {e.id}\n")
            else:
                lines.append(f"/stats {e.id} | /activate {e.id}\n")

        await message.answer("\n".join(lines), parse_mode="HTML")

    # ─── /deactivate /activate ───────────────────────────────────────────

    async def _toggle_active(self, message: types.Message, activate: bool):
        """Toggle event active state."""
        if not self._is_admin(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            cmd = "activate" if activate else "deactivate"
            await message.answer(f"Укажите ID мероприятия: /{cmd} &lt;id&gt;")
            return
        try:
            event_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        async with async_session_factory() as session:
            svc = EventService(session)
            event = await svc.set_active(event_id, activate)
            await session.commit()

        if event is None:
            await message.answer("Мероприятие не найдено.")
            return

        verb = "включено" if activate else "отключено"
        await message.answer(f"✅ Мероприятие «{event.title}» {verb}.")

    async def admin_deactivate(self, message: types.Message):
        await self._toggle_active(message, activate=False)

    async def admin_activate(self, message: types.Message):
        await self._toggle_active(message, activate=True)

    # ─── /stats ──────────────────────────────────────────────────────────

    async def admin_stats(self, message: types.Message):
        """Show event sales stats."""
        if not self._is_admin(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Укажите ID мероприятия: /stats &lt;id&gt;")
            return
        try:
            event_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        async with async_session_factory() as session:
            svc = EventService(session)
            try:
                stats = await svc.get_event_stats(event_id)
                event = await svc.get_by_id(event_id)
            except ValueError as e:
                await message.answer(f"❌ {e}")
                return

        if event is None:
            await message.answer("Мероприятие не найдено.")
            return

        active = stats["sold"] - stats["refunded"]
        text = (
            f"📊 <b>Статистика: {event.title}</b>\n\n"
            f"🎟 Всего билетов: {stats['total_tickets']}\n"
            f"✅ Продано: {stats['sold']} ({stats['sold_pct']}%)\n"
            f"🔄 Возвращено: {stats['refunded']}\n"
            f"🏷 Активных: {active}\n"
            f"💰 Выручка: {stats['revenue']:.0f}₽\n\n"
            f"📅 {event.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"🟢 {'Активно' if event.is_active else 'Отключено'}"
        )
        await message.answer(text, parse_mode="HTML")

    # ─── Callback-запросы (инлайн-кнопки) ────────────────────────────────

    async def cmd_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Handle all callback queries (admin panel + other)."""
        data = callback.data

        if data == "admin:confirm_create":
            # Create event from FSM data
            fsm_data = await state.get_data()
            from datetime import datetime
            event_date = datetime.fromisoformat(fsm_data["date"])

            async with async_session_factory() as session:
                svc = EventService(session)
                event = await svc.create(
                    title=fsm_data["title"],
                    description=fsm_data.get("description"),
                    date=event_date,
                    location=fsm_data.get("location"),
                    price=fsm_data["price"],
                    total_tickets=fsm_data["tickets"],
                )
                await session.commit()

            await state.clear()
            await callback.answer()
            await callback.message.edit_text(
                f"✅ Мероприятие «{event.title}» создано!\n"
                f"ID: <code>{event.id}</code>",
                parse_mode="HTML",
            )
            # Post announcement to channel
            await self.post_announcement(event.id)

        elif data == "admin:cancel_create":
            await state.clear()
            await callback.answer()
            await callback.message.edit_text("❌ Создание отменено.")

        else:
            await callback.answer("Команда не распознана", show_alert=True)

    # ═══════════════════════════════════════════════════════
    # ХЕНДЛЕРЫ КАНАЛА (только просмотр)
    # ═══════════════════════════════════════════════════════

    async def channel_cmd_events(self, channel_post: types.Message):
        """/events в канале — выводит список прямо в канал."""
        async with async_session_factory() as session:
            event_svc = EventService(session)
            events = await event_svc.list_upcoming()

        if not events:
            await channel_post.answer("😔 Нет предстоящих мероприятий.")
            return

        lines = ["🎫 <b>Предстоящие мероприятия:</b>\n"]
        for e in events:
            date_str = e.date.strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"📌 <b>{e.title}</b>\n"
                f"📅 {date_str}\n"
                f"📍 {e.location or 'Не указано'}\n"
                f"💰 {e.price:.0f}₽ | Осталось: {e.available_tickets}/{e.total_tickets}\n"
                f"➡️ Купить: @{self.bot.username} /buy {e.id}\n"
            )

        await channel_post.answer("\n".join(lines), parse_mode="HTML")

    async def channel_cmd_event(self, channel_post: types.Message):
        """/event <id> в канале — детали мероприятия прямо в канал."""
        args = channel_post.text.split(maxsplit=1)
        if len(args) < 2:
            await channel_post.answer("Укажите ID мероприятия: /event &lt;id&gt;")
            return

        try:
            event_id = UUID(args[1])
        except ValueError:
            await channel_post.answer("Неверный ID мероприятия.")
            return

        async with async_session_factory() as session:
            event_svc = EventService(session)
            event = await event_svc.get_by_id(event_id)

        if event is None:
            await channel_post.answer("Мероприятие не найдено.")
            return

        date_str = event.date.strftime("%d.%m.%Y %H:%M")
        text = (
            f"🎫 <b>{event.title}</b>\n\n"
            f"{event.description or 'Описание отсутствует'}\n\n"
            f"📅 {date_str}\n"
            f"📍 {event.location or 'Не указано'}\n"
            f"💰 {event.price:.0f}₽\n"
            f"🎟 Осталось билетов: {event.available_tickets}/{event.total_tickets}\n\n"
            f"👇 Для покупки напишите мне в личку:\n"
            f"@{self.bot.username} — команда /buy {event.id}"
        )

        await channel_post.answer(text, parse_mode="HTML")

    # ═══════════════════════════════════════════════════════
    # ПУБЛИЧНЫЕ МЕТОДЫ
    # ═══════════════════════════════════════════════════════

    async def post_announcement(self, event_id: UUID):
        """Отправить анонс мероприятия в канал. Вызывается из seed/admin."""
        async with async_session_factory() as session:
            event_svc = EventService(session)
            event = await event_svc.get_by_id(event_id)
            if event:
                await self.channel.post_event_announcement(event)

    def _channel_link(self) -> str:
        """Возвращает ссылку на канал или заглушку."""
        cid = settings.telegram_channel_id
        if not cid:
            return ""
        if cid.startswith("@"):
            return f"👉 {cid}"
        return f"👉 <a href='https://t.me/{cid}'>Канал</a>"

    # ═══════════════════════════════════════════════════════
    # ЗАПУСК / ОСТАНОВКА
    # ═══════════════════════════════════════════════════════

    async def run(self):
        import asyncio

        retries = 0
        max_retries = 10
        while retries < max_retries:
            try:
                await self.dp.start_polling(
                    self.bot,
                    allowed_updates=["message", "channel_post", "callback_query"],
                )
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
