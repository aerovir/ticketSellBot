import logging
from datetime import datetime, timezone
from uuid import UUID

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject, ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat, BotCommandScopeAllPrivateChats

from sqlalchemy import select, func

from app.config import settings
from app.core.database import async_session_factory
from app.core.models import (
    PlatformType, Channel, User, Event, Ticket, Payment,
    TicketStatus, PaymentStatus,
)
from app.core.services import UserService, EventService, TicketService, ChannelService, ChannelAdminService
from app.platforms.base import PlatformBot
from app.platforms.telegram.channel import ChannelManager

logger = logging.getLogger("ticketbot.telegram")

PAGE_SIZE = 5  # мероприятий/билетов на страницу

# ─── Наборы команд для Menu Button ────────────────────────────────
USER_COMMANDS = [
    BotCommand(command="start", description="🚀 Приветствие"),
    BotCommand(command="events", description="📋 Список мероприятий"),
    BotCommand(command="event", description="📌 Детали мероприятия"),
    BotCommand(command="buy", description="🎟 Купить билет"),
    BotCommand(command="my_tickets", description="🎫 Мои билеты"),
    BotCommand(command="cancel", description="↩️ Отменить билет"),
]

ADMIN_COMMANDS = [
    BotCommand(command="admin", description="🎛 Панель управления"),
    BotCommand(command="create_event", description="➕ Создать мероприятие"),
    BotCommand(command="events_all", description="📋 Все мероприятия канала"),
    BotCommand(command="deactivate", description="⏸ Отключить мероприятие"),
    BotCommand(command="activate", description="▶️ Включить мероприятие"),
    BotCommand(command="stats", description="📊 Статистика продаж"),
    BotCommand(command="repost_events", description="🔄 Репост анонсов"),
    BotCommand(command="my_channels", description="📢 Мои каналы"),
]

SUPER_ADMIN_COMMANDS = [
    BotCommand(command="subscribe", description="🟢 Подписать канал"),
    BotCommand(command="unsubscribe", description="🔴 Отписать канал"),
    BotCommand(command="stats_all", description="📊 Общая статистика"),
    BotCommand(command="list_channels", description="📋 Список каналов"),
    BotCommand(command="channel_info", description="ℹ️ Инфо о канале"),
    BotCommand(command="user_info", description="👥 Инфо о пользователе"),
    BotCommand(command="admin_cancel", description="✅ Отменить билет"),
    BotCommand(command="broadcast", description="📢 Рассылка"),
    BotCommand(command="health", description="🩺 Статус бота"),
    BotCommand(command="check_expired", description="🔍 Проверить подписки"),
    BotCommand(command="change_admin", description="🔄 Сменить админа"),
]


# ─── FSM States для создания мероприятия ──────────────────────────────────
class CreateEvent(StatesGroup):
    title = State()
    description = State()
    date = State()
    location = State()
    price = State()
    tickets = State()
    confirm = State()


class BroadcastFSM(StatesGroup):
    """FSM для отправки рассылки во все каналы."""
    text = State()


class AwaitingAdminInput(StatesGroup):
    """FSM для ввода параметра после нажатия кнопки админ-меню."""
    text = State()


class TelegramBot(PlatformBot):
    def __init__(self):
        if not settings.telegram_token:
            raise ValueError("TELEGRAM_TOKEN is not set")
        self.bot = Bot(token=settings.telegram_token)
        self.dp = Dispatcher(storage=MemoryStorage())
        self._bot_username = None  # будет заполнен в run()
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

        # ─── Админ-команды (текстовые) ────────────────
        self.dp.message.register(self.admin_menu, Command("admin"))
        self.dp.message.register(self.admin_create_event, Command("create_event"))
        self.dp.message.register(self.admin_events_all, Command("events_all"))
        self.dp.message.register(self.admin_deactivate, Command("deactivate"))
        self.dp.message.register(self.admin_activate, Command("activate"))
        self.dp.message.register(self.admin_stats, Command("stats"))
        self.dp.message.register(self.admin_repost_events, Command("repost_events"))
        self.dp.message.register(self.admin_subscribe, Command("subscribe"))
        self.dp.message.register(self.admin_unsubscribe, Command("unsubscribe"))
        self.dp.message.register(self.admin_my_channels, Command("my_channels"))

        # ─── Супер-админ команды (текстовые) ─────────
        self.dp.message.register(self.sa_stats_all, Command("stats_all"))
        self.dp.message.register(self.sa_list_channels, Command("list_channels"))
        self.dp.message.register(self.sa_channel_info, Command("channel_info"))
        self.dp.message.register(self.sa_user_info, Command("user_info"))
        self.dp.message.register(self.sa_admin_cancel, Command("admin_cancel"))
        self.dp.message.register(self.sa_broadcast, Command("broadcast"))
        self.dp.message.register(self.sa_health, Command("health"))
        self.dp.message.register(self.sa_check_expired, Command("check_expired"))
        self.dp.message.register(self.sa_change_admin, Command("change_admin"))

        # ─── Обработчик текстового ввода для broadcast ──
        self.dp.message.register(self._handle_broadcast_input, StateFilter(BroadcastFSM.text))

        # ─── Обработчик ввода параметра для кнопок админ-меню ──
        self.dp.message.register(self._handle_admin_input, StateFilter(AwaitingAdminInput.text))

        # ─── Обновления участников канала (my_chat_member) ──
        self.dp.my_chat_member.register(self.on_chat_member_update)

        # ─── FSM: шаги создания мероприятия ────────────
        self.dp.message.register(self.fsm_title, CreateEvent.title)
        self.dp.message.register(self.fsm_description, CreateEvent.description)
        self.dp.message.register(self.fsm_date, CreateEvent.date)
        self.dp.message.register(self.fsm_location, CreateEvent.location)
        self.dp.message.register(self.fsm_price, CreateEvent.price)
        self.dp.message.register(self.fsm_tickets, CreateEvent.tickets)

        # Отмена во время FSM
        self.dp.message.register(self.fsm_cancel, Command("cancel"), StateFilter(CreateEvent))
        self.dp.message.register(self.fsm_cancel, Command("cancel"), StateFilter(BroadcastFSM))
        self.dp.message.register(self.fsm_cancel, Command("cancel"), StateFilter(AwaitingAdminInput))

        # ─── Callback-запросы (инлайн-кнопки) ──────────
        self.dp.callback_query.register(self.cmd_callback)

        # ─── Сообщения из канала (channel_post) ────────
        self.dp.channel_post.register(self.channel_cmd_events, Command("events"))
        self.dp.channel_post.register(self.channel_cmd_event, Command("event"))

    # ═══════════════════════════════════════════════════════
    # ХЕНДЛЕРЫ ЛИЧНЫХ СООБЩЕНИЙ
    # ═══════════════════════════════════════════════════════

    async def _get_user_id(self, message: types.Message) -> UUID:
        return await self._resolve_user_id(
            str(message.from_user.id),
            message.from_user.full_name,
        )

    async def _resolve_user_id(self, platform_user_id: str, name: str = "") -> UUID:
        """Find or create user by Telegram ID, return internal UUID."""
        async with async_session_factory() as session:
            user_svc = UserService(session)
            user = await user_svc.get_or_create(
                platform=PlatformType.telegram,
                platform_user_id=platform_user_id,
                name=name,
            )
            await session.commit()
            return user.id

    async def cmd_start(self, message: types.Message, command: CommandObject | None = None):
        """Старт /start — приветствие. Обрабатывает payload из deep link."""
        payload = command.args if command else None

        # Если пришли по deep link из канала с buy_<event_id>
        if payload and payload.startswith("buy_"):
            try:
                event_id = UUID(payload[4:])  # убираем "buy_"
                await self._do_buy_ticket(message, event_id)
                return
            except (ValueError, IndexError):
                pass

        await self._get_user_id(message)

        # Установить Menu Button под роль пользователя
        await self._update_user_commands(message.from_user.id)

        text = (
            "🎫 <b>TicketBot</b>\n\n"
            "Я помогаю покупать билеты на мероприятия.\n\n"
            "Подпишитесь на канал, где публикуются анонсы, "
            "и покупайте билеты через inline-кнопки.\n\n"
            "ℹ️ Нажмите кнопку меню <b>☰</b> в левом нижнем углу, "
            "чтобы увидеть все доступные команды."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список мероприятий", callback_data="ev_page:0")],
            [InlineKeyboardButton(text="🎫 Мои билеты", callback_data="channel_my_tickets")],
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    async def cmd_events(self, message: types.Message, page: int = 0):
        """Список мероприятий с пагинацией."""
        async with async_session_factory() as session:
            event_svc = EventService(session)
            events = await event_svc.list_upcoming()

        if not events:
            await message.answer("😔 Нет предстоящих мероприятий.")
            return

        await self._send_event_page(message.answer, events, page)

    async def _send_event_page(self, send_method, events: list, page: int):
        """Отправить страницу мероприятий с навигацией."""
        total_pages = max(1, (len(events) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * PAGE_SIZE
        end = start + PAGE_SIZE
        page_events = events[start:end]

        lines = [f"🎫 <b>Мероприятия</b> (стр. {page + 1}/{total_pages}):\n"]
        for e in page_events:
            date_str = e.date.strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"📌 <b>{e.title}</b>\n"
                f"📅 {date_str}\n"
                f"📍 {e.location or 'Не указано'}\n"
                f"💰 {e.price:.0f}₽ | Осталось: {e.available_tickets}/{e.total_tickets}\n"
            )

        # Клавиатура с навигацией
        kb_rows = []

        # Кнопки навигации по страницам
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"ev_page:{page - 1}"))
        nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="ev_page:current"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"ev_page:{page + 1}"))
        if nav_row:
            kb_rows.append(nav_row)

        # Кнопки деталей для событий на этой странице
        for e in page_events:
            kb_rows.append([
                InlineKeyboardButton(
                    text=f"🎫 {e.title[:30]}",
                    callback_data=f"ev_detail:{e.id}",
                )
            ])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None
        await send_method("\n".join(lines), parse_mode="HTML", reply_markup=kb)

    async def _do_buy_ticket(self, message: types.Message, event_id: UUID):
        """Купить билет (общая логика для /buy и deep link)."""
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

    async def cmd_event(self, message: types.Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Список мероприятий", callback_data="ev_page:0")],
            ])
            await message.answer(
                "📌 Чтобы посмотреть детали мероприятия, выберите его из списка:",
                reply_markup=kb,
            )
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

        await self._send_event_detail(message.answer, event)

    async def _send_event_detail(self, send_method, event):
        """Отправить детали мероприятия с inline-кнопками."""
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
                )],
                [InlineKeyboardButton(
                    text="← К списку",
                    callback_data="ev_page:0"
                )],
            ]
        )

        await send_method(text, parse_mode="HTML", reply_markup=kb)

    async def cmd_buy(self, message: types.Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Список мероприятий", callback_data="ev_page:0")],
            ])
            await message.answer(
                "🎟 Чтобы купить билет, выберите мероприятие из списка:",
                reply_markup=kb,
            )
            return

        try:
            event_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        await self._get_user_id(message)
        await self._do_buy_ticket(message, event_id)

    async def cmd_my_tickets(self, message: types.Message):
        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            tickets = await ticket_svc.get_user_tickets(user_id)

        if not tickets:
            await message.answer("У вас нет билетов.")
            return

        await self._send_tickets(message.answer, tickets)

    async def _send_tickets(self, send_method, tickets: list):
        """Отправить список билетов с inline-кнопками отмены."""
        lines = ["🎫 <b>Мои билеты:</b>\n"]
        kb_rows = []

        for t in tickets:
            date_str = t["purchase_date"].strftime("%d.%m.%Y %H:%M")
            status_emoji = "✅" if t["status"] == "active" else "❌"
            lines.append(
                f"{status_emoji} <b>{t['event_title']}</b>\n"
                f"🆔 <code>{t['id']}</code>\n"
                f"📅 Куплен: {date_str}\n"
                f"📌 Статус: {t['status']}\n"
            )

            if t["status"] == "active":
                kb_rows.append([
                    InlineKeyboardButton(
                        text=f"↩️ Отменить: {t['event_title'][:25]}",
                        callback_data=f"ticket_cancel:{t['id']}",
                    )
                ])

        # Кнопка "К мероприятиям"
        kb_rows.append([
            InlineKeyboardButton(text="📋 К мероприятиям", callback_data="ev_page:0")
        ])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None
        await send_method("\n".join(lines), parse_mode="HTML", reply_markup=kb)

    async def cmd_cancel(self, message: types.Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎫 Мои билеты", callback_data="channel_my_tickets")],
            ])
            await message.answer(
                "↩️ Чтобы отменить билет, выберите его из списка:",
                reply_markup=kb,
            )
            return

        try:
            ticket_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID билета.")
            return

        await self._do_cancel_ticket(message.answer, ticket_id, message)

    async def _do_cancel_ticket(self, send_method, ticket_id: UUID, message: types.Message):
        """Отменить билет."""
        user_id = await self._get_user_id(message)

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                await ticket_svc.cancel_ticket(ticket_id, user_id)
                await session.commit()
                await send_method("✅ Билет возвращён.")
            except ValueError as e:
                await send_method(f"❌ {e}")

    # ═══════════════════════════════════════════════════════
    # АДМИН-ХЕНДЛЕРЫ
    # ═══════════════════════════════════════════════════════

    def _is_super_admin(self, user_id: int) -> bool:
        """Check if a Telegram user is in the super admin list."""
        if not settings.admin_telegram_ids:
            return False
        admin_ids = [x.strip() for x in settings.admin_telegram_ids.split(",") if x.strip()]
        return str(user_id) in admin_ids

    async def _verify_channel_admin(self, channel: Channel, user_id: int) -> bool | None:
        """Проверить через Telegram API, что пользователь — админ канала и бот в канале.

        Returns:
            True  — пользователь администратор или создатель канала
            False — пользователь НЕ админ (подтверждено API)
            None  — ошибка API (бот не в канале, канал не найден, сетевой сбой)
        """
        try:
            member = await self.bot.get_chat_member(
                chat_id=channel.telegram_channel_id,
                user_id=user_id,
            )
            return member.status in ("administrator", "creator")
        except Exception as e:
            logger.warning(
                "Channel verification failed for %s (admin %s): %s",
                channel.telegram_channel_id, user_id, e,
            )
            return None

    async def _update_user_commands(self, user_id: int):
        """Установить список команд для пользователя в зависимости от его роли.

        Вызывается при старте, при входе в админку и при добавлении бота в канал.
        """
        if self._is_super_admin(user_id):
            commands = USER_COMMANDS + ADMIN_COMMANDS + SUPER_ADMIN_COMMANDS
        else:
            channel = await self._get_admin_channel(user_id)
            if channel:
                commands = USER_COMMANDS + ADMIN_COMMANDS
            else:
                commands = USER_COMMANDS

        await self.bot.set_my_commands(
            commands=commands,
            scope=BotCommandScopeChat(chat_id=user_id),
        )

    async def _get_admin_channel(self, user_id: int) -> Channel | None:
        """Get the channel managed by this Telegram user with an active subscription.

        Поиск через channel_admins (все админы канала). Если Telegram API
        подтверждает что пользователь не админ — удаляем из channel_admins.
        Если API недоступен — доверяем БД.
        """
        async with async_session_factory() as session:
            channel_svc = ChannelService(session)
            admin_svc = ChannelAdminService(session)
            channels = await channel_svc.get_channels_by_admin(str(user_id))
            for channel in channels:
                if await channel_svc.is_subscription_valid(channel.id):
                    verified = await self._verify_channel_admin(channel, user_id)
                    if verified is True:
                        return channel
                    elif verified is False:
                        # API подтвердила: пользователь не админ — удаляем из channel_admins
                        await admin_svc.remove_admin(channel.id, str(user_id))
                        await session.commit()
                        logger.info(
                            "Removed user %s from admins of channel %s (no longer admin)",
                            user_id, channel.telegram_channel_id,
                        )
                        # Другие админы канала могут быть ещё валидны — не деактивируем подписку
                        return None
                    # verified is None — ошибка API (сеть, таймаут, формат ID).
                    # Доверяем БД: подписка активна, пользователь админ.
                    logger.warning(
                        "Returning channel %s for user %s despite Telegram API error",
                        channel.telegram_channel_id, user_id,
                    )
                    return channel

            # Fallback for super-admins: adopt an unassigned active channel
            if self._is_super_admin(user_id):
                unassigned = await channel_svc.get_active_unassigned_channel()
                if unassigned:
                    verified = await self._verify_channel_admin(unassigned, user_id)
                    if verified is True:
                        await admin_svc.sync_admins(unassigned.id, [str(user_id)])
                        await session.commit()
                        logger.info(
                            "Супер-админ %s привязан к каналу %s",
                            user_id, unassigned.telegram_channel_id,
                        )
                        return unassigned
                    if verified is False:
                        logger.info(
                            "Супер-админ %s не админ канала %s",
                            user_id, unassigned.telegram_channel_id,
                        )
                    else:
                        logger.info(
                            "Супер-админ %s не верифицирован для канала %s (ошибка API)",
                            user_id, unassigned.telegram_channel_id,
                        )

            # Fallback: legacy channel
            legacy = await channel_svc.get_by_telegram_id("__legacy__")
            if legacy and await channel_svc.is_subscription_valid(legacy.id):
                verified = await self._verify_channel_admin(legacy, user_id)
                if verified is True:
                    await admin_svc.sync_admins(legacy.id, [str(user_id)])
                    await session.commit()
                    logger.info("Легаси-канал привязан к админу %s", user_id)
                    return legacy
                if verified is False:
                    logger.info(
                        "Легаси-канал: пользователь %s не админ",
                        user_id,
                    )
                else:
                    logger.info(
                        "Легаси-канал: пользователь %s не верифицирован (ошибка API)",
                        user_id,
                    )

        return None

    async def _has_admin_access(self, user_id: int) -> bool:
        """Check if user has admin access (super-admin OR channel admin with active subscription)."""
        if self._is_super_admin(user_id):
            return True
        channel = await self._get_admin_channel(user_id)
        return channel is not None

    def _admin_menu_kb(self, is_super: bool) -> InlineKeyboardMarkup:
        """Build admin menu keyboard. Super-admin sees all buttons."""
        rows = []

        # --- Статистика ---
        stats_row = [
            InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_menu:stats_all"),
            InlineKeyboardButton(text="🔍 Проверить подписки", callback_data="admin_menu:check_expired"),
        ]
        rows.append(stats_row)
        rows.append([
            InlineKeyboardButton(text="📋 Список каналов", callback_data="admin_menu:list_channels"),
        ])

        if is_super:
            rows.append([
                InlineKeyboardButton(text="ℹ️ Инфо о канале", callback_data="admin_menu:channel_info"),
                InlineKeyboardButton(text="👥 Инфо о пользователе", callback_data="admin_menu:user_info"),
            ])
            # --- Управление подписками ---
            rows.append([
                InlineKeyboardButton(text="🟢 Подписать", callback_data="admin_menu:subscribe"),
                InlineKeyboardButton(text="🔴 Отписать", callback_data="admin_menu:unsubscribe"),
            ])
            rows.append([
                InlineKeyboardButton(text="🔄 Сменить админа", callback_data="admin_menu:change_admin"),
            ])
            # --- Действия ---
            rows.append([
                InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_menu:broadcast"),
                InlineKeyboardButton(text="🩺 Здоровье", callback_data="admin_menu:health"),
            ])
            rows.append([
                InlineKeyboardButton(text="✅ Отменить билет", callback_data="admin_menu:admin_cancel"),
            ])

        # --- Общие для всех админов ---
        rows.append([
            InlineKeyboardButton(text="🎫 Создать мероприятие", callback_data="admin_menu:create_event"),
            InlineKeyboardButton(text="📋 Мои мероприятия", callback_data="admin_menu:events_all"),
        ])
        rows.append([
            InlineKeyboardButton(text="🔄 Репост анонсов", callback_data="admin_menu:repost_events"),
            InlineKeyboardButton(text="📢 Мои каналы", callback_data="admin_menu:my_channels"),
        ])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def admin_menu(self, message: types.Message):
        """Show admin panel with inline buttons."""
        user_id = message.from_user.id
        is_super = self._is_super_admin(user_id)

        if not is_super:
            ch = await self._get_admin_channel(user_id)
            if not ch:
                await message.answer("У вас нет доступа к панели администратора.")
                return

        # Обновить Menu Button: админу — расширенный набор команд
        await self._update_user_commands(user_id)

        title = "🎫 <b>Панель управления</b>\n\n"
        if is_super:
            title += "<i>Полный доступ (супер-админ)</i>"
        else:
            title += "<i>Управление вашим каналом</i>"

        kb = self._admin_menu_kb(is_super)
        await message.answer(title, parse_mode="HTML", reply_markup=kb)

    # ═══════════════════════════════════════════════════════
    # СУПЕР-АДМИН КОМАНДЫ
    # ═══════════════════════════════════════════════════════

    async def sa_stats_all(self, message: types.Message):
        """Global statistics: channels, events, tickets, users."""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        async with async_session_factory() as session:
            from sqlalchemy import select, func

            # Users count
            result = await session.execute(select(func.count()).select_from(User))
            users_count = result.scalar() or 0

            # Channels count
            result = await session.execute(select(func.count()).select_from(Channel))
            ch_count = result.scalar() or 0

            # Active subscriptions
            result = await session.execute(
                select(func.count()).select_from(Channel).where(Channel.is_subscription_active == True)
            )
            active_subs = result.scalar() or 0

            # Events count
            result = await session.execute(select(func.count()).select_from(Event))
            events_count = result.scalar() or 0

            # Upcoming events
            result = await session.execute(
                select(func.count()).select_from(Event).where(Event.date >= datetime.now(timezone.utc))
            )
            upcoming = result.scalar() or 0

            # Active tickets
            result = await session.execute(
                select(func.count()).select_from(Ticket).where(Ticket.status == TicketStatus.active)
            )
            tickets_active = result.scalar() or 0

            # Total revenue (from completed payments)
            result = await session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .where(Payment.status == PaymentStatus.completed)
            )
            revenue = float(result.scalar() or 0)

        text = (
            "📊 <b>Общая статистика</b>\n\n"
            f"👥 Пользователей: {users_count}\n"
            f"📢 Каналов: {ch_count} (активных подписок: {active_subs})\n"
            f"🎫 Мероприятий: {events_count} (предстоящих: {upcoming})\n"
            f"🎟 Активных билетов: {tickets_active}\n"
            f"💰 Выручка: {revenue:.0f}₽"
        )
        await message.answer(text, parse_mode="HTML")

    async def sa_list_channels(self, message: types.Message):
        """List all channels with subscription status."""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        async with async_session_factory() as session:
            from sqlalchemy import select, func
            result = await session.execute(select(Channel).order_by(Channel.created_at.desc()))
            channels = list(result.scalars().all())

            # Получить админов для всех каналов одним запросом
            admin_svc = ChannelAdminService(session)
            channel_admins_map = {}
            for ch in channels:
                channel_admins_map[ch.telegram_channel_id] = await admin_svc.get_admin_ids(ch.id)

        if not channels:
            await message.answer("Нет зарегистрированных каналов.")
            return

        lines = ["📋 <b>Все каналы:</b>\n"]
        for ch in channels:
            status = "🟢" if ch.is_subscription_active else "🔴"
            admins = channel_admins_map.get(ch.telegram_channel_id, [])
            if admins:
                admin_display = ", ".join(a[:8] + "..." if len(a) > 8 else a for a in admins)
            else:
                admin_display = "—"
            lines.append(
                f"{status} {ch.title or ch.telegram_channel_id}\n"
                f"   Админы: {admin_display}\n"
                f"   Подписка: {'до ' + ch.subscription_until.strftime('%d.%m.%Y') if ch.subscription_until else 'нет'}\n"
            )

        await message.answer("\n".join(lines), parse_mode="HTML")

    async def sa_channel_info(self, message: types.Message):
        """Show channel details. Usage: /channel_info <channel_id>"""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Укажите ID канала: /channel_info &lt;channel_id&gt;")
            return

        channel_telegram_id = args[1].strip()
        async with async_session_factory() as session:
            channel_svc = ChannelService(session)
            channel = await channel_svc.get_by_telegram_id(channel_telegram_id)

            if not channel:
                await message.answer(f"❌ Канал {channel_telegram_id} не найден.")
                return

            # Events count for this channel
            result = await session.execute(
                select(func.count()).select_from(Event).where(Event.channel_id == channel.id)
            )
            events_count = result.scalar() or 0

            result = await session.execute(
                select(func.count()).select_from(Event)
                .where(Event.channel_id == channel.id, Event.date >= datetime.now(timezone.utc))
            )
            upcoming = result.scalar() or 0

            # Tickets sold for this channel's events
            result = await session.execute(
                select(func.count()).select_from(Ticket)
                .join(Event, Ticket.event_id == Event.id)
                .where(Event.channel_id == channel.id, Ticket.status == TicketStatus.active)
            )
            tickets_sold = result.scalar() or 0

            # Получить всех админов канала
            admin_svc = ChannelAdminService(session)
            admins = await admin_svc.get_admin_ids(channel.id)

        sub_status = "🟢 Активна" if channel.is_subscription_active else "🔴 Неактивна"
        sub_until = f" до {channel.subscription_until.strftime('%d.%m.%Y')}" if channel.subscription_until else ""
        admins_display = ", ".join(f"<code>{a}</code>" for a in admins) if admins else "—"
        text = (
            f"ℹ️ <b>Канал: {channel.title or channel.telegram_channel_id}</b>\n\n"
            f"🆔 {channel.telegram_channel_id}\n"
            f"👥 Админы: {admins_display}\n"
            f"📊 {sub_status}{sub_until}\n"
            f"🎫 Мероприятий: {events_count} (предстоящих: {upcoming})\n"
            f"🎟 Продано билетов: {tickets_sold}"
        )
        await message.answer(text, parse_mode="HTML")

    async def sa_user_info(self, message: types.Message):
        """Show user info. Usage: /user_info <telegram_user_id>"""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Укажите Telegram ID: /user_info &lt;user_id&gt;")
            return

        user_tg_id = args[1].strip()
        async with async_session_factory() as session:
            from sqlalchemy import select, func
            user_svc = UserService(session)
            try:
                user = await user_svc.get_or_create(PlatformType.telegram, user_tg_id)
            except Exception:
                user = None

            channel_svc = ChannelService(session)
            channels = await channel_svc.get_channels_by_admin(user_tg_id)

            text = f"👤 <b>Пользователь: {user_tg_id}</b>\n\n"
            if user:
                text += f"Имя: {user.name or '—'}\n"
                text += f"Внутренний ID: <code>{user.id}</code>\n"

            if channels:
                text += f"\n📢 <b>Каналы ({len(channels)}):</b>\n"
                for ch in channels:
                    status = "🟢" if ch.is_subscription_active else "🔴"
                    text += f"{status} {ch.title or ch.telegram_channel_id}\n"
            else:
                text += "\n📢 Нет зарегистрированных каналов."

        await message.answer(text, parse_mode="HTML")

    async def sa_admin_cancel(self, message: types.Message):
        """Admin cancel any ticket. Usage: /admin_cancel <ticket_id>"""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Укажите ID билета: /admin_cancel &lt;ticket_id&gt;")
            return

        try:
            ticket_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID билета.")
            return

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                ticket = await ticket_svc.admin_cancel_ticket(ticket_id)
                await session.commit()
                await message.answer(f"✅ Билет <code>{ticket_id}</code> возвращён.", parse_mode="HTML")
            except ValueError as e:
                await message.answer(f"❌ {e}")

    async def sa_broadcast(self, message: types.Message, state: FSMContext):
        """Broadcast a message to all bot users via their DMs."""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        await state.set_state(BroadcastFSM.text)
        await message.answer(
            "📢 <b>Рассылка</b>\n\n"
            "Отправьте сообщение, которое будет разослано во все каналы.\n"
            "Или отправьте /cancel для отмены.",
            parse_mode="HTML",
        )

    async def _handle_broadcast_input(self, message: types.Message, state: FSMContext):
        """Handle broadcast text input."""
        text = message.text
        if text.strip().lower() == "/cancel":
            await state.clear()
            await message.answer("❌ Рассылка отменена.")
            return

        if not text.strip():
            await message.answer("❌ Сообщение не может быть пустым.")
            return

        await state.clear()

        # Send to all channels
        async with async_session_factory() as session:
            from sqlalchemy import select
            result = await session.execute(select(Channel).where(Channel.is_subscription_active == True))
            channels = list(result.scalars().all())

        if not channels:
            await message.answer("Нет активных каналов для рассылки.")
            return

        sent = 0
        for ch in channels:
            try:
                await self.bot.send_message(
                    chat_id=ch.telegram_channel_id,
                    text=f"📢 <b>Сообщение администрации</b>\n\n{text}",
                    parse_mode="HTML",
                )
                sent += 1
            except Exception as e:
                logger.error("Ошибка рассылки в %s: %s", ch.telegram_channel_id, e)

        await message.answer(f"✅ Сообщение отправлено в {sent}/{len(channels)} каналов.")

    async def _handle_admin_input(self, message: types.Message, state: FSMContext):
        """Handle text input for admin menu buttons that need a parameter."""
        data = await state.get_data()
        action = data.get("admin_action")

        if not action:
            await state.clear()
            await message.answer("❌ Действие не найдено. Используйте /admin для входа в меню.")
            return

        # Cancel
        if message.text.strip().lower() == "/cancel":
            await state.clear()
            await message.answer("❌ Действие отменено.")
            return

        user_input = message.text.strip()

        if action == "channel_info":
            if not self._is_super_admin(message.from_user.id):
                await message.answer("У вас нет доступа.")
                await state.clear()
                return
            async with async_session_factory() as session:
                channel_svc = ChannelService(session)
                channel = await channel_svc.get_by_telegram_id(user_input)
                if not channel:
                    await message.answer(f"❌ Канал {user_input} не найден.")
                    await state.clear()
                    return
                events_count = (await session.execute(
                    select(func.count()).select_from(Event).where(Event.channel_id == channel.id)
                )).scalar() or 0
                upcoming = (await session.execute(
                    select(func.count()).select_from(Event)
                    .where(Event.channel_id == channel.id, Event.date >= datetime.now(timezone.utc))
                )).scalar() or 0
                tickets_sold = (await session.execute(
                    select(func.count()).select_from(Ticket)
                    .join(Event, Ticket.event_id == Event.id)
                    .where(Event.channel_id == channel.id, Ticket.status == TicketStatus.active)
                )).scalar() or 0
                admin_svc = ChannelAdminService(session)
                admins = await admin_svc.get_admin_ids(channel.id)
            sub_status = "🟢 Активна" if channel.is_subscription_active else "🔴 Неактивна"
            sub_until = f" до {channel.subscription_until.strftime('%d.%m.%Y')}" if channel.subscription_until else ""
            admins_display = ", ".join(f"<code>{a}</code>" for a in admins) if admins else "—"
            text = (
                f"ℹ️ <b>Канал: {channel.title or channel.telegram_channel_id}</b>\n\n"
                f"🆔 {channel.telegram_channel_id}\n"
                f"👥 Админы: {admins_display}\n"
                f"📊 {sub_status}{sub_until}\n"
                f"🎫 Мероприятий: {events_count} (предстоящих: {upcoming})\n"
                f"🎟 Продано билетов: {tickets_sold}"
            )
            await message.answer(text, parse_mode="HTML")
            await state.clear()
            return

        if action == "user_info":
            if not self._is_super_admin(message.from_user.id):
                await message.answer("У вас нет доступа.")
                await state.clear()
                return
            async with async_session_factory() as session:
                user_svc = UserService(session)
                try:
                    user = await user_svc.get_or_create(PlatformType.telegram, user_input)
                except Exception:
                    user = None
                channel_svc = ChannelService(session)
                channels = await channel_svc.get_channels_by_admin(user_input)
                text = f"👤 <b>Пользователь: {user_input}</b>\n\n"
                if user:
                    text += f"Имя: {user.name or '—'}\n"
                    text += f"Внутренний ID: <code>{user.id}</code>\n"
                if channels:
                    text += f"\n📢 <b>Каналы ({len(channels)}):</b>\n"
                    for ch in channels:
                        status = "🟢" if ch.is_subscription_active else "🔴"
                        text += f"{status} {ch.title or ch.telegram_channel_id}\n"
                else:
                    text += "\n📢 Нет зарегистрированных каналов."
            await message.answer(text, parse_mode="HTML")
            await state.clear()
            return

        if action == "subscribe":
            if not self._is_super_admin(message.from_user.id):
                await message.answer("У вас нет доступа.")
                await state.clear()
                return
            parts = user_input.split()
            if len(parts) < 2:
                await message.answer("❌ Укажите @username канала и количество дней через пробел.\nПример: <code>@my_channel 30</code>", parse_mode="HTML")
                return
            try:
                channel_telegram_id = parts[0].strip()
                days = int(parts[1].strip())
                if days <= 0:
                    raise ValueError
            except ValueError:
                await message.answer("❌ Укажите ID канала и количество дней (число > 0).")
                return
            async with async_session_factory() as session:
                try:
                    channel_svc = ChannelService(session)
                    channel = await channel_svc.get_by_telegram_id(channel_telegram_id)
                    if channel:
                        channel = await channel_svc.activate_subscription(channel.id, days)
                        channel_name = channel.title or channel.telegram_channel_id

                        # Синхронизировать админов канала, если бот в нём
                        admin_svc = ChannelAdminService(session)
                        try:
                            admins = await self.bot.get_chat_administrators(chat_id=channel.telegram_channel_id)
                            admin_ids = [
                                str(a.user.id) for a in admins
                                if a.status in ("creator", "administrator") and not a.user.is_bot
                            ]
                            if admin_ids:
                                await admin_svc.sync_admins(channel.id, admin_ids)
                                channel.admin_telegram_user_id = admin_ids[0]
                        except Exception as e:
                            logger.info(
                                "Не удалось синхронизировать админов для %s: %s",
                                channel.telegram_channel_id, e,
                            )

                        await session.commit()
                        text = (
                            f"✅ Подписка активирована для канала {channel_name}!\n"
                            f"Срок: {days} дней (до {channel.subscription_until.strftime('%d.%m.%Y')})"
                        )
                    else:
                        channel = await channel_svc.create(
                            telegram_channel_id=channel_telegram_id,
                            admin_telegram_user_id="",
                            title=f"Канал {channel_telegram_id}",
                        )
                        channel = await channel_svc.activate_subscription(channel.id, days)
                        await session.commit()
                        text = (
                            f"✅ Подписка активирована для канала {channel_telegram_id}!\n"
                            f"Срок: {days} дней.\n"
                            f"ℹ️ Владелец канала должен добавить бота в канал для начала работы."
                        )
                    await message.answer(text, parse_mode="HTML")
                except Exception as e:
                    await session.rollback()
                    await message.answer(f"❌ Ошибка: {e}")
            await state.clear()
            return

        if action == "unsubscribe":
            if not self._is_super_admin(message.from_user.id):
                await message.answer("У вас нет доступа.")
                await state.clear()
                return
            async with async_session_factory() as session:
                try:
                    channel_svc = ChannelService(session)
                    channel = await channel_svc.get_by_telegram_id(user_input)
                    if channel is None:
                        await message.answer(f"❌ Канал {user_input} не найден.")
                        await state.clear()
                        return
                    await channel_svc.deactivate_subscription(channel.id)
                    await session.commit()
                    channel_name = channel.title or channel.telegram_channel_id
                    await message.answer(
                        f"✅ Подписка отключена для канала {channel_name}.\n"
                        f"Бот останется в канале, но новые мероприятия создавать нельзя."
                    )
                except Exception as e:
                    await session.rollback()
                    await message.answer(f"❌ Ошибка: {e}")
            await state.clear()
            return

        if action == "change_admin":
            if not self._is_super_admin(message.from_user.id):
                await message.answer("У вас нет доступа.")
                await state.clear()
                return
            parts = user_input.split()
            if len(parts) < 2:
                await message.answer("❌ Укажите @username канала и новый Telegram ID через пробел.\nПример: <code>@my_channel 123456789</code>", parse_mode="HTML")
                return
            channel_telegram_id = parts[0].strip()
            new_admin_id = parts[1].strip()
            async with async_session_factory() as session:
                channel_svc = ChannelService(session)
                admin_svc = ChannelAdminService(session)
                channel = await channel_svc.get_by_telegram_id(channel_telegram_id)
                if not channel:
                    await message.answer(f"❌ Канал {channel_telegram_id} не найден.")
                    await state.clear()
                    return
                old_admins = await admin_svc.get_admin_ids(channel.id)
                await admin_svc.sync_admins(channel.id, [new_admin_id])
                channel.admin_telegram_user_id = new_admin_id
                await session.commit()
                old_display = ", ".join(old_admins) if old_admins else "—"
                await message.answer(
                    f"✅ Админы канала {channel.title or channel.telegram_channel_id} заменены:\n"
                    f"{old_display} → {new_admin_id}"
                )
            await state.clear()
            return

        if action == "admin_cancel":
            if not self._is_super_admin(message.from_user.id):
                await message.answer("У вас нет доступа.")
                await state.clear()
                return
            try:
                ticket_id = UUID(user_input)
            except ValueError:
                await message.answer("❌ Неверный ID билета. Введите UUID билета.")
                return
            async with async_session_factory() as session:
                ticket_svc = TicketService(session)
                try:
                    ticket = await ticket_svc.admin_cancel_ticket(ticket_id)
                    await session.commit()
                    await message.answer(f"✅ Билет <code>{ticket_id}</code> возвращён.", parse_mode="HTML")
                except ValueError as e:
                    await message.answer(f"❌ {e}")
            await state.clear()
            return

        await message.answer("❌ Неизвестное действие.")
        await state.clear()

    async def sa_health(self, message: types.Message):
        """Check bot health status."""
        """Check bot health status."""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        text = (
            "🩺 <b>Здоровье бота</b>\n\n"
            "🤖 Статус: ✅ Работает\n"
            f"👤 Username: @{self._bot_username or 'неизвестно'}\n\n"
        )
        try:
            async with async_session_factory() as session:
                from sqlalchemy import text as sqltext
                await session.execute(sqltext("SELECT 1"))
                text += "🗄 База данных: ✅ Подключена\n"
        except Exception as e:
            text += f"🗄 База данных: ❌ Ошибка: {e}\n"

        text += "\nДоступные команды: /admin"

        await message.answer(text, parse_mode="HTML")

    async def sa_check_expired(self, message: types.Message):
        """Check and deactivate expired subscriptions."""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        async with async_session_factory() as session:
            channel_svc = ChannelService(session)
            from sqlalchemy import select
            result = await session.execute(
                select(Channel).where(Channel.is_subscription_active == True)
            )
            channels = list(result.scalars().all())

            deactivated = 0
            for ch in channels:
                if not await channel_svc.is_subscription_valid(ch.id):
                    deactivated += 1

            await session.commit()

        await message.answer(
            f"🔍 Проверка завершена.\n"
            f"📢 Всего каналов: {len(channels)}\n"
            f"🔄 Отключено просроченных: {deactivated}",
        )

    async def sa_change_admin(self, message: types.Message):
        """Change channel admin. Usage: /change_admin <channel_id> <new_user_id>"""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа.")
            return

        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer("Использование: /change_admin &lt;channel_id&gt; &lt;new_user_id&gt;")
            return

        channel_telegram_id = args[1].strip()
        new_admin_id = args[2].strip()

        async with async_session_factory() as session:
            channel_svc = ChannelService(session)
            admin_svc = ChannelAdminService(session)
            channel = await channel_svc.get_by_telegram_id(channel_telegram_id)
            if not channel:
                await message.answer(f"❌ Канал {channel_telegram_id} не найден.")
                return

            old_admins = await admin_svc.get_admin_ids(channel.id)
            await admin_svc.sync_admins(channel.id, [new_admin_id])
            channel.admin_telegram_user_id = new_admin_id
            await session.commit()

            old_display = ", ".join(old_admins) if old_admins else "—"
            await message.answer(
                f"✅ Админы канала {channel.title or channel.telegram_channel_id} заменены:\n"
                f"{old_display} → {new_admin_id}"
            )

    # ─── FSM: Создание мероприятия ──────────────────────────────────────

    def _fsm_cancel_kb(self, extra_buttons: list[list[InlineKeyboardButton]] | None = None) -> InlineKeyboardMarkup:
        """Клавиатура с кнопкой отмены для FSM-шагов."""
        rows = list(extra_buttons) if extra_buttons else []
        rows.append([InlineKeyboardButton(text="❌ Отмена создания", callback_data="admin:cancel_create")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _fsm_header(self, data: dict) -> str:
        """Сформировать блок с уже введёнными данными для шапки FSM."""
        lines = []
        if "title" in data:
            lines.append(f"📌 Название: {data['title']}")
        if "description" in data and data["description"]:
            desc = data["description"][:50] + "…" if len(data["description"]) > 50 else data["description"]
            lines.append(f"📖 Описание: {desc}")
        if "date" in data:
            d = datetime.fromisoformat(data["date"])
            lines.append(f"📅 Дата: {d.strftime('%d.%m.%Y %H:%M')}")
        if "location" in data and data["location"]:
            lines.append(f"📍 Место: {data['location']}")
        if "price" in data:
            lines.append(f"💰 Цена: {data['price']:.0f}₽")
        if "tickets" in data:
            lines.append(f"🎟 Билетов: {data['tickets']}")
        return "\n".join(lines) + "\n\n" if lines else ""

    async def admin_create_event(self, message: types.Message, state: FSMContext):
        """Start the create-event wizard."""
        # Get admin's channel (проверяет права через Telegram API внутри)
        channel = await self._get_admin_channel(message.from_user.id)
        if not channel:
            await message.answer("❌ У вас нет канала с активной подпиской.\n\nОбратитесь к администратору для оформления подписки.")
            return

        # Store channel_id in FSM data
        await state.update_data(channel_id=channel.id)
        await state.set_state(CreateEvent.title)
        kb = self._fsm_cancel_kb()
        await message.answer(
            "📝 <b>Создание мероприятия</b> (шаг 1/6)\n\n"
            "Введите <b>название</b> мероприятия.",
            parse_mode="HTML",
            reply_markup=kb,
        )

    async def fsm_cancel(self, message: types.Message, state: FSMContext):
        """Cancel the FSM at any step."""
        await state.clear()
        await message.answer("❌ Создание мероприятия отменено.")

    async def fsm_title(self, message: types.Message, state: FSMContext):
        data = await state.update_data(title=message.text.strip())
        await state.set_state(CreateEvent.description)
        header = await self._fsm_header(data)
        kb = self._fsm_cancel_kb([
            [InlineKeyboardButton(text="➡️ Пропустить", callback_data="fsm_skip:description")],
        ])
        await message.answer(
            f"{header}📝 Введите <b>описание</b> мероприятия\n"
            "или нажмите «Пропустить».",
            parse_mode="HTML",
            reply_markup=kb,
        )

    async def fsm_description(self, message: types.Message, state: FSMContext):
        data = await state.get_data()
        header = await self._fsm_header(data)
        await state.set_state(CreateEvent.date)
        kb = self._fsm_cancel_kb()
        await message.answer(
            f"{header}📅 Введите <b>дату и время</b> в формате:\n"
            "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Пример: <code>25.12.2026 19:00</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )

    async def fsm_date(self, message: types.Message, state: FSMContext):
        text = message.text.strip()
        try:
            date = datetime.strptime(text, "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            data = await state.get_data()
            header = await self._fsm_header(data)
            kb = self._fsm_cancel_kb()
            await message.answer(
                f"{header}❌ Неверный формат. Используйте <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
                "Пример: <code>25.12.2026 19:00</code>",
                parse_mode="HTML",
                reply_markup=kb,
            )
            return
        await state.update_data(date=date.isoformat())
        await state.set_state(CreateEvent.location)
        data = await state.get_data()
        header = await self._fsm_header(data)
        kb = self._fsm_cancel_kb([
            [InlineKeyboardButton(text="➡️ Пропустить", callback_data="fsm_skip:location")],
        ])
        await message.answer(
            f"{header}📍 Введите <b>адрес или место</b> проведения.\n\n"
            "Например: <code>Москва, ул. Тверская, д. 1</code>\n"
            "Или <code>Онлайн</code> для вебинара.\n"
            "или нажмите «Пропустить».",
            parse_mode="HTML",
            reply_markup=kb,
        )

    async def fsm_location(self, message: types.Message, state: FSMContext):
        await state.update_data(location=message.text.strip())
        data = await state.get_data()
        header = await self._fsm_header(data)
        await state.set_state(CreateEvent.price)
        kb = self._fsm_cancel_kb()
        await message.answer(
            f"{header}💰 Введите <b>цену билета</b> в рублях.\n\n"
            "Например: <code>1500</code> или <code>0</code> для бесплатного.",
            parse_mode="HTML",
            reply_markup=kb,
        )

    async def fsm_price(self, message: types.Message, state: FSMContext):
        text = message.text.strip().replace(",", ".")
        try:
            price = float(text)
            if price < 0:
                raise ValueError
        except ValueError:
            data = await state.get_data()
            header = await self._fsm_header(data)
            kb = self._fsm_cancel_kb()
            await message.answer(
                f"{header}❌ Введите число. Например: <code>1500</code> или <code>0</code>.\n"
                "Допускается запятая: <code>1500,50</code>",
                parse_mode="HTML",
                reply_markup=kb,
            )
            return
        await state.update_data(price=price)
        data = await state.get_data()
        header = await self._fsm_header(data)
        await state.set_state(CreateEvent.tickets)
        kb = self._fsm_cancel_kb()
        await message.answer(
            f"{header}🎟 Введите <b>количество билетов</b> (целое число).\n"
            "Например: <code>100</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )

    async def fsm_tickets(self, message: types.Message, state: FSMContext):
        text = message.text.strip()
        try:
            tickets = int(text)
            if tickets <= 0:
                raise ValueError
        except ValueError:
            data = await state.get_data()
            header = await self._fsm_header(data)
            kb = self._fsm_cancel_kb()
            await message.answer(
                f"{header}❌ Введите целое число больше 0.\n"
                "Например: <code>100</code>",
                parse_mode="HTML",
                reply_markup=kb,
            )
            return
        data = await state.update_data(tickets=tickets)
        await state.set_state(CreateEvent.confirm)

        # Показать сводку
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
            f"✅ <b>Подтвердите создание</b> или нажмите «Отмена»."
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

    # ─── /events_all ─────────────────────────────────────────────────────

    async def admin_events_all(self, message: types.Message):
        """Show ALL events for the admin's channel."""
        channel = await self._get_admin_channel(message.from_user.id)
        if not channel:
            await message.answer("❌ У вас нет канала с активной подпиской.\n\nОбратитесь к администратору для оформления подписки.")
            return

        async with async_session_factory() as session:
            svc = EventService(session)
            events = await svc.list_all(channel_id=channel.id)

        if not events:
            await message.answer("Нет мероприятий.")
            return

        lines = ["🎫 <b>Все мероприятия:</b>\n"]
        kb_rows = []
        for e in events:
            event_status = "🟢" if e.is_active else "🔴"
            date_str = e.date.strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"{event_status} <b>{e.title}</b>\n"
                f"📅 {date_str}\n"
                f"🎟 {e.available_tickets}/{e.total_tickets}\n"
            )
            # Первая строка: название мероприятия (до 40 символов)
            title_btn = e.title[:40]
            kb_rows.append([
                InlineKeyboardButton(text=f"🎫 {title_btn}", callback_data=f"ch_admin:menu:{e.id}"),
            ])
            # Вторая строка: кнопки управления
            toggle_label = "▶ Включить" if not e.is_active else "⏸ Отключить"
            kb_rows.append([
                InlineKeyboardButton(text="📊 Статистика", callback_data=f"ch_admin:stats:{e.id}"),
                InlineKeyboardButton(text=toggle_label, callback_data=f"ch_admin:toggle:{e.id}"),
            ])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None
        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)

    # ─── /deactivate /activate ───────────────────────────────────────────

    async def _toggle_active(self, message: types.Message, activate: bool):
        """Toggle event active state."""
        channel = await self._get_admin_channel(message.from_user.id)
        if not channel:
            await message.answer("❌ У вас нет канала с активной подпиской.\n\nОбратитесь к администратору для оформления подписки.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Мои мероприятия", callback_data="admin_menu:events_all")],
            ])
            await message.answer(
                "⏸ Выберите мероприятие для изменения статуса:",
                reply_markup=kb,
            )
            return
        try:
            event_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        async with async_session_factory() as session:
            svc = EventService(session)
            # Verify event belongs to admin's channel
            event = await svc.get_by_id(event_id, channel_id=channel.id)
            if event is None:
                await message.answer("Мероприятие не найдено в вашем канале.")
                return
            event = await svc.set_active(event_id, activate)
            await session.commit()

        verb = "включено" if activate else "отключено"
        await message.answer(f"✅ Мероприятие «{event.title}» {verb}.")

    async def admin_deactivate(self, message: types.Message):
        await self._toggle_active(message, activate=False)

    async def admin_activate(self, message: types.Message):
        await self._toggle_active(message, activate=True)

    # ─── /stats ──────────────────────────────────────────────────────────

    async def admin_stats(self, message: types.Message):
        """Show event sales stats."""
        channel = await self._get_admin_channel(message.from_user.id)
        if not channel:
            await message.answer("❌ У вас нет канала с активной подпиской.\n\nОбратитесь к администратору для оформления подписки.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Мои мероприятия", callback_data="admin_menu:events_all")],
            ])
            await message.answer(
                "📊 Выберите мероприятие для просмотра статистики:",
                reply_markup=kb,
            )
            return
        try:
            event_id = UUID(args[1])
        except ValueError:
            await message.answer("Неверный ID мероприятия.")
            return

        async with async_session_factory() as session:
            svc = EventService(session)
            try:
                event = await svc.get_by_id(event_id, channel_id=channel.id)
                if event is None:
                    await message.answer("Мероприятие не найдено в вашем канале.")
                    return
                stats = await svc.get_event_stats(event_id)
            except ValueError as e:
                await message.answer(f"❌ {e}")
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

    # ─── /repost_events ──────────────────────────────────────────────────

    async def admin_repost_events(self, message: types.Message):
        """Repost all active event announcements to the admin's channel."""
        channel = await self._get_admin_channel(message.from_user.id)
        if not channel:
            await message.answer("❌ У вас нет канала с активной подпиской.\n\nОбратитесь к администратору для оформления подписки.")
            return

        async with async_session_factory() as session:
            svc = EventService(session)
            events = await svc.list_upcoming(channel_id=channel.id)

        if not events:
            await message.answer("Нет активных мероприятий для анонса.")
            return

        posted = 0
        for event in events:
            try:
                await self.channel.post_event_announcement(event, channel.telegram_channel_id)
                posted += 1
            except Exception as e:
                logger.error("Ошибка репоста %s: %s", event.id, e)

        await message.answer(
            f"✅ Анонсы перепощены в канал: {posted}/{len(events)}",
            parse_mode="HTML",
        )

    # ─── /subscribe (super-admin only) ────────────────────────────────────

    async def admin_subscribe(self, message: types.Message):
        """Activate a subscription for a channel. Usage: /subscribe <channel_id> <days>"""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return

        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer(
                "Использование: /subscribe &lt;channel_id&gt; &lt;days&gt;\n\n"
                "channel_id — @username канала или его числовой ID\n"
                "Пример: /subscribe @my_channel 30"
            )
            return

        try:
            channel_telegram_id = args[1].strip()
            days = int(args[2].strip())
            if days <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Укажите ID канала и количество дней (число > 0).")
            return

        async with async_session_factory() as session:
            try:
                channel_svc = ChannelService(session)
                channel = await channel_svc.get_by_telegram_id(channel_telegram_id)

                if channel:
                    # Update existing channel's subscription
                    channel = await channel_svc.activate_subscription(channel.id, days)
                    channel_name = channel.title or channel.telegram_channel_id

                    # Синхронизировать админов канала, если бот в нём
                    admin_svc = ChannelAdminService(session)
                    try:
                        admins = await self.bot.get_chat_administrators(chat_id=channel.telegram_channel_id)
                        admin_ids = [
                            str(a.user.id) for a in admins
                            if a.status in ("creator", "administrator") and not a.user.is_bot
                        ]
                        if admin_ids:
                            await admin_svc.sync_admins(channel.id, admin_ids)
                            channel.admin_telegram_user_id = admin_ids[0]
                    except Exception as e:
                        logger.info(
                            "Не удалось синхронизировать админов для %s: %s (бот может быть не в канале)",
                            channel.telegram_channel_id, e,
                        )

                    await session.commit()
                    text = (
                        f"✅ Подписка активирована для канала {channel_name}!\n"
                        f"Срок: {days} дней (до {channel.subscription_until.strftime('%d.%m.%Y')})"
                    )
                else:
                    # Create a new channel record with subscription
                    channel = await channel_svc.create(
                        telegram_channel_id=channel_telegram_id,
                        admin_telegram_user_id="",
                        title=f"Канал {channel_telegram_id}",
                    )
                    channel = await channel_svc.activate_subscription(channel.id, days)
                    await session.commit()
                    text = (
                        f"✅ Подписка активирована для канала {channel_telegram_id}!\n"
                        f"Срок: {days} дней.\n"
                        f"ℹ️ Владелец канала должен добавить бота в канал для начала работы.\n"
                        f"   После добавления бот привяжет канал к пользователю."
                    )

                await message.answer(text, parse_mode="HTML")

            except Exception as e:
                await session.rollback()
                await message.answer(f"❌ Ошибка: {e}")

    # ─── /unsubscribe (super-admin only) ──────────────────────────────────

    async def admin_unsubscribe(self, message: types.Message):
        """Deactivate a subscription for a channel. Usage: /unsubscribe <channel_id>"""
        if not self._is_super_admin(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "Использование: /unsubscribe &lt;channel_id&gt;\n\n"
                "channel_id — @username канала или его числовой ID\n"
                "Пример: /unsubscribe @my_channel"
            )
            return

        channel_telegram_id = args[1].strip()

        async with async_session_factory() as session:
            try:
                channel_svc = ChannelService(session)
                channel = await channel_svc.get_by_telegram_id(channel_telegram_id)

                if channel is None:
                    await message.answer(f"❌ Канал {channel_telegram_id} не найден.")
                    return

                await channel_svc.deactivate_subscription(channel.id)
                await session.commit()

                channel_name = channel.title or channel.telegram_channel_id
                await message.answer(
                    f"✅ Подписка отключена для канала {channel_name}.\n"
                    f"Бот останется в канале, но новые мероприятия создавать нельзя."
                )

            except Exception as e:
                await session.rollback()
                await message.answer(f"❌ Ошибка: {e}")

    # ─── /my_channels ─────────────────────────────────────────────────────

    async def admin_my_channels(self, message: types.Message):
        """Show the admin's channels and subscription status."""
        if not await self._has_admin_access(message.from_user.id):
            await message.answer("У вас нет доступа к панели администратора.")
            return

        async with async_session_factory() as session:
            channel_svc = ChannelService(session)
            channels = await channel_svc.get_channels_by_admin(str(message.from_user.id))

        if not channels:
            await message.answer("У вас нет зарегистрированных каналов.")
            return

        lines = ["📢 <b>Ваши каналы:</b>\n"]
        for ch in channels:
            status = "🟢 Активна" if ch.is_subscription_active else "🔴 Неактивна"
            until = ""
            if ch.subscription_until:
                until = f" до {ch.subscription_until.strftime('%d.%m.%Y')}"
            lines.append(
                f"📌 {ch.title or ch.telegram_channel_id}\n"
                f"   {status}{until}\n"
            )

        await message.answer("\n".join(lines), parse_mode="HTML")

    # ═══════════════════════════════════════════════════════
    # ХЕНДЛЕРЫ СОБЫТИЙ КАНАЛА
    # ═══════════════════════════════════════════════════════

    async def on_chat_member_update(self, chat_member: types.ChatMemberUpdated):
        """Detect when bot is added to or removed from a channel."""
        # We only care about channels
        if chat_member.chat.type != "channel":
            return

        chat = chat_member.chat
        adder_id = str(chat_member.from_user.id)

        # Bot was added to a channel (в каналах бот всегда администратор)
        if chat_member.new_chat_member.status in ("member", "administrator"):
            logger.info("Бот добавлен в канал %s пользователем %s", chat.id, adder_id)

            # Получить список всех админов канала через Telegram API
            admin_ids: list[str] = []
            try:
                admins = await self.bot.get_chat_administrators(chat_id=chat.id)
                admin_ids = [
                    str(admin.user.id) for admin in admins
                    if admin.status in ("creator", "administrator") and not admin.user.is_bot
                ]
                logger.info(
                    "Канал %s: найдено %d администраторов",
                    chat.id, len(admin_ids),
                )
            except Exception as e:
                logger.error("Не удалось получить админов канала %s: %s", chat.id, e)

            async with async_session_factory() as session:
                channel_svc = ChannelService(session)
                admin_svc = ChannelAdminService(session)
                channel = await channel_svc.get_by_telegram_id(str(chat.id))

                # Если не нашли по числовому ID — ищем по @username
                if not channel and chat.username:
                    channel = await channel_svc.get_by_telegram_id(f"@{chat.username}")
                    if channel:
                        logger.info(
                            "Канал %s найден по @username, telegram_channel_id: %s → %s",
                            chat.username, channel.telegram_channel_id, chat.id,
                        )

                if channel:
                    # Обновляем telegram_channel_id если он: pending_*, __legacy__, @username или голое число без -100
                    if (
                        channel.telegram_channel_id.startswith("pending_")
                        or channel.telegram_channel_id == "__legacy__"
                        or channel.telegram_channel_id.startswith("@")
                        or channel.telegram_channel_id.lstrip("-").isdigit()
                    ):
                        channel.telegram_channel_id = str(chat.id)
                    channel.title = chat.title

                    # Синхронизировать всех админов канала из Telegram
                    if admin_ids:
                        await admin_svc.sync_admins(channel.id, admin_ids)
                        # Legacy fallback: сохранить первого админа
                        channel.admin_telegram_user_id = admin_ids[0]
                    elif not channel.admin_telegram_user_id or channel.admin_telegram_user_id in ("", "0"):
                        # Если API не вернул админов — хотя бы записать кто добавил
                        channel.admin_telegram_user_id = adder_id
                        await admin_svc.sync_admins(channel.id, [adder_id])

                    await session.commit()

                    # Обновить Menu Button для всех админов
                    for aid in admin_ids or [adder_id]:
                        try:
                            await self._update_user_commands(int(aid))
                        except Exception:
                            logger.warning("Не удалось обновить команды для %s", aid)

                    # Subscription status determines the welcome message
                    if await channel_svc.is_subscription_valid(channel.id):
                        await self.bot.send_message(
                            chat_id=chat.id,
                            text=(
                                "✅ <b>Подписка активна!</b>\n\n"
                                "Бот готов к работе. Используйте /create_event "
                                "в личных сообщениях с ботом для создания мероприятий."
                            ),
                            parse_mode="HTML",
                        )
                    else:
                        await self.bot.send_message(
                            chat_id=chat.id,
                            text=(
                                "❌ <b>Подписка неактивна.</b>\n\n"
                                "Обратитесь к администратору для оплаты подписки."
                            ),
                            parse_mode="HTML",
                        )
                else:
                    # First time — create channel record
                    channel = await channel_svc.create(
                        telegram_channel_id=str(chat.id),
                        admin_telegram_user_id=adder_id,
                        title=chat.title,
                    )
                    # Добавить всех найденных админов (или хотя бы того, кто добавил)
                    await admin_svc.sync_admins(channel.id, admin_ids or [adder_id])
                    await session.commit()

                    # Notify the adder in DM
                    try:
                        await self.bot.send_message(
                            chat_id=chat_member.from_user.id,
                            text=(
                                f"📢 Спасибо, что добавили бота в канал «{chat.title}»!\n\n"
                                "Для активации подписки обратитесь к администратору.\n"
                                "После активации вы сможете управлять мероприятиями "
                                "через команды в личных сообщениях с ботом."
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        logger.warning("Не удалось уведомить %s о добавлении в канал", adder_id)

        # Bot was removed from a channel
        elif chat_member.new_chat_member.status in ("left", "kicked"):
            logger.info("Бот удалён из канала %s", chat.id)

    # ─── Callback-запросы (инлайн-кнопки) ────────────────────────────────

    async def cmd_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Handle all callback queries."""
        data = callback.data

        # ─── Канал: покупка билета (из анонса) ──────────
        if data.startswith("channel_buy:"):
            event_id = UUID(data.split(":", 1)[1])
            await self._handle_channel_buy(callback, event_id)
            return

        # ─── Канал: мои билеты ─────────────────────────
        if data == "channel_my_tickets":
            await self._handle_channel_my_tickets(callback)
            return

        # ─── Канал: все мероприятия ────────────────────
        if data == "channel_events":
            await self._handle_channel_events(callback)
            return

        # ─── Канал: управление мероприятием (админ) ─────
        if data.startswith("ch_admin:"):
            await self._handle_channel_admin(callback, data)
            return

        # ─── FSM: пропустить шаг (описание/место) ──────────
        if data.startswith("fsm_skip:"):
            field = data.split(":", 1)[1]
            current_state = await state.get_state()
            expected_state = getattr(CreateEvent, field, None)
            if expected_state and current_state == expected_state.state:
                data_dict = await state.get_data()
                # Поле уже могло быть заполнено текстом — не перезаписываем
                if field not in data_dict or not data_dict.get(field):
                    await state.update_data(**{field: None})
                if field == "description":
                    await state.set_state(CreateEvent.date)
                    data_dict = await state.get_data()
                    header = await self._fsm_header(data_dict)
                    kb = self._fsm_cancel_kb()
                    await callback.message.edit_text(
                        f"{header}📅 Введите <b>дату и время</b> в формате:\n"
                        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
                        "Пример: <code>25.12.2026 19:00</code>",
                        parse_mode="HTML",
                        reply_markup=kb,
                    )
                elif field == "location":
                    await state.set_state(CreateEvent.price)
                    data_dict = await state.get_data()
                    header = await self._fsm_header(data_dict)
                    kb = self._fsm_cancel_kb()
                    await callback.message.edit_text(
                        f"{header}💰 Введите <b>цену билета</b> в рублях.\n\n"
                        "Например: <code>1500</code> или <code>0</code> для бесплатного.",
                        parse_mode="HTML",
                    )
            await callback.answer()
            return

        # ─── Админ: подтвердить создание ────────────────
        if data == "admin:confirm_create":
            # Сначала подтверждаем callback, чтобы пользователь
            # сразу увидел обратную связь
            await callback.answer()

            fsm_data = await state.get_data()
            # Проверяем, что state не потерян (например, после рестарта бота)
            if not fsm_data or "date" not in fsm_data:
                await callback.message.edit_text(
                    "❌ Сессия создания мероприятия истекла. Начните заново: /create_event"
                )
                await state.clear()
                return

            event_date = datetime.fromisoformat(fsm_data["date"])

            try:
                async with async_session_factory() as session:
                    svc = EventService(session)
                    event = await svc.create(
                        title=fsm_data["title"],
                        description=fsm_data.get("description"),
                        date=event_date,
                        location=fsm_data.get("location"),
                        price=fsm_data["price"],
                        total_tickets=fsm_data["tickets"],
                        channel_id=fsm_data["channel_id"],
                    )
                    await session.commit()
            except Exception as e:
                await callback.message.edit_text(
                    f"❌ Ошибка при создании мероприятия: {e}"
                )
                await state.clear()
                return

            await state.clear()
            await callback.message.edit_text(
                f"✅ Мероприятие «{event.title}» создано!\n"
                f"Анонс будет отправлен в канал.",
                parse_mode="HTML",
            )
            # Анонс отправляем после всего — если упадёт, пользователь
            # уже получил подтверждение
            try:
                await self.post_announcement(event.id)
            except Exception as e:
                logger.error("Ошибка отправки анонса для %s: %s", event.id, e)
            return

        # ─── Админ: отмена создания ─────────────────────
        if data == "admin:cancel_create":
            await callback.answer()
            await state.clear()
            await callback.message.edit_text("❌ Создание отменено.")
            return

        # ─── Админ-меню: навигация по кнопкам ───────────
        if data.startswith("admin_menu:"):
            await callback.answer()
            action = data.split(":", 1)[1]

            if action == "back":
                is_super = self._is_super_admin(callback.from_user.id)
                kb = self._admin_menu_kb(is_super)
                title = "🎫 <b>Панель управления</b>\n\n<i>Выберите действие:</i>"
                await callback.message.edit_text(title, parse_mode="HTML", reply_markup=kb)
                return

            user_id = callback.from_user.id
            is_super = self._is_super_admin(user_id)

            if not is_super:
                ch = await self._get_admin_channel(user_id)
                if not ch:
                    await callback.message.edit_text("У вас нет доступа.")
                    return

            # Actions that require super-admin
            super_only = {
                "stats_all", "check_expired", "list_channels",
                "channel_info", "user_info", "subscribe", "unsubscribe",
                "change_admin", "broadcast", "health", "admin_cancel",
            }
            if action in super_only and not is_super:
                await callback.message.edit_text("❌ У вас нет доступа к этому разделу.")
                return

            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu:back")],
            ])
            edit = callback.message.edit_text

            if action == "stats_all":
                async with async_session_factory() as session:
                    users_c = (await session.execute(select(func.count()).select_from(User))).scalar() or 0
                    ch_c = (await session.execute(select(func.count()).select_from(Channel))).scalar() or 0
                    active_subs = (await session.execute(
                        select(func.count()).select_from(Channel).where(Channel.is_subscription_active == True)
                    )).scalar() or 0
                    ev_c = (await session.execute(select(func.count()).select_from(Event))).scalar() or 0
                    upcoming = (await session.execute(
                        select(func.count()).select_from(Event).where(Event.date >= datetime.now(timezone.utc))
                    )).scalar() or 0
                    tickets_active = (await session.execute(
                        select(func.count()).select_from(Ticket).where(Ticket.status == TicketStatus.active)
                    )).scalar() or 0
                    revenue = float((await session.execute(
                        select(func.coalesce(func.sum(Payment.amount), 0))
                        .where(Payment.status == PaymentStatus.completed)
                    )).scalar() or 0)
                await edit(
                    "📊 <b>Общая статистика</b>\n\n"
                    f"👥 Пользователей: {users_c}\n"
                    f"📢 Каналов: {ch_c} (активных подписок: {active_subs})\n"
                    f"🎫 Мероприятий: {ev_c} (предстоящих: {upcoming})\n"
                    f"🎟 Активных билетов: {tickets_active}\n"
                    f"💰 Выручка: {revenue:.0f}₽",
                    parse_mode="HTML", reply_markup=back_kb,
                )
                return

            if action == "check_expired":
                async with async_session_factory() as session:
                    channel_svc = ChannelService(session)
                    result = await session.execute(
                        select(Channel).where(Channel.is_subscription_active == True)
                    )
                    channels = list(result.scalars().all())
                    deactivated = 0
                    for ch in channels:
                        if not await channel_svc.is_subscription_valid(ch.id):
                            deactivated += 1
                    await session.commit()
                await edit(
                    f"🔍 Проверка завершена.\n"
                    f"📢 Всего каналов: {len(channels)}\n"
                    f"🔄 Отключено просроченных: {deactivated}",
                    reply_markup=back_kb,
                )
                return

            if action == "list_channels":
                async with async_session_factory() as session:
                    result = await session.execute(select(Channel).order_by(Channel.created_at.desc()))
                    channels = list(result.scalars().all())
                    admin_svc = ChannelAdminService(session)
                    ch_admins = {}
                    for ch in channels:
                        ch_admins[ch.id] = await admin_svc.get_admin_ids(ch.id)
                if not channels:
                    await edit("Нет зарегистрированных каналов.", reply_markup=back_kb)
                    return
                lines = ["📋 <b>Все каналы:</b>\n"]
                for ch in channels:
                    status = "🟢" if ch.is_subscription_active else "🔴"
                    admins = ch_admins.get(ch.id, [])
                    admin_display = ", ".join(a[:8] + "..." if len(a) > 8 else a for a in admins) if admins else "—"
                    lines.append(
                        f"{status} {ch.title or ch.telegram_channel_id}\n"
                        f"   Админы: {admin_display}\n"
                        f"   Подписка: {'до ' + ch.subscription_until.strftime('%d.%m.%Y') if ch.subscription_until else 'нет'}\n"
                    )
                await edit("\n".join(lines), parse_mode="HTML", reply_markup=back_kb)
                return

            if action == "health":
                text = (
                    "🩺 <b>Здоровье бота</b>\n\n"
                    "🤖 Статус: ✅ Работает\n"
                    f"👤 Username: @{self._bot_username or 'неизвестно'}\n\n"
                )
                try:
                    async with async_session_factory() as session:
                        from sqlalchemy import text as sqltext
                        await session.execute(sqltext("SELECT 1"))
                    text += "🗄 База данных: ✅ Подключена\n"
                except Exception:
                    text += "🗄 База данных: ❌ Ошибка\n"
                await edit(text, parse_mode="HTML", reply_markup=back_kb)
                return

            if action == "events_all":
                ch = await self._get_admin_channel(user_id)
                if not ch:
                    await edit("❌ У вас нет канала с активной подпиской.", reply_markup=back_kb)
                    return
                async with async_session_factory() as session:
                    svc = EventService(session)
                    events = await svc.list_all(channel_id=ch.id)
                if not events:
                    await edit("Нет мероприятий.", reply_markup=back_kb)
                    return
                lines = ["🎫 <b>Все мероприятия:</b>\n"]
                ev_kb_rows = []
                for e in events:
                    event_status = "🟢" if e.is_active else "🔴"
                    date_str = e.date.strftime("%d.%m.%Y %H:%M")
                    lines.append(
                        f"{event_status} <b>{e.title}</b>\n"
                        f"📅 {date_str}\n"
                        f"🎟 {e.available_tickets}/{e.total_tickets}\n"
                    )
                    title_btn = e.title[:40]
                    ev_kb_rows.append([
                        InlineKeyboardButton(text=f"🎫 {title_btn}", callback_data=f"ch_admin:menu:{e.id}"),
                    ])
                    toggle_label = "▶ Включить" if not e.is_active else "⏸ Отключить"
                    ev_kb_rows.append([
                        InlineKeyboardButton(text="📊 Статистика", callback_data=f"ch_admin:stats:{e.id}"),
                        InlineKeyboardButton(text=toggle_label, callback_data=f"ch_admin:toggle:{e.id}"),
                    ])
                ev_kb_rows.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu:back")])
                ev_kb = InlineKeyboardMarkup(inline_keyboard=ev_kb_rows) if ev_kb_rows else None
                await edit("\n".join(lines), parse_mode="HTML", reply_markup=ev_kb)
                return

            if action == "repost_events":
                ch = await self._get_admin_channel(user_id)
                if not ch:
                    await edit("❌ У вас нет канала с активной подпиской.", reply_markup=back_kb)
                    return
                async with async_session_factory() as session:
                    svc = EventService(session)
                    events = await svc.list_upcoming(channel_id=ch.id)
                if not events:
                    await edit("Нет активных мероприятий для анонса.", reply_markup=back_kb)
                    return
                posted = 0
                for ev in events:
                    try:
                        await self.channel.post_event_announcement(ev, ch.telegram_channel_id)
                        posted += 1
                    except Exception as e:
                        logger.error("Ошибка репоста %s: %s", ev.id, e)
                await edit(f"✅ Анонсы перепощены в канал: {posted}/{len(events)}", reply_markup=back_kb)
                return

            if action == "my_channels":
                async with async_session_factory() as session:
                    channel_svc = ChannelService(session)
                    channels = await channel_svc.get_channels_by_admin(str(user_id))
                if not channels:
                    await edit("У вас нет зарегистрированных каналов.", reply_markup=back_kb)
                    return
                lines = ["📢 <b>Ваши каналы:</b>\n"]
                for ch in channels:
                    status = "🟢 Активна" if ch.is_subscription_active else "🔴 Неактивна"
                    until = ""
                    if ch.subscription_until:
                        until = f" до {ch.subscription_until.strftime('%d.%m.%Y')}"
                    lines.append(
                        f"📌 {ch.title or ch.telegram_channel_id}\n"
                        f"   {status}{until}\n"
                    )
                await edit("\n".join(lines), parse_mode="HTML", reply_markup=back_kb)
                return

            # ─── FSM: create_event ────────────────────────────────────
            if action == "create_event":
                ch = await self._get_admin_channel(user_id)
                if not ch:
                    await edit("❌ У вас нет канала с активной подпиской.", reply_markup=back_kb)
                    return
                await state.update_data(channel_id=ch.id)
                await state.set_state(CreateEvent.title)
                await callback.message.answer(
                    "📝 Введите <b>название</b> мероприятия:",
                    parse_mode="HTML",
                )
                return

            # ─── FSM: broadcast ──────────────────────────────────────
            if action == "broadcast":
                await state.set_state(BroadcastFSM.text)
                await callback.message.answer(
                    "📢 <b>Рассылка</b>\n\n"
                    "Отправьте сообщение, которое будет разослано во все каналы.\n"
                    "Или отправьте /cancel для отмены.",
                    parse_mode="HTML",
                )
                return

            # ─── FSM для кнопок, требующих ввод параметра ──────
            input_actions = {
                "channel_info": "ℹ️ <b>Информация о канале</b>\n\nВведите @username или ID канала:",
                "user_info": "👥 <b>Информация о пользователе</b>\n\nВведите Telegram ID пользователя:",
                "subscribe": "🟢 <b>Подписка (активация)</b>\n\nВведите @username канала и количество дней через пробел:\nПример: <code>@my_channel 30</code>",
                "unsubscribe": "🔴 <b>Подписка (отключение)</b>\n\nВведите @username канала:",
                "change_admin": "🔄 <b>Смена администратора канала</b>\n\nВведите @username канала и новый Telegram ID через пробел:\nПример: <code>@my_channel 123456789</code>",
                "admin_cancel": "✅ <b>Отмена билета (админ)</b>\n\nВведите ID билета:",
            }
            if action in input_actions:
                await state.update_data(admin_action=action)
                await state.set_state(AwaitingAdminInput.text)
                await callback.message.answer(input_actions[action], parse_mode="HTML")
                return

            await callback.answer("Неизвестная команда", show_alert=True)
            return

        # ─── Навигация по страницам мероприятий ──────────
        if data.startswith("ev_page:"):
            if data == "ev_page:current":
                await callback.answer()
                return
            page = int(data.split(":")[1])
            async with async_session_factory() as session:
                svc = EventService(session)
                events = await svc.list_upcoming()
            if events:
                await self._send_event_page(callback.message.edit_text, events, page)
            await callback.answer()
            return

        # ─── Детали мероприятия ──────────────────────────
        if data.startswith("ev_detail:"):
            event_id = UUID(data.split(":", 1)[1])
            async with async_session_factory() as session:
                svc = EventService(session)
                event = await svc.get_by_id(event_id)
            if event:
                await self._send_event_detail(callback.message.edit_text, event)
            else:
                await callback.answer("Мероприятие не найдено", show_alert=True)
            await callback.answer()
            return

        # ─── Покупка билета ──────────────────────────────
        if data.startswith("buy:"):
            event_id = UUID(data.split(":", 1)[1])
            user_id = await self._resolve_user_id(
                str(callback.from_user.id),
                callback.from_user.full_name or "",
            )
            async with async_session_factory() as session:
                ticket_svc = TicketService(session)
                try:
                    ticket = await ticket_svc.buy_ticket(user_id, event_id)
                    await session.commit()
                    await callback.answer("✅ Билет куплен!", show_alert=True)
                    await callback.message.edit_text(
                        f"✅ Билет куплен!\n"
                        f"Номер: <code>{ticket.id}</code>",
                        parse_mode="HTML",
                    )
                except ValueError as e:
                    await callback.answer(f"❌ {e}", show_alert=True)
            return

        # ─── Отмена билета ──────────────────────────────
        if data.startswith("ticket_cancel:"):
            ticket_id = UUID(data.split(":", 1)[1])
            user_id = await self._resolve_user_id(
                str(callback.from_user.id),
                callback.from_user.full_name or "",
            )
            async with async_session_factory() as session:
                ticket_svc = TicketService(session)
                try:
                    await ticket_svc.cancel_ticket(ticket_id, user_id)
                    await session.commit()
                    await callback.answer("✅ Билет возвращён!", show_alert=True)
                    tickets = await ticket_svc.get_user_tickets(user_id)
                    if tickets:
                        await self._send_tickets(callback.message.edit_text, tickets)
                    else:
                        await callback.message.edit_text("✅ Билет возвращён.\nУ вас нет билетов.")
                except ValueError as e:
                    await callback.answer(f"❌ {e}", show_alert=True)
            return

        await callback.answer("Команда не распознана", show_alert=True)

    # ═══════════════════════════════════════════════════════
    # ХЕНДЛЕРЫ КАНАЛА (только просмотр)
    # ═══════════════════════════════════════════════════════

    async def channel_cmd_events(self, channel_post: types.Message):
        """/events в канале — выводит список мероприятий этого канала."""
        source_chat_id = str(channel_post.chat.id) if channel_post.chat else None

        async with async_session_factory() as session:
            channel_svc = ChannelService(session)
            channel = None
            if source_chat_id:
                channel = await channel_svc.get_by_telegram_id(source_chat_id)

            event_svc = EventService(session)
            events = await event_svc.list_upcoming(channel_id=channel.id if channel else None)

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
            )

        lines.append("\nℹ️ Купить билет — откройте меню бота ☰ или нажмите 🎟 Купить в анонсе.")
        await channel_post.answer("\n".join(lines), parse_mode="HTML")

    async def channel_cmd_event(self, channel_post: types.Message):
        """/event <id> в канале — детали мероприятия прямо в канал."""
        args = channel_post.text.split(maxsplit=1)
        if len(args) < 2:
            await channel_post.answer("📌 Чтобы посмотреть детали мероприятия, нажмите 🎟 Купить в анонсе или откройте меню бота.")
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
            f"👇 Для покупки откройте меню бота ☰ "
            f"или нажмите 🎟 Купить в анонсе канала."
        )

        await channel_post.answer(text, parse_mode="HTML")

    # ═══════════════════════════════════════════════════════
    # ХЕНДЛЕРЫ ДЛЯ КАНАЛА (callback-кнопки в анонсах)
    # ═══════════════════════════════════════════════════════

    async def _handle_channel_buy(self, callback: types.CallbackQuery, event_id: UUID):
        """Покупка билета из канала — по кнопке в анонсе."""
        try:
            user_id = await self._resolve_user_id(
                str(callback.from_user.id),
                callback.from_user.full_name or "",
            )
        except Exception:
            await callback.answer(
                "ℹ️ Напишите @username бота /start, чтобы начать покупку билетов.",
                show_alert=True,
            )
            return

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            try:
                ticket = await ticket_svc.buy_ticket(user_id, event_id)
                await session.commit()
                await callback.answer(
                    f"✅ Билет куплен! Номер: {ticket.id}",
                    show_alert=True,
                )
            except ValueError as e:
                await callback.answer(f"❌ {e}", show_alert=True)

    async def _handle_channel_my_tickets(self, callback: types.CallbackQuery):
        """Показать билеты пользователя — в ЛС или подсказка."""
        try:
            user_id = await self._resolve_user_id(
                str(callback.from_user.id),
                callback.from_user.full_name or "",
            )
        except Exception:
            await callback.answer(
                "ℹ️ Напишите @username бота /start, чтобы увидеть билеты.",
                show_alert=True,
            )
            return

        async with async_session_factory() as session:
            ticket_svc = TicketService(session)
            tickets = await ticket_svc.get_user_tickets(user_id)

        if not tickets:
            await callback.answer("У вас нет билетов.", show_alert=True)
            return

        try:
            await self._send_tickets(
                lambda text, **kw: self.bot.send_message(
                    chat_id=callback.from_user.id, text=text, **kw,
                ),
                tickets,
            )
            await callback.answer("📨 Список билетов отправлен в личные сообщения.", show_alert=False)
        except Exception:
            await callback.answer(
                "ℹ️ Напишите @username бота /start, чтобы увидеть билеты.",
                show_alert=True,
            )

    async def _handle_channel_events(self, callback: types.CallbackQuery):
        """Показать список мероприятий канала — в ЛС или подсказка."""
        # Determine channel context from the message's chat
        source_chat_id = str(callback.message.chat.id) if callback.message else None

        async with async_session_factory() as session:
            channel_svc = ChannelService(session)
            channel = None
            if source_chat_id:
                channel = await channel_svc.get_by_telegram_id(source_chat_id)

            event_svc = EventService(session)
            events = await event_svc.list_upcoming(channel_id=channel.id if channel else None)

        if not events:
            await callback.answer("😔 Нет предстоящих мероприятий.", show_alert=True)
            return

        try:
            await self._send_event_page(
                lambda text, **kw: self.bot.send_message(
                    chat_id=callback.from_user.id, text=text, **kw,
                ),
                events,
                page=0,
            )
            await callback.answer("📨 Список мероприятий отправлен в личные сообщения.", show_alert=False)
        except Exception:
            await callback.answer(
                "ℹ️ Напишите @username бота /start, чтобы увидеть мероприятия.",
                show_alert=True,
            )

    # ═══════════════════════════════════════════════════════
    # КАНАЛ: АДМИН-ПАНЕЛЬ (через кнопку «🎛 Управление»)
    # ═══════════════════════════════════════════════════════

    async def _send_ch_admin_panel(
        self,
        user_id: int,
        event,
        edit_message: types.Message | None = None,
    ):
        """Отправить или обновить панель управления мероприятием в ЛС админа."""
        date_str = event.date.strftime("%d.%m.%Y %H:%M")
        status = "🟢 Активно" if event.is_active else "🔴 Отключено"
        header = (
            f"🎫 <b>{event.title}</b>\n"
            f"📅 {date_str}\n"
            f"🎟 {event.available_tickets}/{event.total_tickets}\n"
            f"{status}\n\n"
            f"<b>Выберите действие:</b>"
        )

        rows = [
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data=f"ch_admin:stats:{event.id}"),
                InlineKeyboardButton(
                    text="⏸ Отключить" if event.is_active else "▶ Включить",
                    callback_data=f"ch_admin:toggle:{event.id}",
                ),
            ],
            [
                InlineKeyboardButton(text="🔄 Репост анонса", callback_data=f"ch_admin:repost:{event.id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Закрыть панель", callback_data="ch_admin:close"),
            ],
        ]

        kb = InlineKeyboardMarkup(inline_keyboard=rows)

        if edit_message:
            await edit_message.edit_text(header, parse_mode="HTML", reply_markup=kb)
        else:
            await self.bot.send_message(
                chat_id=user_id,
                text=header,
                parse_mode="HTML",
                reply_markup=kb,
            )

    async def _handle_channel_admin(self, callback: types.CallbackQuery, data: str):
        """Обработка всех ch_admin:* callback'ов.

        Приходит из двух мест:
        - Из канала: нажали «🎛 Управление» на анонсе → проверить админа → панель в ЛС
        - Из ЛС: кнопки панели (статистика, включить/отключить, репост, закрыть)
        """
        parts = data.split(":", 2)
        action = parts[1] if len(parts) > 1 else ""
        event_id = UUID(parts[2]) if len(parts) > 2 and parts[2] else None

        # ─── Определяем, откуда пришёл callback ────────────
        is_from_channel = callback.message and callback.message.chat.type == "channel"

        # ─── Из канала: кнопка «🎛 Управление» на анонсе ──
        if is_from_channel:
            if action != "menu" or not event_id:
                await callback.answer()
                return

            # Проверить, что нажавший — админ этого канала
            source_chat_id = str(callback.message.chat.id)
            async with async_session_factory() as session:
                channel_svc = ChannelService(session)
                admin_svc = ChannelAdminService(session)
                channel = await channel_svc.get_by_telegram_id(source_chat_id)
                is_super = self._is_super_admin(callback.from_user.id)
                is_admin = channel and await admin_svc.user_is_admin(
                    channel.id, str(callback.from_user.id),
                )
                if not channel or (not is_admin and not is_super):
                    await callback.answer(
                        "❌ Доступно только администратору канала.",
                        show_alert=True,
                    )
                    return

            await callback.answer()

            # Загрузить мероприятие
            async with async_session_factory() as session:
                svc = EventService(session)
                event = await svc.get_by_id(event_id)
                if not event:
                    await callback.answer("❌ Мероприятие не найдено.", show_alert=True)
                    return

            # Отправить панель в ЛС
            try:
                await self._send_ch_admin_panel(callback.from_user.id, event)
                await callback.answer(
                    "📨 Панель отправлена в личные сообщения.",
                    show_alert=True,
                )
            except Exception:
                await callback.answer(
                    "ℹ️ Напишите /start боту в личных сообщениях, чтобы открыть панель.",
                    show_alert=True,
                )
            return

        # ─── Из ЛС: кнопки панели управления ───────────────
        # Проверить, что пользователь — админ канала (или super-admin)
        channel = await self._get_admin_channel(callback.from_user.id)
        is_super = self._is_super_admin(callback.from_user.id)
        if not channel and not is_super:
            await callback.answer("❌ Доступно только администратору канала.", show_alert=True)
            return

        # ─── Показать панель (menu) ────────────────────────
        if action == "menu" and event_id:
            async with async_session_factory() as session:
                svc = EventService(session)
                event = await svc.get_by_id(event_id)
                if not event:
                    await callback.answer("❌ Мероприятие не найдено.", show_alert=True)
                    return
            await self._send_ch_admin_panel(
                callback.from_user.id, event, edit_message=callback.message,
            )
            await callback.answer()
            return

        # ─── Статистика ────────────────────────────────────
        if action == "stats" and event_id:
            async with async_session_factory() as session:
                svc = EventService(session)
                event = await svc.get_by_id(event_id)
                if not event:
                    await callback.answer("❌ Мероприятие не найдено.", show_alert=True)
                    return
                try:
                    stats = await svc.get_event_stats(event_id)
                except ValueError:
                    await callback.answer("❌ Статистика недоступна.", show_alert=True)
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
            back_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="◀️ Назад к панели",
                    callback_data=f"ch_admin:menu:{event_id}",
                )],
            ])
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
            await callback.answer()
            return

        # ─── Включить / Отключить ─────────────────────────
        if action == "toggle" and event_id:
            async with async_session_factory() as session:
                svc = EventService(session)
                event = await svc.get_by_id(event_id)
                if not event:
                    await callback.answer("❌ Мероприятие не найдено.", show_alert=True)
                    return
                await svc.set_active(event_id, not event.is_active)
                await session.commit()
                event.is_active = not event.is_active  # обновить локально

            await self._send_ch_admin_panel(
                callback.from_user.id, event, edit_message=callback.message,
            )
            await callback.answer()
            return

        # ─── Репост анонса ────────────────────────────────
        if action == "repost" and event_id:
            async with async_session_factory() as session:
                svc = EventService(session)
                event = await svc.get_by_id(event_id)
                if not event:
                    await callback.answer("❌ Мероприятие не найдено.", show_alert=True)
                    return

                channel_svc = ChannelService(session)
                channel_obj = await channel_svc.get_by_id(event.channel_id)
                if not channel_obj:
                    await callback.answer("❌ Канал не найден.", show_alert=True)
                    return

            try:
                await self.channel.post_event_announcement(event, channel_obj.telegram_channel_id)
                await callback.answer("✅ Анонс перепощен в канал!", show_alert=True)
            except Exception:
                await callback.answer("❌ Ошибка репоста.", show_alert=True)
            return

        # ─── Закрыть панель ──────────────────────────────
        if action == "close":
            try:
                await callback.message.delete()
            except Exception:
                await callback.message.edit_text("❌ Панель закрыта.")
            await callback.answer()
            return

        await callback.answer()

    # ═══════════════════════════════════════════════════════
    # ПУБЛИЧНЫЕ МЕТОДЫ
    # ═══════════════════════════════════════════════════════

    async def post_announcement(self, event_id: UUID):
        """Отправить анонс мероприятия в его канал. Вызывается из seed/admin."""
        async with async_session_factory() as session:
            from app.core.services import ChannelService
            event_svc = EventService(session)
            event = await event_svc.get_by_id(event_id)
            if event and event.channel_id:
                channel_svc = ChannelService(session)
                channel = await channel_svc.get_by_id(event.channel_id)
                if channel:
                    await self.channel.post_event_announcement(event, channel.telegram_channel_id)

    # ═══════════════════════════════════════════════════════
    # ЗАПУСК / ОСТАНОВКА
    # ═══════════════════════════════════════════════════════

    async def run(self):
        import asyncio

        retries = 0
        max_retries = 10
        while retries < max_retries:
            try:
                # Получаем username бота (в aiogram 3.x нет bot.username)
                me = await self.bot.get_me()
                self._bot_username = me.username
                self.channel.bot_username = me.username

                # Устанавливаем Menu Button: пользователи видят команды в меню
                await self.bot.set_my_commands(
                    commands=USER_COMMANDS,
                    scope=BotCommandScopeAllPrivateChats(),
                )

                await self.dp.start_polling(
                    self.bot,
                    allowed_updates=["message", "channel_post", "callback_query", "my_chat_member"],
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
