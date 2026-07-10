"""
Тесты VK Bot хендлеров.

Используем mock для vkbottle, тестируем логику ответов на команды.
"""

import uuid
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest


@pytest.fixture
def mock_message():
    """Создаёт mock VK сообщения."""
    msg = AsyncMock()
    msg.from_id = 12345
    msg.text = ""
    msg.answer = AsyncMock()
    msg.sender = Mock(first_name="Test", last_name="User")
    return msg


@pytest.fixture
def vk_bot():
    """Создаёт VKPlatformBot с захардкоженным токеном.

    VKBot.on — это labeler, у которого message() возвращает
    декоратор, регистрирующий хендлер. В тестах подменяем
    его на no-op lambda, чтобы хендлеры регистрировались без ошибок.
    """
    with (
        patch("app.platforms.vk.bot.settings.vk_token", "test_token"),
        patch("app.platforms.vk.bot.settings.vk_group_id", "123"),
        patch("app.platforms.vk.bot.VKBot") as mock_bot_cls,
    ):
        mock_bot = AsyncMock()
        # on.message() используется как декоратор: @bot.on.message(text="...")
        # должен возвращать callable, который принимает функцию и возвращает её
        mock_bot.on = Mock()
        mock_bot.on.message = Mock(return_value=lambda f: f)
        mock_bot_cls.return_value = mock_bot

        from app.platforms.vk.bot import VKPlatformBot

        return VKPlatformBot()


class TestVKCommands:
    async def test_cmd_start(self, vk_bot, mock_message):
        """Команда /start возвращает приветствие."""
        mock_message.text = "/start"

        with patch(
            "app.platforms.vk.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            await vk_bot.cmd_start(mock_message)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.call_args[0][0]
        assert "TicketBot" in text

    async def test_cmd_events_empty(self, vk_bot, mock_message):
        """Команда /events без мероприятий."""
        with patch(
            "app.platforms.vk.bot.EventService.list_upcoming",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await vk_bot.cmd_events(mock_message)

        mock_message.answer.assert_awaited_once_with(
            "😔 Нет предстоящих мероприятий."
        )

    async def test_cmd_event_invalid_id(self, vk_bot, mock_message):
        """Команда /event с неверным ID."""
        await vk_bot.cmd_event(mock_message, "not-a-uuid")

        mock_message.answer.assert_awaited_once_with(
            "Неверный ID мероприятия."
        )

    async def test_cmd_buy_invalid_id(self, vk_bot, mock_message):
        """Команда /buy с неверным ID."""
        await vk_bot.cmd_buy(mock_message, "not-a-uuid")

        mock_message.answer.assert_awaited_once_with(
            "Неверный ID мероприятия."
        )

    async def test_cmd_my_tickets_empty(self, vk_bot, mock_message):
        """Команда /my_tickets без билетов."""
        with patch(
            "app.platforms.vk.bot.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=Mock(id=uuid.uuid4()),
        ):
            with patch(
                "app.platforms.vk.bot.TicketService.get_user_tickets",
                new_callable=AsyncMock,
                return_value=[],
            ):
                await vk_bot.cmd_my_tickets(mock_message)

        mock_message.answer.assert_awaited_once_with(
            "У вас нет билетов."
        )

    async def test_cmd_cancel(self, vk_bot, mock_message):
        """Команда /cancel с неверным ID."""
        await vk_bot.cmd_cancel(mock_message, "not-a-uuid")

        mock_message.answer.assert_awaited_once_with(
            "Неверный ID билета."
        )
