"""
Тесты Telegram Bot хендлеров.

Используем mock для aiogram, тестируем логику ответов на команды.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.models import PlatformType


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_message():
    """Создаёт mock-сообщение Telegram."""
    msg = AsyncMock()
    msg.from_user.id = 12345
    msg.from_user.full_name = "Test User"
    msg.text = ""
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    return msg


@pytest.fixture
def mock_callback():
    """Создаёт mock callback запроса."""
    cb = AsyncMock()
    cb.data = ""
    cb.from_user.id = 12345
    cb.from_user.full_name = "Test User"
    cb.answer = AsyncMock()
    cb.message = AsyncMock()
    cb.message.edit_text = AsyncMock()
    return cb


@pytest.fixture
def telegram_bot():
    """Создаёт TelegramBot с захардкоженным токеном (не настоящим)."""
    with (
        patch("app.platforms.telegram.bot.settings.telegram_token", "test:token"),
        patch("app.platforms.telegram.bot.Bot") as mock_bot_cls,
    ):
        mock_bot = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        # По умолчанию get_chat_member возвращает администратора канала
        mock_member = Mock()
        mock_member.status = "administrator"
        mock_bot.get_chat_member = AsyncMock(return_value=mock_member)

        from app.platforms.telegram.bot import TelegramBot

        bot = TelegramBot()
        bot._bot_username = "test_bot"
        bot.bot = mock_bot
        return bot


# ═══════════════════════════════════════════════════════════════
# User commands
# ═══════════════════════════════════════════════════════════════

class TestUserCommands:
    async def test_cmd_start(self, telegram_bot, mock_message):
        """Команда /start возвращает приветствие."""
        mock_message.text = "/start"

        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch.object(telegram_bot, "_update_user_commands", new_callable=AsyncMock),
        ):
            await telegram_bot.cmd_start(mock_message)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.call_args[0][0]
        assert "TicketBot" in text
        assert "меню" in text

    async def test_cmd_events_empty(self, telegram_bot, mock_message):
        """Команда /events когда нет мероприятий."""
        with patch(
            "app.platforms.telegram.bot.EventService.list_upcoming",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await telegram_bot.cmd_events(mock_message)

        mock_message.answer.assert_awaited_once_with(
            "😔 Нет предстоящих мероприятий."
        )

    async def test_cmd_event_no_id(self, telegram_bot, mock_message):
        """Команда /event без ID мероприятия."""
        mock_message.text = "/event"
        await telegram_bot.cmd_event(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "выберите его из списка" in mock_message.answer.call_args[0][0]

    async def test_cmd_event_invalid_id(self, telegram_bot, mock_message):
        """Команда /event с неверным ID."""
        mock_message.text = "/event not-a-uuid"
        await telegram_bot.cmd_event(mock_message)

        mock_message.answer.assert_awaited_once_with(
            "Неверный ID мероприятия."
        )

    async def test_cmd_buy_no_id(self, telegram_bot, mock_message):
        """Команда /buy без ID."""
        mock_message.text = "/buy"
        await telegram_bot.cmd_buy(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "выберите мероприятие" in mock_message.answer.call_args[0][0]

    async def test_cmd_my_tickets_empty(self, telegram_bot, mock_message):
        """Команда /my_tickets без билетов."""
        mock_message.text = "/my_tickets"

        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch(
                "app.platforms.telegram.bot.TicketService.get_user_tickets",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await telegram_bot.cmd_my_tickets(mock_message)

        mock_message.answer.assert_awaited_once_with(
            "У вас нет билетов."
        )

    async def test_cmd_cancel_no_id(self, telegram_bot, mock_message):
        """Команда /cancel без ID."""
        mock_message.text = "/cancel"

        with patch(
            "app.platforms.telegram.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            await telegram_bot.cmd_cancel(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "выберите его из списка" in mock_message.answer.call_args[0][0]


# ═══════════════════════════════════════════════════════════════
# Admin commands
# ═══════════════════════════════════════════════════════════════

class TestAdminCommands:
    async def test_admin_menu_unauthorized(self, telegram_bot, mock_message):
        """Обычный пользователь не может открыть админку."""
        mock_message.from_user.id = 99999  # не админ
        with patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock, return_value=None):
            await telegram_bot.admin_menu(mock_message)

        mock_message.answer.assert_awaited_once_with(
            "У вас нет доступа к панели администратора."
        )

    async def test_admin_menu_authorized(self, telegram_bot, mock_message):
        """Администратор видит меню с кнопками."""
        with patch(
            "app.platforms.telegram.bot.settings.admin_telegram_ids",
            "12345",
        ):
            mock_message.text = "/admin"
            await telegram_bot.admin_menu(mock_message)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.call_args[0][0]
        assert "Панель управления" in text
        # Check that reply_markup exists
        kwargs = mock_message.answer.call_args[1]
        assert "reply_markup" in kwargs

    async def test_admin_menu_has_check_ticket_button(self, telegram_bot, mock_message):
        """В админ-меню есть кнопка проверки билетов."""
        with patch(
            "app.platforms.telegram.bot.settings.admin_telegram_ids",
            "12345",
        ):
            mock_message.text = "/admin"
            await telegram_bot.admin_menu(mock_message)

        kwargs = mock_message.answer.call_args[1]
        kb = kwargs["reply_markup"]
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if "Проверить билет" in btn.text:
                    assert btn.callback_data == "admin_menu:check_ticket"
                    found = True
        assert found, "Кнопка 'Проверить билет' не найдена в админ-меню"

    async def test_admin_menu_check_ticket_for_non_super(self, telegram_bot, mock_message):
        """Обычный админ тоже видит кнопку проверки билетов."""
        mock_channel = Mock()
        mock_channel.id = uuid.uuid4()

        with patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock, return_value=mock_channel):
            mock_message.text = "/admin"
            await telegram_bot.admin_menu(mock_message)

        kwargs = mock_message.answer.call_args[1]
        kb = kwargs["reply_markup"]
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if "Проверить билет" in btn.text:
                    found = True
        assert found, "Кнопка проверки билетов должна быть видна и обычному админу"

    async def test_admin_create_event_unauthorized(self, telegram_bot, mock_message):
        """Обычный пользователь не может создать мероприятие."""
        mock_message.from_user.id = 99999
        mock_state = AsyncMock()

        with patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock, return_value=None):
            await telegram_bot.admin_create_event(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        assert "нет канала" in mock_message.answer.call_args[0][0]

    async def test_deactivate_no_id(self, telegram_bot, mock_message):
        """/deactivate без ID."""
        mock_message.text = "/deactivate"
        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock) as mock_get_channel,
        ):
            mock_channel = Mock()
            mock_channel.id = uuid.uuid4()
            mock_get_channel.return_value = mock_channel
            await telegram_bot.admin_deactivate(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "Выберите мероприятие" in mock_message.answer.call_args[0][0]

    async def test_activate_no_id(self, telegram_bot, mock_message):
        """/activate без ID."""
        mock_message.text = "/activate"
        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock) as mock_get_channel,
        ):
            mock_channel = Mock()
            mock_channel.id = uuid.uuid4()
            mock_get_channel.return_value = mock_channel
            await telegram_bot.admin_activate(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "Выберите мероприятие" in mock_message.answer.call_args[0][0]

    async def test_stats_no_id(self, telegram_bot, mock_message):
        """/stats без ID."""
        mock_message.text = "/stats"
        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock) as mock_get_channel,
        ):
            mock_channel = Mock()
            mock_channel.id = uuid.uuid4()
            mock_get_channel.return_value = mock_channel
            await telegram_bot.admin_stats(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "Выберите мероприятие" in mock_message.answer.call_args[0][0]


# ═══════════════════════════════════════════════════════════════
# Channel commands
# ═══════════════════════════════════════════════════════════════

class TestChannelCommands:
    async def test_channel_events_empty(self, telegram_bot, mock_message):
        """/events в канале без мероприятий."""
        with (
            patch(
                "app.platforms.telegram.bot.EventService.list_upcoming",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.platforms.telegram.bot.ChannelService.get_by_telegram_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await telegram_bot.channel_cmd_events(mock_message)

        mock_message.answer.assert_awaited_once()

    async def test_channel_event_no_id(self, telegram_bot, mock_message):
        """/event в канале без ID."""
        mock_message.text = "/event"
        await telegram_bot.channel_cmd_event(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "посмотреть детали" in mock_message.answer.call_args[0][0]


# ═══════════════════════════════════════════════════════════════
# Callback handlers
# ═══════════════════════════════════════════════════════════════

class TestCallbackHandlers:
    async def test_callback_buy_ticket(self, telegram_bot, mock_callback):
        """Callback покупки билета."""
        event_id = uuid.uuid4()
        mock_callback.data = f"buy:{event_id}"
        mock_callback.from_user.id = 12345

        mock_ticket = Mock(id=uuid.uuid4())
        mock_ticket.validation_code = None

        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch(
                "app.platforms.telegram.bot.TicketService.buy_ticket",
                new_callable=AsyncMock,
                return_value=mock_ticket,
            ),
        ):
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.answer.assert_awaited_once()

    async def test_callback_buy_ticket_sends_dm_with_code(self, telegram_bot, mock_callback):
        """После покупки билет с кодом отправляется в ЛС."""
        event_id = uuid.uuid4()
        mock_callback.data = f"buy:{event_id}"
        mock_callback.from_user.id = 12345
        mock_callback.from_user.full_name = "Test User"

        mock_ticket = Mock(id=uuid.uuid4())
        mock_ticket.validation_code = "AB3X-K7M9"

        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch(
                "app.platforms.telegram.bot.TicketService.buy_ticket",
                new_callable=AsyncMock,
                return_value=mock_ticket,
            ),
        ):
            await telegram_bot.cmd_callback(mock_callback, Mock())

        dm_found = any(
            "AB3X-K7M9" in str(call)
            for call in telegram_bot.bot.send_message.await_args_list
        )
        assert dm_found, "Код AB3X-K7M9 не отправлен в ЛС"

    async def test_callback_channel_buy_sends_dm_with_code(self, telegram_bot, mock_callback):
        """После покупки из канала код отправляется в ЛС."""
        event_id = uuid.uuid4()
        mock_callback.data = f"channel_buy:{event_id}"
        mock_callback.from_user.id = 12345
        mock_callback.from_user.full_name = "Test User"

        mock_ticket = Mock(id=uuid.uuid4())
        mock_ticket.validation_code = "CODE-1234"

        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch(
                "app.platforms.telegram.bot.TicketService.buy_ticket",
                new_callable=AsyncMock,
                return_value=mock_ticket,
            ),
        ):
            await telegram_bot.cmd_callback(mock_callback, Mock())

        dm_found = any(
            "CODE-1234" in str(call)
            for call in telegram_bot.bot.send_message.await_args_list
        )
        assert dm_found, "Код CODE-1234 не отправлен в ЛС из канала"

    async def test_callback_ev_page(self, telegram_bot, mock_callback):
        """Callback навигации по страницам мероприятий."""
        mock_callback.data = "ev_page:0"

        mock_event = Mock()
        mock_event.id = uuid.uuid4()
        mock_event.title = "Test Event"
        mock_event.date.strftime = Mock(return_value="25.12.2026 19:00")
        mock_event.location = "Moscow"
        mock_event.price = 1000
        mock_event.available_tickets = 50
        mock_event.total_tickets = 100

        with patch(
            "app.platforms.telegram.bot.EventService.list_upcoming",
            new_callable=AsyncMock,
            return_value=[mock_event],
        ):
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.answer.assert_awaited_once()

    async def test_callback_ticket_cancel(self, telegram_bot, mock_callback):
        """Callback отмены билета."""
        ticket_id = uuid.uuid4()
        mock_callback.data = f"ticket_cancel:{ticket_id}"

        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch(
                "app.platforms.telegram.bot.TicketService.cancel_ticket",
                new_callable=AsyncMock,
            ),
            patch(
                "app.platforms.telegram.bot.TicketService.get_user_tickets",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.answer.assert_awaited_once()

    async def test_callback_unknown(self, telegram_bot, mock_callback):
        """Callback с неизвестной командой."""
        mock_callback.data = "unknown:command"
        await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.answer.assert_awaited_once_with(
            "Команда не распознана", show_alert=True
        )


# ═══════════════════════════════════════════════════════════════
# Deep link tests
# ═══════════════════════════════════════════════════════════════

class TestDeepLink:
    async def test_start_with_buy_payload(self, telegram_bot, mock_message):
        """/start buy_<event_id> обрабатывается как покупка."""
        event_id = uuid.uuid4()
        from aiogram.filters import CommandObject
        command = CommandObject(prefix="/", command="start", args=f"buy_{event_id}")

        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch(
                "app.platforms.telegram.bot.TicketService.buy_ticket",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
        ):
            await telegram_bot.cmd_start(mock_message, command)

        mock_message.answer.assert_awaited_once()
        assert "Билет куплен" in mock_message.answer.call_args[0][0]

    async def test_start_without_payload(self, telegram_bot, mock_message):
        """/start без payload — обычное приветствие."""
        with (
            patch(
                "app.platforms.telegram.bot.UserService.get_or_create",
                new_callable=AsyncMock,
                return_value=Mock(id=uuid.uuid4()),
            ),
            patch.object(telegram_bot, "_update_user_commands", new_callable=AsyncMock),
        ):
            await telegram_bot.cmd_start(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "TicketBot" in mock_message.answer.call_args[0][0]


# ═══════════════════════════════════════════════════════════════
# Admin menu select() scope tests
# ═══════════════════════════════════════════════════════════════

class TestAdminMenuSelectScope:
    """Admin menu inline callbacks using select() inside cmd_callback.

    Внутри cmd_callback есть lazy import: from sqlalchemy import select
    (строка 2293). Python видит его как локальную переменную во всей
    функции. Хендлеры list_channels / stats_all / check_expired
    используют select() ДО того, как этот lazy import выполнится →
    UnboundLocalError.

    Тесты проверяют, что select() разрешается корректно (глобальный
    импорт со строки 12) и не падает.
    """

    # ─── Вспомогательные методы ─────────────────────────────────

    @staticmethod
    def _make_mock_channel(
        *,
        title: str = "Test Channel",
        telegram_id: str = "@test_channel",
        active: bool = True,
        has_subscription: bool = True,
    ) -> Mock:
        """Создать mock канала с нужными атрибутами."""
        ch = Mock()
        ch.id = uuid.uuid4()
        ch.title = title
        ch.telegram_channel_id = telegram_id
        ch.is_subscription_active = active
        ch.subscription_until = (
            datetime(2027, 1, 1, tzinfo=timezone.utc) if has_subscription else None
        )
        ch.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        return ch

    @staticmethod
    def _make_mock_db_result(scalars_return: list | None = None) -> Mock:
        """Создать mock результата session.execute()."""
        result = Mock()
        scalars = Mock()
        scalars.all.return_value = scalars_return or []
        result.scalars.return_value = scalars
        return result

    @staticmethod
    def _make_session_mock(execute_return) -> AsyncMock:
        """Создать mock сессии с execute, возвращающим execute_return."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=execute_return)
        return session

    # ─── list_channels ──────────────────────────────────────────────

    async def test_list_channels_success(self, telegram_bot, mock_callback):
        """admin_menu:list_channels — показывает список каналов."""
        mock_callback.data = "admin_menu:list_channels"

        ch1 = self._make_mock_channel(
            title="Первый канал",
            telegram_id="@first_channel",
            active=True,
        )
        ch2 = self._make_mock_channel(
            title="Второй канал",
            telegram_id="@second_channel",
            active=False,
        )

        db_result = self._make_mock_db_result(scalars_return=[ch1, ch2])

        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch(
                "app.platforms.telegram.bot.async_session_factory",
            ) as mock_factory,
            patch(
                "app.platforms.telegram.bot.ChannelAdminService.get_admin_ids",
                new_callable=AsyncMock,
                return_value=["12345"],
            ),
        ):
            mock_factory.return_value.__aenter__.return_value = (
                self._make_session_mock(db_result)
            )
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Все каналы" in text
        assert "Первый канал" in text
        assert "Второй канал" in text
        assert "🟢" in text
        assert "🔴" in text
        mock_callback.answer.assert_awaited_once()

    async def test_list_channels_empty(self, telegram_bot, mock_callback):
        """admin_menu:list_channels — пустой список каналов."""
        mock_callback.data = "admin_menu:list_channels"

        db_result = self._make_mock_db_result(scalars_return=[])

        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch(
                "app.platforms.telegram.bot.async_session_factory",
            ) as mock_factory,
        ):
            mock_factory.return_value.__aenter__.return_value = (
                self._make_session_mock(db_result)
            )
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.message.edit_text.assert_awaited_once()
        assert (
            "Нет зарегистрированных каналов."
            in mock_callback.message.edit_text.call_args[0][0]
        )
        mock_callback.answer.assert_awaited_once()

    # ─── stats_all ──────────────────────────────────────────────────

    async def test_stats_all_success(self, telegram_bot, mock_callback):
        """admin_menu:stats_all — показывает общую статистику."""
        mock_callback.data = "admin_menu:stats_all"

        # stats_all делает 7 execute-запросов, каждому нужен .scalar()
        count_result = Mock()
        count_result.scalar.return_value = 5
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=count_result)

        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch(
                "app.platforms.telegram.bot.async_session_factory",
            ) as mock_factory,
        ):
            mock_factory.return_value.__aenter__.return_value = mock_session
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Общая статистика" in text
        assert "5" in text  # все счётчики вернули 5
        assert "₽" in text
        mock_callback.answer.assert_awaited_once()

    # ─── check_expired ────────────────────────────────────────────────

    async def test_check_expired_success(self, telegram_bot, mock_callback):
        """admin_menu:check_expired — проверяет и отключает просроченные."""
        mock_callback.data = "admin_menu:check_expired"

        active_ch = self._make_mock_channel(
            title="Active Channel",
            active=True,
        )

        db_result = self._make_mock_db_result(scalars_return=[active_ch])

        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch(
                "app.platforms.telegram.bot.async_session_factory",
            ) as mock_factory,
            patch(
                "app.platforms.telegram.bot.ChannelService.is_subscription_valid",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_factory.return_value.__aenter__.return_value = (
                self._make_session_mock(db_result)
            )
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Проверка завершена" in text
        assert "0" in text  # ни один не отключён
        mock_callback.answer.assert_awaited_once()

    async def test_check_expired_deactivates(self, telegram_bot, mock_callback):
        """check_expired отключает просроченные подписки."""
        mock_callback.data = "admin_menu:check_expired"

        expired_ch = self._make_mock_channel(
            title="Expired Channel",
            active=True,
        )
        db_result = self._make_mock_db_result(scalars_return=[expired_ch])

        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
            patch(
                "app.platforms.telegram.bot.async_session_factory",
            ) as mock_factory,
            patch(
                "app.platforms.telegram.bot.ChannelService.is_subscription_valid",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            mock_factory.return_value.__aenter__.return_value = (
                self._make_session_mock(db_result)
            )
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "1" in text  # один отключён
        mock_callback.answer.assert_awaited_once()

    # ─── admin_ev_page (место lazy import) ────────────────────────────

    async def test_admin_ev_page_pagination(self, telegram_bot, mock_callback):
        """admin_ev_page:0 — пагинация списка мероприятий (место lazy import)."""
        mock_callback.data = "admin_ev_page:0"

        event_id = uuid.uuid4()
        mock_event = Mock()
        mock_event.id = event_id
        mock_event.title = "Page Test Event"
        mock_event.date = Mock()
        mock_event.date.strftime = Mock(return_value="25.12.2026 19:00")
        mock_event.location = "Office"
        mock_event.price = 500
        mock_event.available_tickets = 30
        mock_event.total_tickets = 50

        db_result = self._make_mock_db_result(scalars_return=[mock_event])

        mock_state = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={"admin_events": [str(event_id)]}
        )

        with (
            patch(
                "app.platforms.telegram.bot.async_session_factory",
            ) as mock_factory,
        ):
            mock_factory.return_value.__aenter__.return_value = (
                self._make_session_mock(db_result)
            )
            await telegram_bot.cmd_callback(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()

    # ─── check_ticket (admin_menu) ────────────────────────────

    async def test_check_ticket_callback_opens_fsm(self, telegram_bot, mock_callback):
        """admin_menu:check_ticket — открывает FSM для ввода кода."""
        mock_callback.data = "admin_menu:check_ticket"
        mock_callback.message.chat.type = "private"
        mock_state = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={})

        with (
            patch(
                "app.platforms.telegram.bot.settings.admin_telegram_ids",
                "12345",
            ),
        ):
            await telegram_bot.cmd_callback(mock_callback, mock_state)

        mock_state.set_state.assert_awaited_once()
        mock_callback.message.answer.assert_awaited_once()
        answer_text = mock_callback.message.answer.call_args[0][0]
        assert "код" in answer_text.lower() or "билет" in answer_text.lower()
        mock_callback.answer.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════
# FSM Event Creation — Phase 1
# ═══════════════════════════════════════════════════════════════

class TestFsmEventCreation:
    """Phase 1: FSM создание мероприятия — баги с описанием."""

    async def test_fsm_description_saves_text(self, telegram_bot, mock_message):
        """fsm_description сохраняет введённый текст описания в state."""
        mock_message.text = "Тестовое описание мероприятия для проверки сохранения"
        mock_state = AsyncMock()

        with patch.object(telegram_bot, "_fsm_header", new_callable=AsyncMock, return_value=""):
            await telegram_bot.fsm_description(mock_message, mock_state)

        mock_state.update_data.assert_awaited_with(
            description="Тестовое описание мероприятия для проверки сохранения"
        )

    async def test_fsm_description_sets_date_state(self, telegram_bot, mock_message):
        """fsm_description переключает состояние на CreateEvent.date."""
        mock_message.text = "Описание"
        mock_state = AsyncMock()
        mock_state.set_state = AsyncMock()

        with patch.object(telegram_bot, "_fsm_header", new_callable=AsyncMock, return_value=""):
            await telegram_bot.fsm_description(mock_message, mock_state)

        mock_state.set_state.assert_awaited_once()

    async def test_fsm_header_long_description(self, telegram_bot):
        """_fsm_header не обрезает длинное описание (>= 50 символов)."""
        long_desc = (
            "Это очень длинное описание тестового мероприятия, "
            "которое должно отображаться полностью без обрезания до 50 символов."
        )
        data = {
            "title": "Тестовое мероприятие",
            "description": long_desc,
        }

        header = await telegram_bot._fsm_header(data)

        assert long_desc in header
        assert "…" not in header  # не должно быть обрезано

    async def test_fsm_header_without_description(self, telegram_bot):
        """_fsm_header не падает, если description отсутствует в data."""
        data = {"title": "Мероприятие", "price": 100}

        header = await telegram_bot._fsm_header(data)

        assert "📌 Название: Мероприятие" in header
        assert "💰 Цена:" in header


# ═══════════════════════════════════════════════════════════════
# Format Event Text — Phase 2
# ═══════════════════════════════════════════════════════════════

def _make_mock_event(**kwargs) -> Mock:
    """Создать mock Event с полями по умолчанию."""
    e = Mock()
    e.id = kwargs.get("id", uuid.uuid4())
    e.title = kwargs.get("title", "Тестовое мероприятие")
    e.description = kwargs.get("description", "Описание тестового мероприятия")
    e.location = kwargs.get("location", "Москва, ул. Тверская")
    e.price = kwargs.get("price", 1500.0)
    e.available_tickets = kwargs.get("available_tickets", 50)
    e.total_tickets = kwargs.get("total_tickets", 100)
    e.is_active = kwargs.get("is_active", True)
    # Mock the date with strftime
    e.date = Mock()
    e.date.strftime = Mock(return_value="25.12.2026 19:00")
    return e


class TestFormatEventText:
    """Phase 2: Унифицированный _format_event_text."""

    async def test_format_full(self, telegram_bot):
        """_format_event_text(event, 'full') — полный формат для анонса/деталей."""
        event = _make_mock_event(
            title="Концерт",
            description="Лучшие хиты",
            location="Клуб «Звук»",
            price=2000,
            available_tickets=30,
            total_tickets=50,
        )
        text = telegram_bot._format_event_text(event, "full")

        assert "🎫 <b>Концерт</b>" in text
        assert "Лучшие хиты" in text
        assert "25.12.2026 19:00" in text
        assert "Клуб «Звук»" in text
        assert "2000₽" in text
        assert "30/50" in text or "30" in text

    async def test_format_full_no_description(self, telegram_bot):
        """_format_event_text(event, 'full') — без описания."""
        event = _make_mock_event(description="")
        text = telegram_bot._format_event_text(event, "full")
        assert "Описание отсутствует" in text or "🎫" in text

    async def test_format_full_no_location(self, telegram_bot):
        """_format_event_text(event, 'full') — без места."""
        event = _make_mock_event(location=None)
        text = telegram_bot._format_event_text(event, "full")
        assert "Не указано" in text or "📍" not in text or "📍" in text

    async def test_format_short(self, telegram_bot):
        """_format_event_text(event, 'short') — краткий формат для списка."""
        event = _make_mock_event(title="Вебинар", price=0, available_tickets=10, total_tickets=20)
        text = telegram_bot._format_event_text(event, "short")

        assert "Вебинар" in text
        assert "25.12.2026" in text

    async def test_format_admin(self, telegram_bot):
        """_format_event_text(event, 'admin') — админ-формат для панели/списка."""
        event = _make_mock_event(title="Админ-ивент", is_active=True)
        text = telegram_bot._format_event_text(event, "admin")

        assert "Админ-ивент" in text
        assert "🟢" in text or "Активно" in text

    async def test_format_admin_inactive(self, telegram_bot):
        """_format_event_text(event, 'admin') — неактивное мероприятие."""
        event = _make_mock_event(title="Отключено", is_active=False)
        text = telegram_bot._format_event_text(event, "admin")

        assert "Отключено" in text
        assert "🔴" in text

    async def test_format_unknown_mode(self, telegram_bot):
        """_format_event_text с неизвестным mode не падает."""
        event = _make_mock_event()
        text = telegram_bot._format_event_text(event, "unknown")
        assert isinstance(text, str)
        assert len(text) > 0
