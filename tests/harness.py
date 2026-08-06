"""
Харнесс имитации пользователя в Telegram (Подход A).

Гоняет полный конвейер бота через Dispatcher.feed_update с фейк-сессией,
которая перехватывает исходящие вызовы Telegram API и возвращает
минимальные типизированные объекты — без реального Telegram и без мока
целых хендлеров (фильтры/FSM/диспетчер работают по-настоящему).

Как использовать:
    fake = FakeTelegramSession()
    bot = Bot(token="123456789:TESTTOKEN", session=fake)
    patch("app.platforms.telegram.bot.Bot", lambda token, **kw: bot)
    patch("app.platforms.telegram.bot.async_session_factory", test_session_factory)
    update = make_message_update(user_id=123, text="/start", bot=bot)
    await tb.dp.feed_update(bot, update)
    fake.calls  # все исходящие вызовы
"""
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import (
    Chat,
    ChatMemberAdministrator,
    ChatMemberUpdated,
    Message,
    Update,
    User,
)


class FakeTelegramSession(BaseSession):
    """Перехватывает исходящие вызовы бота, записывает их, возвращает объекты."""

    def __init__(self):
        super().__init__()
        self.calls = []  # список aiogram method-объектов (SendMessage, GetMe, ...)

    @property
    def sent_messages(self) -> list:
        """Отправленные сообщения (SendMessage/EditMessageText/...)."""
        return [c for c in self.calls if c.__class__.__name__ in
                ("SendMessage", "EditMessageText", "SendPhoto", "SendVideo")]

    async def make_request(self, bot, method, timeout=None):
        """Имитирует ответ Telegram API на метод."""
        self.calls.append(method)
        name = method.__class__.__name__

        if name == "GetMe":
            return User(id=123456, is_bot=True, first_name="TestBot", username="testbot")

        if name in (
            "SetMyCommands", "SetChatMenuButton", "SetMyDefaultAdministratorRights",
            "DeleteMyCommands", "AnswerCallbackQuery", "SetMyDescription",
        ):
            return True

        if name == "GetChatMember":
            # _verify_channel_admin смотрит member.status == "administrator"
            return ChatMemberAdministrator(
                user=User(id=123, is_bot=False, first_name="Admin"),
                status="administrator",
                is_anonymous=False,
                can_be_edited=False,
                can_manage_chat=True,
                can_delete_messages=True,
                can_manage_video_chats=True,
                can_restrict_members=True,
                can_promote_members=True,
                can_change_info=True,
                can_invite_users=True,
                can_post_messages=True,
                can_edit_messages=True,
                can_pin_messages=True,
            )

        if name == "GetChatAdministrators":
            # Синхронизация админов канала (subscribe/on_chat_member_update)
            return [
                ChatMemberAdministrator(
                    user=User(id=123, is_bot=False, first_name="Admin"),
                    status="administrator",
                    is_anonymous=False,
                    can_be_edited=False,
                    can_manage_chat=True,
                    can_delete_messages=True,
                    can_manage_video_chats=True,
                    can_restrict_members=True,
                    can_promote_members=True,
                    can_change_info=True,
                    can_invite_users=True,
                    can_post_messages=True,
                    can_edit_messages=True,
                    can_pin_messages=True,
                    can_post_stories=True,
                    can_edit_stories=True,
                    can_delete_stories=True,
                ),
            ]

        if name == "DeleteMessage":
            return True

        if name in (
            "SendMessage", "EditMessageText", "SendPhoto", "SendVideo",
            "SendAnimation", "SendAudio", "SendDocument", "SendVoice",
            "CopyMessage", "SendSticker",
        ):
            chat_id = getattr(method, "chat_id", 1)
            return Message(
                message_id=1,
                date=datetime.now(timezone.utc),
                chat=Chat(id=chat_id, type="private"),
            )

        # Если метод не распознан — честно сообщить, чтобы дополнить харнесс
        returning = getattr(method, "__returning__", None)
        raise NotImplementedError(
            f"FakeTelegramSession не знает метод {name} (returning={returning})"
        )

    # Абстрактные методы BaseSession (не используются в этом пути, но обязательны)
    def check_response(self, bot, method, status_code, content):
        from aiogram.client.session.base import Response
        return Response[method.__returning__].model_validate(
            {"ok": True}, context={"bot": bot},
        )

    def prepare_value(self, value, bot, files, _dumps_json=True):
        return value

    async def stream_content(self, url, headers=None, timeout=30,
                             chunk_size=65536, raise_for_status=True):
        if False:
            yield b""  # pragma: no cover — генератор без yield нельзя

    async def close(self):
        pass


def make_message_update(user_id: int, text: str, bot: Bot, chat_id: int | None = None) -> Update:
    """Построить Update с сообщением от виртуального пользователя."""
    chat_id = chat_id or user_id
    raw = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat": {"id": chat_id, "type": "private", "first_name": "Test"},
            "text": text,
        },
    }
    return Update.model_validate(raw, context={"bot": bot})


def make_callback_update(
    user_id: int,
    callback_data: str,
    bot: Bot,
    chat_type: str = "private",
    message: dict | None = None,
) -> Update:
    """Построить Update с callback_query (нажатие inline-кнопки).

    Args:
        user_id: Telegram ID пользователя (нажавшего).
        callback_data: Строка callback_data (например "buy:<event_id>").
        bot: Бот (для context).
        chat_type: "private" или "channel" — откуда нажата кнопка.
        message: Если нужен конкретный message (для channel-контекста),
                dict вида {"message_id", "chat": {"id", "type", "title"}}.
    """
    if message is None:
        msg = {
            "message_id": 10,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": user_id, "type": chat_type, "first_name": "Test"},
        }
    else:
        msg = message

    raw = {
        "update_id": 2,
        "callback_query": {
            "id": "callback_id_1",
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "data": callback_data,
            "chat_instance": "1234567890",
            "message": msg,
        },
    }
    return Update.model_validate(raw, context={"bot": bot})


def make_channel_post_update(channel_id: int, text: str, bot: Bot) -> Update:
    """Построить Update с channel_post (сообщение в канале)."""
    raw = {
        "update_id": 3,
        "channel_post": {
            "message_id": 5,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": channel_id, "type": "channel", "title": "Test Channel"},
            "text": text,
        },
    }
    return Update.model_validate(raw, context={"bot": bot})


def _admin_member_dict(user: dict, status: str = "administrator") -> dict:
    """Полный ChatMemberAdministrator как dict (для my_chat_member)."""
    base = {
        "user": user,
        "status": status,
        "is_anonymous": False,
        "can_be_edited": False,
        "can_manage_chat": True,
        "can_delete_messages": True,
        "can_manage_video_chats": True,
        "can_restrict_members": True,
        "can_promote_members": True,
        "can_change_info": True,
        "can_invite_users": True,
        "can_post_messages": True,
        "can_edit_messages": True,
        "can_pin_messages": True,
        "can_post_stories": True,
        "can_edit_stories": True,
        "can_delete_stories": True,
    }
    return base


def make_chat_member_update(channel_id: int, bot: Bot, status: str = "administrator") -> Update:
    """Построить Update с my_chat_member (бот добавлен в канал).

    Событие провижининга: бот становится администратором канала.
    """
    raw = {
        "update_id": 4,
        "my_chat_member": {
            "chat": {"id": channel_id, "type": "channel", "title": "Test Channel"},
            "from": {"id": 999, "is_bot": False, "first_name": "Admin"},
            "date": int(datetime.now(timezone.utc).timestamp()),
            "old_chat_member": {
                "user": {"id": 123, "is_bot": True, "first_name": "Bot"},
                "status": "left",
            },
            "new_chat_member": _admin_member_dict(
                {"id": 123, "is_bot": True, "first_name": "Bot"}, status,
            ),
        },
    }
    return Update.model_validate(raw, context={"bot": bot})
