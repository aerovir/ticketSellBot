"""VK Mini App аутентификация — проверка подписи launch params.

Launch params приходят от VK Mini App в Authorization header как
base64-URL-закодированная query string:
    vk_user_id=...&vk_app_id=...&vk_ts=...&sign=...&vk_ref=...

Алгоритм проверки (официальный VK, совпадает с vk-mini-app-auth):
1. Взять все параметры с префиксом `vk_`, кроме `sign`.
2. Отсортировать ключи по алфавиту.
3. Собрать строку urlencode(key=value).
4. HMAC-SHA256(secret, строка) → base64url без padding.
5. Сравнить с `sign` (constant-time).
Дополнительно: vk_app_id == конфиг, vk_ts не старше TTL (1 час).

Возвращает dict с ключом 'platform'='vk' — совместим с get_current_user.
"""

import base64
import binascii
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import HTTPException, status

from app.config import settings

# Максимальный возраст launch params (1 час, как в официальной либе).
_TTL = timedelta(hours=1)


class VKAuthError(Exception):
    """Ошибка валидации VK launch params."""


def decode_launch_params(authorization_header: str) -> dict:
    """Декодировать base64 launch params из Authorization header → dict."""
    if not authorization_header:
        raise VKAuthError("Missing VK launch params")
    header = authorization_header.strip()
    try:
        padding = "=" * (-len(header) % 4)
        url = base64.b64decode(header + padding, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        raise VKAuthError("Invalid VK launch params format") from e
    # Launch params передаются как query string (возможно в виде полного URL).
    # Устойчиво к обоим форматам: "vk_app_id=...&..." и "https://host/?vk_app_id=...".
    parsed = urlparse(url)
    query_string = parsed.query if parsed.query else (url if "=" in url else "")
    params = parse_qs(query_string, keep_blank_values=True)
    return {k: v[0] if isinstance(v, list) else "" for k, v in params.items()}


def compute_sign(params: dict, secret: str) -> str:
    """Вычислить подпись launch params (для тестов и проверки)."""
    vk_params = {k: v for k, v in params.items() if k.startswith("vk_")}
    vk_params.pop("sign", None)
    sign_params_query = urlencode(dict(sorted(vk_params.items())))
    digest = hmac.new(secret.encode(), sign_params_query.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _parse_vk_ts(vk_ts: str) -> datetime:
    try:
        ts = int(vk_ts)
    except (TypeError, ValueError):
        raise VKAuthError("Invalid vk_ts")
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def validate_vk_init_data(x_vk_init_data: str | None) -> dict:
    """Проверить launch params VK Mini App.

    Returns dict {'user': {'id': vk_user_id}, 'platform': 'vk'}.
    Raises HTTPException 401 on invalid/expired/missing params.
    """
    if not x_vk_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing VK launch params",
        )

    app_id = settings.vk_app_id
    secret = settings.vk_secret_key
    if not app_id or not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="VK App ID / secret key not configured",
        )

    try:
        params = decode_launch_params(x_vk_init_data)
    except VKAuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    if "sign" not in params or "vk_user_id" not in params:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing sign or vk_user_id in VK launch params",
        )

    # app_id
    try:
        if int(params.get("vk_app_id", "0")) != app_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid VK app ID")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid VK app ID")

    # TTL
    vk_ts = params.get("vk_ts", "")
    try:
        if datetime.now(timezone.utc) - _parse_vk_ts(vk_ts) > _TTL:
            raise VKAuthError("VK launch params expired")
    except VKAuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    # Подпись
    try:
        expected = compute_sign(params, secret)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid VK signature")
    if not hmac.compare_digest(expected, params["sign"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid VK signature")

    try:
        vk_user_id = int(params["vk_user_id"])
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid vk_user_id")

    return {
        "user": {"id": vk_user_id, "first_name": None},
        "platform": "vk",
        "vk_app_id": app_id,
    }
