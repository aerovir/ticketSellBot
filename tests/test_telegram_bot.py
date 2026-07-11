"""
Тесты Telegram Bot хендлеров.

Используем mock для aiogram, тестируем логику ответов на команды.
"""

import uuid
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

        with patch(
            "app.platforms.telegram.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            await telegram_bot.cmd_start(mock_message)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.call_args[0][0]
        assert "TicketBot" in text
        assert "/events" in text
        assert "/buy" in text

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
        assert "Укажите ID" in mock_message.answer.call_args[0][0]

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
        assert "Укажите ID" in mock_message.answer.call_args[0][0]

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
        assert "Укажите ID билета" in mock_message.answer.call_args[0][0]


# ═══════════════════════════════════════════════════════════════
# Admin commands
# ═══════════════════════════════════════════════════════════════

class TestAdminCommands:
    async def test_admin_menu_unauthorized(self, telegram_bot, mock_message):
        """Обычный пользователь не может открыть админку."""
        mock_message.from_user.id = 99999  # не админ
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

    async def test_admin_create_event_unauthorized(self, telegram_bot, mock_message):
        """Обычный пользователь не может создать мероприятие."""
        mock_message.from_user.id = 99999
        mock_state = AsyncMock()

        await telegram_bot.admin_create_event(mock_message, mock_state)

        mock_message.answer.assert_awaited_once_with(
            "У вас нет доступа к панели администратора."
        )

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
        assert "Укажите ID" in mock_message.answer.call_args[0][0]

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
        assert "Укажите ID" in mock_message.answer.call_args[0][0]

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
        assert "Укажите ID" in mock_message.answer.call_args[0][0]


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
        assert "Укажите ID" in mock_message.answer.call_args[0][0]


# ═══════════════════════════════════════════════════════════════
# Callback handlers
# ═══════════════════════════════════════════════════════════════

class TestCallbackHandlers:
    async def test_callback_buy_ticket(self, telegram_bot, mock_callback):
        """Callback покупки билета."""
        event_id = uuid.uuid4()
        mock_callback.data = f"buy:{event_id}"

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
            await telegram_bot.cmd_callback(mock_callback, Mock())

        mock_callback.answer.assert_awaited_once()

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
        with patch(
            "app.platforms.telegram.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            await telegram_bot.cmd_start(mock_message)

        mock_message.answer.assert_awaited_once()
        assert "TicketBot" in mock_message.answer.call_args[0][0]
