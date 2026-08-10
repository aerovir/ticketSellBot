"""
VK Mini App аутентификация (#161): проверка подписи launch params.

Алгоритм (официальный VK):
- Параметры с префиксом vk_, кроме sign, сортируются по алфавиту.
- Строка urlencode(key=value) → HMAC-SHA256(секрет) → base64url без padding.
- Сравнение constant-time; vk_app_id совпадает; vk_ts не старше TTL (1 час).
"""

import base64
import time
from urllib.parse import urlencode
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.web.vk_auth import validate_vk_init_data, compute_sign

APP_ID = 123456  # фиктивный app_id (реальный — в GitHub secrets VK_APP_ID)
SECRET = "test_vk_secret_key"


def make_vk_header(
    app_id: int = APP_ID,
    secret: str = SECRET,
    user_id: int = 5305539,
    ts: int | None = None,
    **extra,
) -> str:
    """Сгенерировать base64 Authorization header с валидной подписью."""
    params = {
        "vk_app_id": str(app_id),
        "vk_user_id": str(user_id),
        "vk_ts": str(int(ts or time.time())),
        "vk_ref": "catalog",
        **{k: str(v) for k, v in extra.items()},
    }
    sign = compute_sign(params, secret)
    params["sign"] = sign
    query = urlencode(sorted(params.items()))
    return base64.b64encode(query.encode()).decode()


@pytest.fixture
def vk_settings():
    with (
        patch("app.web.vk_auth.settings.vk_app_id", APP_ID),
        patch("app.web.vk_auth.settings.vk_secret_key", SECRET),
    ):
        yield


class TestVKAuth:
    def test_valid_launch_params(self, vk_settings):
        data = validate_vk_init_data(make_vk_header(user_id=5305539))
        assert data["platform"] == "vk"
        assert data["user"]["id"] == 5305539

    def test_invalid_sign_rejected(self, vk_settings):
        header = make_vk_header(user_id=5305539)
        # Искажаем подпись
        tampered = header[:-4] + "AAAA"
        with pytest.raises(HTTPException) as e:
            validate_vk_init_data(tampered)
        assert e.value.status_code == 401

    def test_wrong_secret_rejected(self, vk_settings):
        header = make_vk_header(secret="another_secret")
        with pytest.raises(HTTPException) as e:
            validate_vk_init_data(header)
        assert e.value.status_code == 401

    def test_wrong_app_id_rejected(self, vk_settings):
        header = make_vk_header(app_id=99999)
        with pytest.raises(HTTPException) as e:
            validate_vk_init_data(header)
        assert e.value.status_code == 401

    def test_expired_rejected(self, vk_settings):
        header = make_vk_header(ts=time.time() - 2 * 3600)  # 2 часа назад
        with pytest.raises(HTTPException) as e:
            validate_vk_init_data(header)
        assert e.value.status_code == 401

    def test_missing_sign_rejected(self, vk_settings):
        params = {
            "vk_app_id": str(APP_ID),
            "vk_user_id": "1",
            "vk_ts": str(int(time.time())),
        }
        query = urlencode(params)
        header = base64.b64encode(query.encode()).decode()
        with pytest.raises(HTTPException) as e:
            validate_vk_init_data(header)
        assert e.value.status_code == 401

    def test_missing_header_rejected(self, vk_settings):
        with pytest.raises(HTTPException) as e:
            validate_vk_init_data(None)
        assert e.value.status_code == 401

    def test_secret_not_configured_returns_500(self):
        with (
            patch("app.web.vk_auth.settings.vk_app_id", None),
            patch("app.web.vk_auth.settings.vk_secret_key", None),
        ):
            with pytest.raises(HTTPException) as e:
                validate_vk_init_data(make_vk_header())
            assert e.value.status_code == 500
