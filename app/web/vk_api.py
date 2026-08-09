"""VK API клиент — публикация анонсов мероприятий в VK-группы.

Использует community token группы (хранится зашифрованным, расшифровывается
через app/core/crypto.py) и метод wall.post (стена группы).

Messages/DM (vk_group_message, vk_user_dm) — требуют прав сообщений сообщества
и диалогов; реализуются отдельно (см. нерешённые вопросы в плане).
"""

import logging

import httpx

from app.core.crypto import decrypt_token

logger = logging.getLogger("ticketbot.web.vk_api")

_API_VERSION = "5.131"


class VKAPIError(Exception):
    """Ошибка VK API."""


async def vk_api_call(method: str, token: str, **params) -> dict:
    """Вызвать метод VK API с access_token."""
    url = f"https://api.vk.com/method/{method}"
    data = {"access_token": token, "v": _API_VERSION, **params}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, data=data)
        payload = resp.json()
    if "error" in payload:
        err = payload["error"]
        raise VKAPIError(
            f"VK API {method} error {err.get('error_code')}: {err.get('error_msg')}"
        )
    return payload.get("response", {})


async def post_to_group_wall(group, text: str) -> bool:
    """Опубликовать анонс на стену VK-группы.

    Returns True on success, False on error (logged, not raised).
    """
    token = decrypt_token(group.community_token or "")
    if not token:
        logger.warning("Нет community token для VK-группы %s", group.group_id)
        return False
    try:
        await vk_api_call(
            "wall.post",
            token,
            owner_id=f"-{group.group_id.lstrip('-')}",
            message=text,
        )
        logger.info("Анонс опубликован в VK-группу %s", group.group_id)
        return True
    except VKAPIError as e:
        logger.error("Ошибка публикации в VK-группу %s: %s", group.group_id, e)
        return False
