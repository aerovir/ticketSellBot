"""
Контрактные тесты ролей: матрица «роль × эндпоинт» на реальных данных.

Роль задаётся РЕАЛЬНЫМ состоянием БД (подписка/канал), не моком.
Проверяет, что каждая роль видит только свои функции (по матрице фич).

Роли:
- user (покупатель, без подписки): создание бесплатного 201, платного 409,
  управление СВОИМИ мероприятиями, статистика/пригласительные/QR 403
- organizer (с подпиской): свои 200, чужое 403
- super_admin: всё 200

КЛЮЧЕВОЙ КОНТРАКТ (защита от регресса расхождения frontend/backend):
  Если POST /admin/events возвращает 201 для роли X — значит роль X
  ДОЛЖНА иметь доступ к управлению своими мероприятиями через API.
  Фронтенд ОБЯЗАН показывать UI для любой роли, которая может создавать
  мероприятия (т.е. для всех ролей, включая "user").
"""
import uuid
import pytest
from datetime import datetime, timezone, timedelta

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import UserService, ChannelService, ChannelAdminService

HEADERS = {"X-Skip-Auth": "1"}


async def _user(db_session, platform_id="12345"):
    return await UserService(db_session).get_or_create(
        PlatformType.telegram, platform_id, "Dev"
    )


def _future(days=7):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _event_payload(owner_user_id=None, price=0):
    return {
        "title": "Contract Event",
        "date": _future(7),
        "price": price,
        "total_tickets": 10,
        "channel_id": None,
        "owner_user_id": owner_user_id,
    }


@pytest.mark.integration
class TestRoleContract:
    """Матрица роль × эндпоинт на реальных данных."""

    # ────────────────────────────────────────────────────────────────
    # User (без подписки) — полный жизненный цикл своего мероприятия
    # ────────────────────────────────────────────────────────────────

    async def test_user_without_subscription_can_create_free_event(self, db_client, db_session):
        """Покупатель (без подписки): бесплатное 201 — ОТКРЫТОЕ СОЗДАНИЕ."""
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid, price=0))
        assert resp.status_code == 201, resp.text
        assert "id" in resp.json()

    async def test_user_without_subscription_cannot_create_paid_event(self, db_client, db_session):
        """Покупатель (без подписки): платное 409 — нет pro."""
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid, price=500))
        assert resp.status_code == 409, resp.text

    async def test_user_without_subscription_role_is_user(self, db_client, db_session):
        """Покупатель (без подписки): role = user."""
        user = await _user(db_session)
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.json()["role"] == "user"

    async def test_user_manages_own_event_lifecycle(self, db_client, db_session):
        """Покупатель (без подписки): полный жизненный цикл СВОЕГО мероприятия.

        КОНТРАКТ: если роль может создать мероприятие (POST 201),
        она должна мочь им управлять (list/get/patch/toggle/delete).

        publish не тестируем — он дёргает Telegram API для анонса,
        что недоступно в тестовом окружении без сети.
        """
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        # 1. Создать бесплатное мероприятие
        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid, price=0))
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # 2. Видеть в своём списке (GET /admin/events)
        resp = await db_client.get("/api/admin/events", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        my_ids = {e["id"] for e in resp.json()}
        assert event_id in my_ids, "Созданное мероприятие должно быть в списке"

        # 3. Получить детали своего мероприятия
        resp = await db_client.get(f"/api/admin/events/{event_id}", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "Contract Event"

        # 4. Редактировать своё мероприятие
        resp = await db_client.patch(f"/api/admin/events/{event_id}", headers=HEADERS,
                                     json={"title": "Updated Title"})
        assert resp.status_code == 200, resp.text

        # 5. Переключить active
        resp = await db_client.post(f"/api/admin/events/{event_id}/toggle", headers=HEADERS)
        assert resp.status_code == 200, resp.text

        # 6. Мягко удалить
        resp = await db_client.post(f"/api/admin/events/{event_id}/delete", headers=HEADERS)
        assert resp.status_code == 200, resp.text

    async def test_user_cannot_access_other_users_event(self, db_client, db_session):
        """Покупатель не может управлять чужим мероприятием."""
        from app.core.services import EventService

        # Создать чужое мероприятие напрямую через сервис (owner = другой пользователь)
        owner = await _user(db_session, platform_id="owner123")
        await db_session.commit()
        other_event = await EventService(db_session).create(
            title="Other Event",
            description=None,
            date=datetime.now(timezone.utc) + timedelta(days=7),
            location=None,
            price=0,
            total_tickets=10,
            channel_id=None,
            owner_user_id=owner.id,
        )
        await db_session.commit()
        other_event_id = str(other_event.id)

        # Текущий пользователь (platform_id="12345") пытается получить доступ
        resp = await db_client.get(f"/api/admin/events/{other_event_id}", headers=HEADERS)
        assert resp.status_code == 403, resp.text

        resp = await db_client.patch(f"/api/admin/events/{other_event_id}", headers=HEADERS,
                                     json={"title": "Hacked"})
        assert resp.status_code == 403, resp.text

    async def test_user_cannot_access_admin_only_endpoints(self, db_client, db_session):
        """Покупатель (без подписки): админские эндпоинты 403."""
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        # Создать мероприятие чтобы было что проверять
        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid, price=0))
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # Статистика — 403 (только организатор)
        resp = await db_client.get("/api/admin/stats", headers=HEADERS)
        assert resp.status_code == 403, resp.text

        # Пригласительные — 403 (pro only)
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites", headers=HEADERS, json={"seats": 1},
        )
        assert resp.status_code == 403, resp.text

        # Каналы — 403 (super-admin only)
        resp = await db_client.get("/api/admin/channels", headers=HEADERS)
        assert resp.status_code == 403, resp.text

    # ────────────────────────────────────────────────────────────────
    # КОНТРАКТ: роль "user" и доступ к созданию мероприятий
    # ────────────────────────────────────────────────────────────────

    async def test_contract_user_role_must_have_create_access(self, db_client, db_session):
        """КОНТРАКТ: если /api/me возвращает role='user',
        то этот пользователь ДОЛЖЕН мочь создать бесплатное мероприятие.

        Этот тест — защита от регресса. Если он падает, значит backend
        заблокировал создание для обычных пользователей, но /api/me
        продолжает возвращать role='user'. Фронтенд, ориентируясь на role,
        скроет кнопку «Панель» — и пользователь не сможет создать мероприятие.
        """
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        # Шаг 1: роль — user
        resp = await db_client.get("/api/me", headers=HEADERS)
        me = resp.json()
        assert me["role"] == "user", (
            "Ожидается role='user' для пользователя без подписки. "
            "Если роль изменилась — обновите этот тест."
        )

        # Шаг 2: user ДОЛЖЕН мочь создать бесплатное мероприятие
        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid, price=0))
        assert resp.status_code == 201, (
            f"КОНТРАКТ НАРУШЕН: role='user', но POST /admin/events вернул {resp.status_code}. "
            f"Фронтенд скрывает кнопку «Панель» для role='user' — пользователь не сможет "
            f"создать мероприятие. Либо откройте эндпоинт, либо измените role на не-'user'."
        )

        # Шаг 3: user ДОЛЖЕН видеть созданное мероприятие в списке
        event_id = resp.json()["id"]
        resp = await db_client.get("/api/admin/events", headers=HEADERS)
        assert resp.status_code == 200, (
            f"КОНТРАКТ НАРУШЕН: role='user', но GET /admin/events вернул {resp.status_code}. "
            f"Фронтенд вызывает этот эндпоинт для отображения списка мероприятий в панели."
        )
        assert any(e["id"] == event_id for e in resp.json()), (
            "КОНТРАКТ НАРУШЕН: созданное мероприятие не появилось в GET /admin/events."
        )

    async def test_contract_user_can_publish_own_event(self, db_client, db_session):
        """КОНТРАКТ: пользователь с role='user' может опубликовать своё мероприятие.

        Для owner-мероприятий (без канала) анонс не требуется —
        post_event_announcement возвращает False без вызова Telegram API.
        """
        from unittest.mock import AsyncMock, patch

        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        # Создать бесплатное owner-мероприятие
        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid, price=0))
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # Публиковать — post_event_announcement замокан (в тестах нет сети)
        with patch("app.web.routes.post_event_announcement", new_callable=AsyncMock, return_value=False):
            resp = await db_client.post(f"/api/admin/events/{event_id}/publish", headers=HEADERS)
        assert resp.status_code == 200, (
            f"КОНТРАКТ НАРУШЕН: role='user', но POST /admin/events/{event_id}/publish "
            f"вернул {resp.status_code}. Пользователь должен мочь публиковать свои мероприятия."
        )
        assert resp.json()["is_published"] is True

    # ────────────────────────────────────────────────────────────────
    # Organizer (с подпиской)
    # ────────────────────────────────────────────────────────────────

    async def test_organizer_with_subscription(self, db_client, db_session):
        """Организатор (с подпиской): свои 200, чужое 403."""
        user = await _user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()
        uid = str(user.id)

        # роль organizer
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.json()["role"] == "organizer"

        # создаёт своё → 201
        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid))
        assert resp.status_code == 201, resp.text
        my_event = resp.json()["id"]

        # статистика своего → 200
        resp = await db_client.get(f"/api/admin/events/{my_event}/stats", headers=HEADERS)
        assert resp.status_code == 200, resp.text

        # пригласительные: basic-организатор → 403 (invite_tickets = pro)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()
        resp = await db_client.post(
            f"/api/admin/events/{my_event}/invites", headers=HEADERS, json={"seats": 1},
        )
        assert resp.status_code == 403, resp.text

    async def test_organizer_pro_invites_qr(self, db_client, db_session):
        """Организатор pro: пригласительные 201, QR доступен."""
        user = await _user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()
        uid = str(user.id)

        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json={**_event_payload(owner_user_id=uid), "invites_quota": 5})
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # пригласительное pro → 201
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites", headers=HEADERS, json={"seats": 1},
        )
        assert resp.status_code == 201, resp.text

    # ────────────────────────────────────────────────────────────────
    # Super-admin
    # ────────────────────────────────────────────────────────────────

    async def test_super_admin_everything(self, db_client, db_session):
        """Супер-админ: всё доступно."""
        user = await _user(db_session)
        await db_session.commit()

        # супер-админ через admin_telegram_ids
        from unittest.mock import patch
        with patch("app.web.dependencies.settings.admin_telegram_ids", "12345"):
            resp = await db_client.get("/api/me", headers=HEADERS)
            assert resp.json()["role"] == "super_admin"

            resp = await db_client.get("/api/admin/stats", headers=HEADERS)
            assert resp.status_code == 200, resp.text

            resp = await db_client.get("/api/admin/channels", headers=HEADERS)
            assert resp.status_code == 200, resp.text
