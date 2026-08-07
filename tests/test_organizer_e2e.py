"""
Сквозные (end-to-end) сценарии роли «Организатор» + подписка на пользователя.

Реальная БД через db_client (httpx.ASGITransport на тестовой БД), как TestCabinetFlow.
Никакие сервисы НЕ мокаются — проверяется реальная логика owner/channel.

Юзер 12345 (X-Skip-Auth) — организатор через реальную подписку пользователя
(UserService.activate_subscription), а не через патч dependency.
"""

import pytest
from datetime import datetime, timezone, timedelta

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import UserService, ChannelService, ChannelAdminService

HEADERS = {"X-Skip-Auth": "1"}


def _future(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def _organizer_user(db_session):
    """Реальная запись юзера 12345 (X-Skip-Auth) в БД."""
    return await UserService(db_session).get_or_create(
        PlatformType.telegram, "12345", "Dev"
    )


def _event_payload(owner_user_id=None, channel_id=None, price=0, total=50):
    return {
        "title": "E2E Org Event",
        "date": _future(7),
        "price": price,
        "total_tickets": total,
        "channel_id": channel_id,
        "owner_user_id": owner_user_id,
    }


@pytest.mark.integration
class TestOrganizerE2E:
    """Сквозные сценарии организатора (реальная БД)."""

    async def test_organizer_without_channel_full_flow(self, db_client, db_session):
        """Организатор БЕЗ канала (подписка пользователя): create → list → buy → stats."""
        user = await _organizer_user(db_session)
        await db_session.commit()

        # ── Фаза «покупатель» (без подписки, без канала): 403 + role=user ──
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "user"

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id)),
        )
        assert resp.status_code == 403, resp.text

        # ── Активируем реальную подписку пользователя ──
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        # role=organizer
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "organizer", resp.json()

        # create → 201 (owner_user_id = свой)
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id)),
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # list → виден по owner
        resp = await db_client.get("/api/admin/events", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        mine = [e for e in resp.json() if e["id"] == event_id]
        assert len(mine) == 1, resp.json()
        assert mine[0]["owner_user_id"] == str(user.id)
        assert mine[0]["channel_id"] is None

        # детали события → доступ владельцу
        resp = await db_client.get(f"/api/admin/events/{event_id}", headers=HEADERS)
        assert resp.status_code == 200, resp.text

        # buy → 201 (организатор покупает билет на своё мероприятие)
        resp = await db_client.post(f"/api/events/{event_id}/buy", headers=HEADERS)
        assert resp.status_code == 201, resp.text

        # stats → 200 (это и есть цель сквозного сценария)
        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        assert resp.status_code == 200, (
            f"stats status={resp.status_code} body={resp.text}"
        )
        assert resp.json()["sold"] == 1

    async def test_owner_event_admin_actions_scope(self, db_client, db_session):
        """Организатор без канала: admin-действия над owner-событием (карта доступов)."""
        user = await _organizer_user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id)),
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # Каждое действие: ожидаем 200 (организатор = владелец события)
        checks = []

        r = await db_client.get(f"/api/admin/events/{event_id}", headers=HEADERS)
        checks.append(("GET /admin/events/{id}", r.status_code, r.text[:80]))

        r = await db_client.get(f"/api/admin/events/{event_id}/tickets", headers=HEADERS)
        checks.append(("GET /admin/events/{id}/tickets", r.status_code, r.text[:80]))

        r = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        checks.append(("GET /admin/events/{id}/stats", r.status_code, r.text[:80]))

        r = await db_client.post(f"/api/admin/events/{event_id}/toggle", headers=HEADERS)
        checks.append(("POST /admin/events/{id}/toggle", r.status_code, r.text[:80]))

        r = await db_client.patch(
            f"/api/admin/events/{event_id}", headers=HEADERS, json={"title": "Renamed"},
        )
        checks.append(("PATCH /admin/events/{id}", r.status_code, r.text[:80]))

        r = await db_client.post(f"/api/admin/events/{event_id}/delete", headers=HEADERS)
        checks.append(("POST /admin/events/{id}/delete", r.status_code, r.text[:80]))

        failed = [c for c in checks if c[1] != 200]
        assert not failed, f"Owner-событие недоступно организатору: {failed}"

    async def test_organizer_with_channel_regression(self, db_client, db_session):
        """Организатор С каналом: create через channel_id → 201 + stats (регресс)."""
        await _organizer_user(db_session)

        channel_svc = ChannelService(db_session)
        channel = await channel_svc.create(
            telegram_channel_id="e2e_channel_1",
            admin_telegram_user_id="12345",
            title="E2E Channel",
        )
        await channel_svc.activate_subscription(
            channel.id, duration_days=365, tier=SubscriptionTier.pro,
        )
        await ChannelAdminService(db_session).sync_admins(channel.id, ["12345"])
        await db_session.commit()

        # role organizer по каналу
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "organizer", resp.json()

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(channel_id=str(channel.id), price=1000, total=100),
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        resp = await db_client.get(f"/api/admin/events/{event_id}", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert resp.json()["channel_id"] == str(channel.id)

        # buy + stats (канальный путь)
        resp = await db_client.post(f"/api/events/{event_id}/buy", headers=HEADERS)
        assert resp.status_code == 201, resp.text

        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert resp.json()["sold"] == 1

    async def test_event_no_channel_no_owner_400(self, db_client, db_session):
        """Мероприятие без channel и без owner → 400."""
        user = await _organizer_user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=None, channel_id=None),
        )
        assert resp.status_code == 400, resp.text

    async def test_me_role_organizer_vs_user(self, db_client, db_session):
        """GET /api/me: role=organizer при подписке пользователя, role=user без."""
        user = await _organizer_user(db_session)
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(user.id)
        assert resp.json()["role"] == "user"

        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "organizer"

    async def test_owner_cannot_create_for_other_user(self, db_client, db_session):
        """owner_user_id ≠ current.user_id → 403 (нельзя создать от чужого имени)."""
        user = await _organizer_user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        # Другой пользователь (владелец-«жертва»)
        other = await UserService(db_session).get_or_create(
            PlatformType.telegram, "99999", "Other",
        )
        await db_session.commit()

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(other.id)),
        )
        assert resp.status_code == 403, resp.text
