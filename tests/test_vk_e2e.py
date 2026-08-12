"""
Полный контур VK (#166): сквозной сценарий организатора через web.

Киллер-фича: одно мероприятие на всех площадках.
Сценарий:
1. Организатор (канон) в TG: подписка + код привязки.
2. VK-пользователь вводит код → вход по VK ведёт на канон организатора.
3. Организатор добавляет VK-группу (self-service, token шифруется).
4. Создаёт мероприятие (owner) + соработника (менеджера).
5. Публикует анонс в VK-группу (стена) — запись event_publications.
6. Покупатель (VK, отдельный аккаунт) покупает билет.
7. Организатор проверяет билет по коду (проверил в TG, куплено в VK) —
   киллер-фича: check-in по коду работает с любой площадки.
"""

import uuid
import base64
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from cryptography.fernet import Fernet

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import UserService, EventService, VKGroupService, TicketService

TEST_KEY = Fernet.generate_key().decode()


def _vk_auth_header(user_id=5305539, app_id=123456, secret="test_vk_secret_key"):
    """Валидный X-VK-Init-Data (launch params + подпись) для аутентификации VK-покупателя."""
    from app.web.vk_auth import compute_sign

    params = {
        "vk_app_id": str(app_id),
        "vk_user_id": str(user_id),
        "vk_ts": str(int(time.time())),
        "vk_ref": "catalog",
    }
    sign = compute_sign(params, secret)
    params["sign"] = sign
    query = urlencode(sorted(params.items()))
    return base64.b64encode(query.encode()).decode()


async def test_full_vk_organizer_cycle(db_client, db_session):
    user_svc = UserService(db_session)
    event_svc = EventService(db_session)
    group_svc = VKGroupService(db_session)
    ticket_svc = TicketService(db_session)

    # ── 1. Организатор (канон 12345 — совпадает с X-Skip-Auth) ──
    org = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Организатор")
    await user_svc.activate_subscription(org.id, days=30, tier=SubscriptionTier.pro)
    code = await user_svc.create_link_code(org.id, PlatformType.vk, ttl_minutes=10)

    # ── 2. VK-пользователь привязывается → канон организатора ──
    await user_svc.consume_link_code(code, PlatformType.vk, "vk_buyer_uid", current_user_id=None)
    # Покупатель (другой VK-пользователь, не привязан) — раздельный аккаунт.
    # Числовой VK ID, чтобы аутентифицироваться как покупатель через launch params (X-VK-Init-Data).
    buyer = await user_svc.get_or_create(PlatformType.vk, "7777777", name="Покупатель VK")
    assert buyer.id != org.id

    # ── 3. VK-группа (self-service, token шифруется) ──
    with patch("app.config.settings.vk_token_encryption_key", TEST_KEY):
        group = await group_svc.register_vk_group(
            org.id, "100500", title="Группа продаж", community_token="vk-secret",
        )

    # ── 4. Мероприятие (owner) + соработник ──
    event = await event_svc.create(
        title="Событие VK",
        description="Анонс во все площадки",
        date=datetime.now(timezone.utc) + timedelta(days=7),
        location="Москва",
        price=0,
        total_tickets=20,
        channel_id=None,
        owner_user_id=org.id,
    )
    event.is_published = True
    mgr = await user_svc.get_or_create(PlatformType.telegram, "vk_mgr", name="Менеджер")
    await event_svc.add_manager(event.id, mgr.id)
    await db_session.commit()

    # ── 5. Публикация в VK-группу (стена) через web ──
    with patch("app.web.routes.post_to_group_wall", new_callable=AsyncMock, return_value=True):
        resp = await db_client.post(
            f"/api/admin/events/{event.id}/publish",
            headers={"X-Skip-Auth": "1"},
            json={"vk_group_id": group.group_id},
        )
        assert resp.status_code == 200
        assert resp.json()["announced"] is True

    resp = await db_client.get(
        f"/api/admin/events/{event.id}/publications", headers={"X-Skip-Auth": "1"},
    )
    pubs = resp.json()["publications"]
    assert any(p["target_type"] == "vk_group_wall" and p["status"] == "posted" for p in pubs)

    # ── 6. Покупатель из VK покупает билет ──
    ticket = await ticket_svc.buy_ticket(buyer.id, event.id)
    assert ticket.validation_code is not None
    await db_session.commit()

    # ── 6b. F1: билет в ЛС VK — POST /tickets/{id}/send-vk.
    #        Реальная VK-группа (шаг 3) + реальная принадлежность билета.
    #        Отправка в VK (messages.send) замокана — сети в тесте нет. ──
    vk_header = _vk_auth_header(user_id=7777777)
    with (
        patch("app.web.vk_auth.settings.vk_app_id", 123456),
        patch("app.web.vk_auth.settings.vk_secret_key", "test_vk_secret_key"),
        patch("app.web.routes.send_vk_ticket_dm", new_callable=AsyncMock, return_value=True),
    ):
        resp = await db_client.post(
            f"/api/tickets/{ticket.id}/send-vk",
            headers={"X-VK-Init-Data": vk_header},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] is True, resp.json()
    assert resp.json()["group_id"] == group.group_id, resp.json()

    # ── 7. Статистика учитывает проданный билет (куплен в VK) ──
    resp = await db_client.get(f"/api/admin/events/{event.id}/stats", headers={"X-Skip-Auth": "1"})
    assert resp.status_code == 200
    assert resp.json()["sold"] == 1

    # ── 8. Киллер-фича: проверка билета по коду (TG/web), купленного в VK ──
    resp = await db_client.get(
        f"/api/admin/tickets/validate?code={ticket.validation_code}",
        headers={"X-Skip-Auth": "1"},
    )
    assert resp.status_code == 200
    info = resp.json()
    assert info["found"] is True
    assert info["status"] == "active"

    # Отметить вход (owner из TG/web) — билет учтён как использованный
    resp = await db_client.post(
        "/api/admin/tickets/checkin",
        headers={"X-Skip-Auth": "1"},
        json={"code": ticket.validation_code},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "checked_in"


async def test_vk_identity_resolves_canon(db_session):
    """Вход по VK после линковки возвращает канонического организатора."""
    user_svc = UserService(db_session)
    org = await user_svc.get_or_create(PlatformType.telegram, "canon_org", name="Канон")
    code = await user_svc.create_link_code(org.id, PlatformType.vk, ttl_minutes=10)
    await user_svc.consume_link_code(code, PlatformType.vk, "vk_identity_uid", current_user_id=None)

    vk_user = await user_svc.get_or_create(PlatformType.vk, "vk_identity_uid", name="X")
    assert vk_user.id == org.id
    assert vk_user.name == "Канон"
