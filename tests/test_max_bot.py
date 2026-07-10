"""
Тесты MAX Bot хендлеров.

MAX — заглушка. Тесты проверяют базовую маршрутизацию команд.
MAX SDK (max-bot-api-client-py) мокается, так как может быть не установлен.
"""

import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.fixture
def mock_message():
    """Создаёт mock MAX сообщения."""
    msg = AsyncMock()
    msg.chat.id = "chat_123"
    msg.from_user.id = "user_123"
    msg.from_user.name = "Test User"
    msg.text = ""
    return msg


@pytest.fixture
def max_bot():
    """Создаёт MaxPlatformBot с замоканным SDK.

    MaxBot.on.command() используется как декоратор. Мокаем его
    на no-op lambda, чтобы хендлеры регистрировались без ошибок.
    """
    with (
        patch("app.platforms.max.bot.settings.max_token", "test_token"),
        patch("app.platforms.max.bot.MAX_AVAILABLE", True),
        patch("app.platforms.max.bot.MaxBot", create=True) as mock_bot_cls,
    ):
        mock_bot = AsyncMock()
        # on.command() используется как декоратор
        mock_bot.on = Mock()
        mock_bot.on.command = Mock(return_value=lambda f: f)
        mock_bot.send_message = AsyncMock()
        mock_bot_cls.return_value = mock_bot

        from app.platforms.max.bot import MaxPlatformBot

        return MaxPlatformBot()


class TestMaxCommands:
    async def test_cmd_start(self, max_bot, mock_message):
        """Команда start (без слэша для MAX)."""
        with patch(
            "app.platforms.max.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            await max_bot.cmd_start(mock_message)

        max_bot.bot.send_message.assert_awaited_once()
        text = max_bot.bot.send_message.call_args[1]["text"]
        assert "TicketBot" in text

    async def test_cmd_events_empty(self, max_bot, mock_message):
        """Команда events без мероприятий."""
        with patch(
            "app.platforms.max.bot.EventService.list_upcoming",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await max_bot.cmd_events(mock_message)

        max_bot.bot.send_message.assert_awaited_once()
        text = max_bot.bot.send_message.call_args[1]["text"]
        assert "Нет предстоящих" in text

    async def test_cmd_event_no_id(self, max_bot, mock_message):
        """Команда event без ID."""
        mock_message.text = "/event"
        await max_bot.cmd_event(mock_message)

        max_bot.bot.send_message.assert_awaited_once()
        text = max_bot.bot.send_message.call_args[1]["text"]
        assert "Укажите ID" in text

    async def test_cmd_event_invalid_id(self, max_bot, mock_message):
        """Команда event с неверным ID."""
        mock_message.text = "/event not-a-uuid"
        await max_bot.cmd_event(mock_message)

        max_bot.bot.send_message.assert_awaited_once_with(
            chat_id="chat_123",
            text="Неверный ID мероприятия.",
        )

    async def test_cmd_buy_no_id(self, max_bot, mock_message):
        """Команда buy без ID."""
        mock_message.text = "/buy"
        with patch(
            "app.platforms.max.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            await max_bot.cmd_buy(mock_message)

        max_bot.bot.send_message.assert_awaited_once()
        text = max_bot.bot.send_message.call_args[1]["text"]
        assert "Укажите ID" in text

    async def test_cmd_my_tickets_empty(self, max_bot, mock_message):
        """Команда my_tickets без билетов."""
        with patch(
            "app.platforms.max.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            with patch(
                "app.platforms.max.bot.TicketService.get_user_tickets",
                new_callable=AsyncMock,
                return_value=[],
            ):
                await max_bot.cmd_my_tickets(mock_message)

        max_bot.bot.send_message.assert_awaited_once()
        text = max_bot.bot.send_message.call_args[1]["text"]
        assert "У вас нет билетов" in text

    async def test_cmd_cancel_no_id(self, max_bot, mock_message):
        """Команда cancel без ID."""
        mock_message.text = "/cancel"
        await max_bot.cmd_cancel(mock_message)

        max_bot.bot.send_message.assert_awaited_once()
        text = max_bot.bot.send_message.call_args[1]["text"]
        assert "Укажите ID билета" in text
