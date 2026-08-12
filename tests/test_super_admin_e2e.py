"""
Сквозные e2e-сценарии роли «Супер-админ» (F13-F17) на реальной БД.

Роль super-admin задаётся ПАТЧЕМ settings.admin_telegram_ids = "12345"
(конфиг), БД и все сервисы — РЕАЛЬНЫЕ (db_client → тестовая БД через
httpx.ASGITransport). Никакие сервисы не мокаются.

Покрывает канонический journey супер-админа (docs/user-flows.md):
  F13 подписать канал → F14 смена админа + инфо канала →
  F15 глобальная статистика → F16 рассылка → F17 здоровье.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import ChannelService, UserService

HEADERS = {"X-Skip-Auth": "1"}
# Супер-админ — это конфиг: Telegram ID в ADMIN_TELEGRAM_IDS (settings).
SUPER_ADMIN_IDS_PATCH = "app.web.dependencies.settings.admin_telegram_ids"


def _future(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _event_payload(owner_user_id=None, price=0, total=10):
    return {
        "title": "SA E2E Event",
        "date": _future(7),
        "price": price,
        "total_tickets": total,
        "channel_id": None,
        "owner_user_id": owner_user_id,
    }


class _OneSessionCM:
    """Проксирует `async with async_session_factory()` на заданную сессию."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _OneSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _OneSessionCM(self._session)


class _FakeBot:
    """Фейк-бот для рассылки: send_message всегда успешен."""

    async def send_message(self, *args, **kwargs):
        return None


@pytest.mark.integration
class TestSuperAdminE2E:
    """Сквозные сценарии супер-админа (реальная БД, роль из конфига)."""

    # ─── F13: подписка каналов (глобально) ────────────────────────────

    async def test_f13_create_channel_and_subscribe(self, db_client, db_session):
        """F13: POST /admin/channels — создать канал и активировать подписку."""
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            # Вход супер-админа (роль из конфига, БД реальная)
            resp = await db_client.get("/api/me", headers=HEADERS)
            assert resp.status_code == 200
            assert resp.json()["role"] == "super_admin", resp.json()

            resp = await db_client.post(
                "/api/admin/channels",
                headers=HEADERS,
                json={
                    "telegram_channel_id": "@sa_channel_f13",
                    "title": "SA Channel F13",
                    "duration_days": 30,
                    "tier": "pro",
                },
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["telegram_channel_id"] == "@sa_channel_f13"
        assert data["is_subscription_active"] is True
        assert data["subscription_tier"] == "pro"

        # Канал реально создан в БД с активной подпиской
        channel = await ChannelService(db_session).get_by_telegram_id("@sa_channel_f13")
        assert channel is not None
        assert channel.is_subscription_active is True
        assert channel.subscription_tier == SubscriptionTier.pro
        assert channel.subscription_until is not None

    async def test_f13_subscribed_channel_visible_in_list(self, db_client, db_session):
        """F13: канал с подпиской виден в списке всех каналов (super-admin)."""
        channel_svc = ChannelService(db_session)
        channel = await channel_svc.create(
            "@sa_channel_f13b", "", "SA Channel F13B",
        )
        await channel_svc.activate_subscription(
            channel.id, duration_days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.get("/api/admin/channels", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        mine = [c for c in resp.json() if c["telegram_channel_id"] == "@sa_channel_f13b"]
        assert len(mine) == 1, resp.json()
        assert mine[0]["is_subscription_active"] is True
        assert mine[0]["subscription_tier"] == "basic"

    async def test_f13_non_super_admin_403(self, db_client):
        """F13: без ADMIN_TELEGRAM_IDS — 403 (роль из конфига, БД реальная)."""
        with patch(SUPER_ADMIN_IDS_PATCH, ""):
            resp = await db_client.post(
                "/api/admin/channels",
                headers=HEADERS,
                json={
                    "telegram_channel_id": "@sa_nope",
                    "duration_days": 30,
                    "tier": "pro",
                },
            )
        assert resp.status_code == 403, resp.text

    # ─── F14: список/инфо каналов, смена админа ───────────────────────

    async def test_f14_change_admin_and_channel_info(self, db_client, db_session):
        """F14: смена админа + детальная информация о канале."""
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.post(
                "/api/admin/channels",
                headers=HEADERS,
                json={"telegram_channel_id": "@sa_channel_f14", "duration_days": 30, "tier": "pro"},
            )
            assert resp.status_code == 201, resp.text
            channel_id = resp.json()["channel_id"]

            # Смена админа: пустой список старых → новый admin 555
            resp = await db_client.post(
                f"/api/admin/channels/{channel_id}/change_admin",
                headers=HEADERS,
                json={"new_admin_id": "555"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["channel_id"] == channel_id
        assert resp.json()["new_admin_id"] == "555"

        # Инфо о канале — новый админ в списке, подписка активна
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.get(f"/api/admin/channels/{channel_id}", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        info = resp.json()
        assert info["id"] == channel_id
        assert "555" in info["admins"], info
        assert info["is_subscription_active"] is True

    async def test_f14_channel_info_unknown_404(self, db_client):
        """F14: инфо о несуществующем канале — 404."""
        unknown_id = "00000000-0000-4000-8000-000000000000"
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.get(f"/api/admin/channels/{unknown_id}", headers=HEADERS)
        assert resp.status_code == 404, resp.text

    # ─── F15: глобальная статистика ───────────────────────────────────

    async def test_f15_global_stats_counts_sold_ticket(self, db_client, db_session):
        """F15: мероприятие → покупка → /admin/stats учитывает проданный билет."""
        user = await UserService(db_session).get_or_create(
            PlatformType.telegram, "12345", "Dev",
        )
        await db_session.commit()

        # Супер-админ создаёт мероприятие (владелец — 12345)
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.post(
                "/api/admin/events",
                headers=HEADERS,
                json=_event_payload(owner_user_id=str(user.id)),
            )
            assert resp.status_code == 201, resp.text
            event_id = resp.json()["id"]

            # Публикация (анонс — внешний side-effect, отправку мокаем)
            with (
                patch("app.web.routes.post_event_announcement", new_callable=AsyncMock, return_value=False),
                patch("app.web.routes.send_announcement_dm", new_callable=AsyncMock, return_value=False),
            ):
                resp = await db_client.post(f"/api/admin/events/{event_id}/publish", headers=HEADERS)
            assert resp.status_code == 200, resp.text
            assert resp.json()["is_published"] is True

        # Покупатель (X-Skip-Auth = 12345) покупает билет
        resp = await db_client.post(f"/api/events/{event_id}/buy", headers=HEADERS)
        assert resp.status_code == 201, resp.text

        # Глобальная статистика — активный билет учтён
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.get("/api/admin/stats", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        stats = resp.json()
        assert stats["tickets_active"] == 1, stats
        assert stats["events_count"] >= 1, stats

    async def test_f15_stats_forbidden_for_organizer(self, db_client, db_session):
        """F15: /admin/stats — 403 для организатора (не супер-админ)."""
        user = await UserService(db_session).get_or_create(
            PlatformType.telegram, "12345", "Dev",
        )
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        # admin_telegram_ids пусто → роль organizer (по подписке) → 403
        with patch(SUPER_ADMIN_IDS_PATCH, ""):
            resp = await db_client.get("/api/admin/stats", headers=HEADERS)
        assert resp.status_code == 403, resp.text

    # ─── F16: рассылка (broadcast) ─────────────────────────────────────

    async def test_f16_broadcast_counts_sent_total(self, db_client, db_session):
        """F16: рассылка в активные каналы — подсчёт sent/total (отправка замокана)."""
        # 2 активных канала в реальной БД
        channel_svc = ChannelService(db_session)
        for i in range(2):
            ch = await channel_svc.create(f"@bcast_ch_{i}", "", f"Broadcast {i}")
            await channel_svc.activate_subscription(
                ch.id, duration_days=30, tier=SubscriptionTier.basic,
            )
        await db_session.commit()

        factory = _OneSessionFactory(db_session)
        with (
            patch(SUPER_ADMIN_IDS_PATCH, "12345"),
            # send_broadcast живёт в app.web.announce — патчим его сессию и бота,
            # чтобы функция увидела каналы из db_session и отправила «в сеть» фейком
            patch("app.web.announce.async_session_factory", factory),
            patch("app.web.announce._get_bot", return_value=_FakeBot()),
        ):
            resp = await db_client.post(
                "/api/admin/broadcast",
                headers=HEADERS,
                json={"text": "Всем привет!"},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 2, data
        assert data["sent"] == 2, data

    async def test_f16_broadcast_empty_text_400(self, db_client):
        """F16: пустое сообщение — 400."""
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.post(
                "/api/admin/broadcast",
                headers=HEADERS,
                json={"text": "   "},
            )
        assert resp.status_code == 400, resp.text

    async def test_f16_broadcast_forbidden_for_organizer(self, db_client, db_session):
        """F16: рассылка — 403 для организатора."""
        user = await UserService(db_session).get_or_create(
            PlatformType.telegram, "12345", "Dev",
        )
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        with patch(SUPER_ADMIN_IDS_PATCH, ""):
            resp = await db_client.post(
                "/api/admin/broadcast",
                headers=HEADERS,
                json={"text": "hi"},
            )
        assert resp.status_code == 403, resp.text

    # ─── F17: здоровье / мониторинг ───────────────────────────────────

    async def test_f17_health_ok(self, db_client):
        """F17: /admin/health — 200, БД подключена."""
        with patch(SUPER_ADMIN_IDS_PATCH, "12345"):
            resp = await db_client.get("/api/admin/health", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["db_ok"] is True, data
        assert data["status"] == "ok", data

    async def test_f17_health_forbidden_for_organizer(self, db_client, db_session):
        """F17: /admin/health — 403 для не-супер-админа."""
        user = await UserService(db_session).get_or_create(
            PlatformType.telegram, "12345", "Dev",
        )
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.basic,
        )
        await db_session.commit()

        with patch(SUPER_ADMIN_IDS_PATCH, ""):
            resp = await db_client.get("/api/admin/health", headers=HEADERS)
        assert resp.status_code == 403, resp.text
