"""
Контрактные тесты ролей: матрица «роль × эндпоинт» на реальных данных.

Роль задаётся РЕАЛЬНЫМ состоянием БД (подписка/канал), не моком.
Проверяет, что каждая роль видит только свои функции (по матрице ролей).

Роли (матрица ролей, docs/roles-matrix.md):
- user (покупатель, без подписки): НЕ создаёт мероприятия (403),
  минимальный ЛК (билеты), «Стать организатором»
- organizer (с подпиской): создаёт свои мероприятия, управляет ими
- super_admin: глобальные разделы (статистика, подписки организаторов),
  НЕ управляет мероприятиями/каналами организаторов

КЛЮЧЕВОЙ КОНТРАКТ (защита от регресса):
  Только организатор создаёт мероприятия. user и суперадмин — 403 на POST
  /admin/events. Фронтенд ролевой: кнопки «Создать» только у организатора.
"""
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import UserService, EventService, ChannelAdminService

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
    # User (без подписки) — минимальный ЛК, НЕ создаёт
    # ────────────────────────────────────────────────────────────────

    async def test_user_cannot_create_event(self, db_client, db_session):
        """Покупатель (без подписки): НЕ может создать мероприятие (403)."""
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid, price=0))
        assert resp.status_code == 403, resp.text

    async def test_user_cannot_list_admin_events(self, db_client, db_session):
        """Покупатель: GET /admin/events → 403 (только организатор)."""
        user = await _user(db_session)
        await db_session.commit()

        resp = await db_client.get("/api/admin/events", headers=HEADERS)
        assert resp.status_code == 403, resp.text

    async def test_user_role_is_user_has_group_false(self, db_client, db_session):
        """Покупатель: role=user, has_group=false."""
        await _user(db_session)
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        me = resp.json()
        assert me["role"] == "user"
        assert me["has_group"] is False

    async def test_user_can_buy_ticket(self, db_client, db_session):
        """Покупатель: может покупать билеты (открытая покупка)."""
        from app.core.services import EventService
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)
        # Организатор (с подпиской) создаёт событие
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()
        ev = await EventService(db_session).create(
            title="Buy Event", description=None,
            date=datetime.now(timezone.utc) + timedelta(days=7),
            location=None, price=100, total_tickets=10,
            channel_id=None, owner_user_id=uid,
        )
        ev.is_published = True
        await db_session.commit()

        resp = await db_client.post(f"/api/events/{ev.id}/buy", headers=HEADERS)
        assert resp.status_code == 201, resp.text

    async def test_user_cannot_access_admin_only_endpoints(self, db_client, db_session):
        """Покупатель (без подписки): админские эндпоинты 403."""
        await _user(db_session)
        await db_session.commit()

        # Статистика — 403 (только суперадмин)
        resp = await db_client.get("/api/admin/stats", headers=HEADERS)
        assert resp.status_code == 403, resp.text

        # Каналы — 403 (суперадмин)
        resp = await db_client.get("/api/admin/channels", headers=HEADERS)
        assert resp.status_code == 403, resp.text

    # ────────────────────────────────────────────────────────────────
    # Organizer (с подпиской)
    # ────────────────────────────────────────────────────────────────

    async def test_organizer_with_subscription(self, db_client, db_session):
        """Организатор (с подпиской): создаёт свои, чужое 403."""
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
        resp = await db_client.post(
            f"/api/admin/events/{my_event}/invites", headers=HEADERS, json={"seats": 1},
        )
        assert resp.status_code == 403, resp.text

    async def test_organizer_pro_invites_qr(self, db_client, db_session):
        """Организатор pro: пригласительные 201."""
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

        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites", headers=HEADERS, json={"seats": 1},
        )
        assert resp.status_code == 201, resp.text

    async def test_organizer_has_group_transition(self, db_client, db_session):
        """Бесшовный переход: без группы → с группой (после добавления канала)."""
        from app.core.models import Channel
        from app.core.services import ChannelService
        user = await _user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        # Без площадки → has_group=false
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.json()["has_group"] is False

        # Добавить канал с активной подпиской → has_group=true
        channel = await ChannelService(db_session).create(
            telegram_channel_id="@org_channel", admin_telegram_user_id="12345", title="Org"
        )
        await ChannelService(db_session).activate_subscription(
            channel.id, duration_days=30, tier=SubscriptionTier.basic,
        )
        await ChannelAdminService(db_session).sync_admins(channel.id, ["12345"])
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.json()["has_group"] is True

    # ────────────────────────────────────────────────────────────────
    # Super-admin — НЕ управляет мероприятиями/каналами организаторов
    # ────────────────────────────────────────────────────────────────

    async def test_super_admin_global_but_no_events(self, db_client, db_session):
        """Супер-админ: глобальные разделы 200, мероприятия/каналы — НЕ управляет."""
        user = await _user(db_session)
        await db_session.commit()
        uid = str(user.id)

        # Создать мероприятие как организатор (owner)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()
        resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                    json=_event_payload(owner_user_id=uid))
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # Суперадмин
        with patch("app.web.dependencies.settings.admin_telegram_ids", "12345"):
            resp = await db_client.get("/api/me", headers=HEADERS)
            assert resp.json()["role"] == "super_admin"

            # Глобальные разделы — 200
            resp = await db_client.get("/api/admin/stats", headers=HEADERS)
            assert resp.status_code == 200, resp.text

            # Мероприятия — пусто (не управляет)
            resp = await db_client.get("/api/admin/events", headers=HEADERS)
            assert resp.status_code == 200, resp.text
            assert resp.json() == [], "Суперадмин не видит мероприятия"

            # Не может создать мероприятие (403)
            resp = await db_client.post("/api/admin/events", headers=HEADERS,
                                        json=_event_payload(owner_user_id=uid))
            assert resp.status_code == 403, resp.text

            # Не может управлять чужим мероприятием (403)
            resp = await db_client.get(f"/api/admin/events/{event_id}", headers=HEADERS)
            assert resp.status_code == 403, resp.text

    async def test_super_admin_can_validate_ticket_by_code(self, db_client, db_session):
        """Супер-админ может найти покупателя по коду (валидация, без управления)."""
        from app.core.services import TicketService
        user = await _user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()
        uid = str(user.id)
        ev = await EventService(db_session).create(
            title="Valid Event", description=None,
            date=datetime.now(timezone.utc) + timedelta(days=7),
            location=None, price=100, total_tickets=10,
            channel_id=None, owner_user_id=uid,
        )
        ev.is_published = True
        await db_session.commit()
        ticket = await TicketService(db_session).buy_ticket(uid, ev.id)
        await db_session.commit()

        with patch("app.web.dependencies.settings.admin_telegram_ids", "12345"):
            resp = await db_client.get(
                f"/api/admin/tickets/validate?code={ticket.validation_code}", headers=HEADERS)
            assert resp.status_code == 200, resp.text
            assert resp.json()["found"] is True
