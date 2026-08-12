"""
Сквозные (end-to-end) сценарии роли «Организатор» + подписка на пользователя.

Реальная БД через db_client (httpx.ASGITransport на тестовой БД), как TestCabinetFlow.
Никакие сервисы НЕ мокаются — проверяется реальная логика owner/channel.

Юзер 12345 (X-Skip-Auth) — организатор через реальную подписку пользователя
(UserService.activate_subscription), а не через патч dependency.
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.core.models import PlatformType, SubscriptionTier, Event
from app.core.services import (
    UserService,
    ChannelService,
    ChannelAdminService,
    TicketService,
)

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

        # ── Фаза «покупатель» (без подписки, без канала): создание ОТКРЫТО, role=user ──
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "user"

        # Создание бесплатного открыто даже без подписки (201)
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id)),
        )
        assert resp.status_code == 201, resp.text

        # ── Активируем подписку пользователя через РЕАЛЬНЫЙ API (покупка) ──
        resp = await db_client.post(
            "/api/me/subscription",
            headers=HEADERS,
            json={"tier": "basic"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["subscription_tier"] == "basic"

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

        # Опубликовать (черновик → опубликовано) перед продажей
        ev = await db_session.get(Event, uuid.UUID(event_id))
        ev.is_published = True
        await db_session.commit()

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

        # Опубликовать (черновик → опубликовано) перед продажей
        ev = await db_session.get(Event, uuid.UUID(event_id))
        ev.is_published = True
        await db_session.commit()

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

    # ═══════════════════════════════════════════════════════════════════
    # Полный цикл организатора с подпиской (Mini App, реальная БД)
    # ═══════════════════════════════════════════════════════════════════

    async def test_full_organizer_cycle_with_subscription(self, db_client, db_session):
        """Организатор с PRO-подпиской без канала проходит весь цикл:
        subscribe → me → create (draft) → publish → list → get → edit →
        toggle → stats → buy → tickets → checkin → QR → delete."""
        user = await _organizer_user(db_session)
        await db_session.commit()

        # ── 1. Покупка подписки: role user → organizer (UserService.activate_subscription) ──
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "user"

        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "organizer", resp.json()

        # ── 2. Создание мероприятия без канала (платное — Pro) → черновик ──
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id), price=100, total=10),
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]
        assert resp.json()["is_published"] is False

        # ── 3. Публикация: is_published=true. Анонс — внешний side-effect
        #        (пост в Telegram): патчим оба, бизнес-логику НЕ мокаем. ──
        with (
            patch("app.web.routes.post_event_announcement", new_callable=AsyncMock, return_value=False),
            patch("app.web.routes.send_announcement_dm", new_callable=AsyncMock, return_value=False),
        ):
            resp = await db_client.post(
                f"/api/admin/events/{event_id}/publish", headers=HEADERS,
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_published"] is True
        # owner-событие без канала — анонс не публикуется (announced=false)
        assert resp.json()["announced"] is False
        # DM-fallback вызван (announced=false → send_announcement_dm)
        assert resp.json()["dm_sent"] is False  # замокан

        resp = await db_client.get(f"/api/admin/events/{event_id}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["is_published"] is True

        # ── 4. Просмотр своих ──
        resp = await db_client.get("/api/admin/events", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        mine = [e for e in resp.json() if e["id"] == event_id]
        assert len(mine) == 1, resp.json()
        assert mine[0]["owner_user_id"] == str(user.id)
        assert mine[0]["channel_id"] is None

        # ── 5. Редактирование (название / цена / кол-во) ──
        resp = await db_client.patch(
            f"/api/admin/events/{event_id}",
            headers=HEADERS,
            json={"title": "E2E Renamed", "price": 200, "total_tickets": 20},
        )
        assert resp.status_code == 200, resp.text
        resp = await db_client.get(f"/api/admin/events/{event_id}", headers=HEADERS)
        detail = resp.json()
        assert detail["title"] == "E2E Renamed"
        assert detail["price"] == 200.0
        assert detail["total_tickets"] == 20

        # ── 6. Toggle вкл/выкл ──
        resp = await db_client.post(f"/api/admin/events/{event_id}/toggle", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        resp = await db_client.post(f"/api/admin/events/{event_id}/toggle", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

        # ── 7. Статистика до продаж ──
        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        stats = resp.json()
        assert stats["sold"] == 0, stats
        assert stats["total_tickets"] == 20
        assert stats["available"] == 20, stats  # total 10→20, available синхронизирован

        # ── 8. Билеты: покупатель покупает (POST /events/{id}/buy) ──
        resp = await db_client.post(f"/api/events/{event_id}/buy", headers=HEADERS)
        assert resp.status_code == 201, resp.text
        ticket_a_id = resp.json()["ticket_id"]

        # Отдельный покупатель 77777 — через реальный TicketService (API хардкодит юзера 12345)
        buyer = await UserService(db_session).get_or_create(
            PlatformType.telegram, "77777", "Buyer",
        )
        await TicketService(db_session).buy_ticket_webapp(buyer.id, uuid.UUID(event_id))
        await db_session.commit()

        # Организатор видит оба билета
        resp = await db_client.get(f"/api/admin/events/{event_id}/tickets", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        tickets = resp.json()["tickets"]
        assert len(tickets) == 2, tickets
        buyer_ticket = [t for t in tickets if t["user_name"] == "Buyer"]
        assert len(buyer_ticket) == 1, tickets
        buyer_code = buyer_ticket[0]["validation_code"]
        assert buyer_code is not None

        # stats после 2 продаж: sold=2, available=18
        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        stats = resp.json()
        assert stats["sold"] == 2, stats
        assert stats["available"] == 18, stats

        # ── 9. Проверка билета на входе (checkin по коду) ──
        resp = await db_client.post(
            "/api/admin/tickets/checkin",
            headers=HEADERS,
            json={"code": buyer_code},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True
        assert resp.json()["status"] == "checked_in"

        # validate: билет уже отмечен
        resp = await db_client.get(
            "/api/admin/tickets/validate",
            headers=HEADERS,
            params={"code": buyer_code},
        )
        assert resp.status_code == 200
        assert resp.json()["already_checked_in"] is True

        # stats после чекина: билет покупателя больше не active → sold=1
        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        stats = resp.json()
        assert stats["sold"] == 1, stats
        assert stats["available"] == 18, stats

        # ── 10. QR для купленного билета (pro) ──
        resp = await db_client.get(f"/api/admin/tickets/{ticket_a_id}/qr", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert "image/png" in resp.headers["content-type"]

        # ── 11. Мягкое удаление ──
        resp = await db_client.post(f"/api/admin/events/{event_id}/delete", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        resp = await db_client.get("/api/admin/events", headers=HEADERS)
        assert resp.status_code == 200
        assert all(e["id"] != event_id for e in resp.json()), resp.json()

        # удалённое событие исчезло из списка, но в БД оно мягко удалено
        from sqlalchemy import select
        from app.core.models import Event as EventModel
        from app.core.database import Base as _B  # noqa: F401 — таблицы созданы conftest
        row = (await db_session.execute(
            select(EventModel).where(EventModel.id == uuid.UUID(event_id)),
        )).scalar_one_or_none()
        assert row is not None
        assert row.deleted_at is not None

    async def test_owner_event_invites_allowed(self, db_client, db_session):
        """Пригласительные по owner-событию организатора БЕЗ канала → 201.

        Решение (2026-08-07): организатор без канала (owner-мероприятие)
        с PRO-подпиской и квотой тоже выдаёт пригласительные.
        """
        user = await _organizer_user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json={**_event_payload(owner_user_id=str(user.id), price=100, total=10), "invites_quota": 5},
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites",
            headers=HEADERS,
            json={"seats": 1},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["validation_code"] is not None

    async def test_channel_organizer_invites_and_qr(self, db_client, db_session):
        """Организатор С pro-каналом: пригласительные (quota+pro) + QR + отмена.

        Канальный путь регресса: create через channel_id → invite → QR → cancel.
        """
        await _organizer_user(db_session)

        channel_svc = ChannelService(db_session)
        channel = await channel_svc.create(
            telegram_channel_id="e2e_channel_invites",
            admin_telegram_user_id="12345",
            title="E2E Invites Channel",
        )
        await channel_svc.activate_subscription(
            channel.id, duration_days=365, tier=SubscriptionTier.pro,
        )
        await ChannelAdminService(db_session).sync_admins(channel.id, ["12345"])
        await db_session.commit()

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json={**_event_payload(channel_id=str(channel.id), price=500, total=20), "invites_quota": 5},
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # выдача пригласительного (seats=2)
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites",
            headers=HEADERS,
            json={"seats": 2},
        )
        assert resp.status_code == 201, resp.text
        invite_id = resp.json()["ticket_id"]
        assert resp.json()["seats"] == 2
        assert resp.json()["validation_code"] is not None

        # список пригласительных
        resp = await db_client.get(f"/api/admin/events/{event_id}/invites", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["invites"]) == 1

        # stats: seats=2 заняты, квота=5
        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        stats = resp.json()
        assert stats["invites_issued"] == 1, stats
        assert stats["invites_quota"] == 5, stats
        assert stats["available"] == 18, stats  # 20 - 2 места приглашения

        # QR пригласительного (pro)
        resp = await db_client.get(f"/api/admin/tickets/{invite_id}/qr", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert "image/png" in resp.headers["content-type"]

        # отмена → места возвращаются
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites/{invite_id}/cancel",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"

        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        assert resp.json()["available"] == 20, resp.json()

    async def test_invites_not_counted_in_sold(self, db_client, db_session):
        """F-invites (owner-путь): пригласительное НЕ в sold, но вычитается из available.

        Контракт пригласительного как «ссылки»:
        - is_invite=True, seats=N → stats.sold НЕ меняется (растёт только invites_issued);
        - stats.available уменьшается на N (места резервируются);
        - отмена пригласительного → available += N, sold не трогает.
        Реальная БД, роль организатора — через реальную pro-подписку.
        """
        user = await _organizer_user(db_session)
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()

        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json={**_event_payload(owner_user_id=str(user.id), price=100, total=10), "invites_quota": 5},
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        # Опубликовать, чтобы купить билет (черновик → продажа)
        ev = await db_session.get(Event, uuid.UUID(event_id))
        ev.is_published = True
        await db_session.commit()

        # Базовые stats
        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert resp.json()["sold"] == 0
        assert resp.json()["available"] == 10

        # Один ОБЫЧНЫЙ билет, чтобы отличать sold от пригласительных
        resp = await db_client.post(f"/api/events/{event_id}/buy", headers=HEADERS)
        assert resp.status_code == 201, resp.text

        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        assert resp.json()["sold"] == 1, resp.json()
        assert resp.json()["available"] == 9, resp.json()

        # Выдать пригласительное seats=2
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites",
            headers=HEADERS,
            json={"seats": 2},
        )
        assert resp.status_code == 201, resp.text
        invite_id = resp.json()["ticket_id"]
        assert resp.json()["seats"] == 2

        # stats: sold НЕ изменился (1), invites_issued=1, available 9 → 7
        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        stats = resp.json()
        assert stats["sold"] == 1, stats          # пригласительное не считается проданным
        assert stats["invites_issued"] == 1, stats
        assert stats["invites_used"] == 0, stats
        assert stats["available"] == 7, stats     # 10 - 1 билет - 2 места приглашения

        # Отмена → места возвращаются (available 7 → 9), sold не трогает
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/invites/{invite_id}/cancel",
            headers=HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "refunded"

        resp = await db_client.get(f"/api/admin/events/{event_id}/stats", headers=HEADERS)
        stats = resp.json()
        assert stats["sold"] == 1, stats
        assert stats["available"] == 9, stats

    async def test_buyer_cannot_admin(self, db_client, db_session):
        """Покупатель (без подписки и канала): открытое создание мероприятий,
        но нет доступа к организаторским функциям (статистика, каналы)."""
        await _organizer_user(db_session)
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "user"

        # GET /admin/events — 200 (открыто: свои owner-мероприятия)
        resp = await db_client.get("/api/admin/events", headers=HEADERS)
        assert resp.status_code == 200, resp.text

        # POST /admin/events — 201 для бесплатного своего (открытое создание)
        me = await db_client.get("/api/me", headers=HEADERS)
        my_uid = me.json()["id"]
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=my_uid, price=0),
        )
        assert resp.status_code == 201, resp.text

        # Статистика (GET /admin/stats) — 403 (только организатор)
        resp = await db_client.get("/api/admin/stats", headers=HEADERS)
        assert resp.status_code == 403, resp.text

        # Каналы (GET /admin/channels) — 403 (только super-admin)
        resp = await db_client.get("/api/admin/channels", headers=HEADERS)
        assert resp.status_code == 403, resp.text


class TestRealUserPath:
    """Реальный путь пользователя через API (без моков ролей).

    Создание открыто для всех; платное — только после покупки pro.
    Факт покупки = активация функций матрицы.
    """

    async def test_real_user_path_creation_and_subscription(self, db_client, db_session):
        """Пользователь: создать бесплатное → платное 409 → купить pro → платное 201."""
        user = await _organizer_user(db_session)
        await db_session.commit()

        # 1. Роль user (без подписки)
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "user"

        # 2. Создание бесплатного — ОТКРЫТО (201)
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id), price=0, total=10),
        )
        assert resp.status_code == 201, resp.text
        free_event_id = resp.json()["id"]

        # 3. Платное без pro → 409
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id), price=500, total=10),
        )
        assert resp.status_code == 409, resp.text

        # 4. Покупка pro через реальный API
        resp = await db_client.post(
            "/api/me/subscription",
            headers=HEADERS,
            json={"tier": "pro"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["subscription_tier"] == "pro"

        # 5. Роль → organizer
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["role"] == "organizer"

        # 6. Платное теперь можно → 201
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json=_event_payload(owner_user_id=str(user.id), price=500, total=10),
        )
        assert resp.status_code == 201, resp.text


class TestSelfServiceChannels:
    """Самообслуживание: обычный пользователь добавляет свой канал."""

    async def test_regular_user_adds_own_channel(self, db_client, db_session):
        """Обычный пользователь (без подписки) может добавить канал → 201."""
        user = await _organizer_user(db_session)
        await db_session.commit()
        # Без подписки — роль user
        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.json()["role"] == "user"

        # Добавить канал → 201
        resp = await db_client.post(
            "/api/me/channels",
            headers=HEADERS,
            json={"telegram_channel_id": "@myownchannel", "title": "Мой канал"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["title"] == "Мой канал"
        assert "telegram_channel_id" in resp.json()

        # Канал в списке
        resp = await db_client.get("/api/me/channels", headers=HEADERS)
        assert resp.status_code == 200
        channels = resp.json()
        assert len(channels) == 1
        assert channels[0]["telegram_channel_id"] == "@myownchannel"

        # Идемпотентно: повторный POST → 200
        resp = await db_client.post(
            "/api/me/channels",
            headers=HEADERS,
            json={"telegram_channel_id": "@myownchannel"},
        )
        assert resp.status_code == 200, resp.text

    async def test_cannot_claim_other_users_channel(self, db_client, db_session):
        """Пользователь не может забрать чужой канал → 409."""
        from app.core.models import PlatformType

        # Первый пользователь регистрирует канал
        user1 = await _organizer_user(db_session)
        await db_session.commit()
        resp = await db_client.post(
            "/api/me/channels",
            headers=HEADERS,
            json={"telegram_channel_id": "@claimed"},
        )
        assert resp.status_code == 201, resp.text

        # Второй пользователь пытается забрать тот же канал → 409
        user2 = await UserService(db_session).get_or_create(
            PlatformType.telegram, "67890", "Second",
        )
        await db_session.commit()

        # X-Skip-Auth: 1 всегда резолвится в platform_user_id=12345 (первый пользователь).
        # Для честной проверки создаём канал через сервис от имени второго пользователя,
        # затем проверяем что первый не может его забрать.
        from app.core.services import ChannelService, ChannelAdminService
        channel_svc = ChannelService(db_session)
        admin_svc = ChannelAdminService(db_session)
        other_channel = await channel_svc.create(
            telegram_channel_id="@otherclaim",
            admin_telegram_user_id="67890",
            title="Second user channel",
        )
        await admin_svc.sync_admins(other_channel.id, ["67890"])
        await db_session.commit()

        # Первый пользователь (12345) пытается забрать → 409
        resp = await db_client.post(
            "/api/me/channels",
            headers=HEADERS,
            json={"telegram_channel_id": "@otherclaim"},
        )
        assert resp.status_code == 409, resp.text
