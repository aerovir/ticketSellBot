"""
Тесты FastAPI (Mini App) хендлеров.

Используем TestClient от FastAPI + X-Skip-Auth header для тестов.
initData validation тестируем отдельно с известными HMAC-векторами.
"""

import contextlib
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.web.server import create_app


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    """Создаёт тестовый FastAPI клиент с замоканной БД."""
    app = create_app()
    with (
        patch("app.web.server.init_db", new_callable=AsyncMock),
        patch("app.web.server.close_db", new_callable=AsyncMock),
        TestClient(app) as c,
    ):
        yield c


def make_valid_init_data(bot_token: str, user_id: int = 12345, **extra) -> str:
    """Generate a valid initData string for testing.

    Creates a data_check_string from params, signs it with the bot token,
    and returns the full query string including the hash.
    """
    params = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Test"}),
        **extra,
    }

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )

    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    sig = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    params["hash"] = sig
    return urlencode(sorted(params.items()))


# ═══════════════════════════════════════════════════════════════
# initData Validation Tests
# ═══════════════════════════════════════════════════════════════

class TestInitDataValidation:
    """Тесты валидации initData."""

    def test_validate_valid_init_data(self):
        """Валидная initData должна проходить проверку."""
        from app.web.dependencies import validate_init_data
        from fastapi import HTTPException

        bot_token = "test:token"
        init_data = make_valid_init_data(bot_token)

        with patch("app.web.dependencies.settings.telegram_token", bot_token):
            result = validate_init_data(x_init_data=init_data, x_skip_auth=None)

        assert result["user"]["id"] == 12345
        assert "hash" in result
        assert "auth_date" in result

    def test_validate_missing_hash(self):
        """Отсутствие hash должно вызывать 401."""
        from app.web.dependencies import validate_init_data
        from fastapi import HTTPException

        bad_data = "auth_date=123456&user=%7B%22id%22%3A1%7D"

        with patch("app.web.dependencies.settings.telegram_token", "test:token"):
            with pytest.raises(HTTPException) as exc:
                validate_init_data(x_init_data=bad_data, x_skip_auth=None)
            assert exc.value.status_code == 401

    def test_validate_wrong_signature(self):
        """Неверная подпись должна вызывать 401."""
        from app.web.dependencies import validate_init_data
        from fastapi import HTTPException

        bot_token = "test:token"
        init_data = make_valid_init_data(bot_token)
        # Tamper with the hash
        init_data = init_data.replace(init_data.split("hash=")[-1][:8], "deadbeef")

        with patch("app.web.dependencies.settings.telegram_token", bot_token):
            with pytest.raises(HTTPException) as exc:
                validate_init_data(x_init_data=init_data, x_skip_auth=None)
            assert exc.value.status_code == 401

    def test_validate_missing_header(self):
        """Отсутствие заголовка X-Init-Data должно вызывать 401."""
        from app.web.dependencies import validate_init_data
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            validate_init_data(x_init_data=None)
        assert exc.value.status_code == 401

    def test_validate_skip_auth(self):
        """Заголовок X-Skip-Auth должен пропускать валидацию."""
        from app.web.dependencies import validate_init_data

        result = validate_init_data(x_init_data=None, x_skip_auth="1")
        assert result["user"]["id"] == 12345
        assert result["hash"] == "skip"


# ═══════════════════════════════════════════════════════════════
# API Endpoint Tests
# ═══════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    """Тесты API endpoints с замоканными сервисами."""

    def test_health(self, client):
        """GET /health всегда доступен."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_events_unauthorized(self, client):
        """GET /api/events без initData — 401."""
        resp = client.get("/api/events")
        assert resp.status_code == 401

    def test_events_skip_auth(self, client):
        """GET /api/events с X-Skip-Auth — 200 и список."""
        with patch(
            "app.web.routes.EventService.list_upcoming",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(
                "/api/events",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_events_with_data(self, client):
        """GET /api/events возвращает список мероприятий."""
        from datetime import datetime, timezone

        mock_event = Mock()
        mock_event.id = "550e8400-e29b-41d4-a716-446655440000"
        mock_event.title = "Test Event"
        mock_event.date = datetime.now(timezone.utc)
        mock_event.location = "Moscow"
        mock_event.price = 1000.0
        mock_event.available_tickets = 50
        mock_event.total_tickets = 100

        with patch(
            "app.web.routes.EventService.list_upcoming",
            new_callable=AsyncMock,
            return_value=[mock_event],
        ):
            resp = client.get(
                "/api/events",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Event"
        assert data[0]["price"] == 1000.0

    def test_event_detail_found(self, client):
        """GET /api/events/{id} — детали мероприятия."""
        from datetime import datetime, timezone

        mock_event = Mock()
        mock_event.id = "550e8400-e29b-41d4-a716-446655440000"
        mock_event.title = "Test Event"
        mock_event.description = "Description"
        mock_event.date = datetime.now(timezone.utc)
        mock_event.location = "Moscow"
        mock_event.price = 1000.0
        mock_event.available_tickets = 50
        mock_event.total_tickets = 100
        mock_event.is_active = True

        with patch(
            "app.web.routes.EventService.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_event,
        ):
            resp = client.get(
                "/api/events/550e8400-e29b-41d4-a716-446655440000",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Event"

    def test_event_detail_not_found(self, client):
        """GET /api/events/{id} — 404 если нет."""
        with patch(
            "app.web.routes.EventService.get_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                "/api/events/550e8400-e29b-41d4-a716-446655440000",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 404

    def test_event_detail_invalid_uuid(self, client):
        """GET /api/events/{id} с не-UUID — 400."""
        resp = client.get(
            "/api/events/not-a-uuid",
            headers={"X-Skip-Auth": "1"},
        )
        assert resp.status_code == 400

    def test_buy_ticket_success(self, client):
        """POST /api/events/{id}/buy — успешная покупка."""
        mock_result = {
            "ticket_id": "660e8400-e29b-41d4-a716-446655440001",
            "event_title": "Test Event",
            "event_date": "2026-12-25T19:00:00+00:00",
            "amount": 1000.0,
            "payment_id": "770e8400-e29b-41d4-a716-446655440002",
            "payment_status": "pending",
            "purchase_date": "2026-07-10T12:00:00+00:00",
        }

        with (
            patch("app.web.routes.UserService.get_or_create", new_callable=AsyncMock) as mock_user,
            patch("app.web.routes.TicketService.buy_ticket_webapp", new_callable=AsyncMock) as mock_buy,
        ):
            mock_user.return_value = Mock(id="550e8400-e29b-41d4-a716-446655440000")
            mock_buy.return_value = mock_result

            resp = client.post(
                "/api/events/550e8400-e29b-41d4-a716-446655440000/buy",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 201
        assert resp.json()["payment_status"] == "pending"

    def test_buy_ticket_conflict(self, client):
        """POST /api/events/{id}/buy — конфликт (билеты кончились)."""
        with (
            patch("app.web.routes.UserService.get_or_create", new_callable=AsyncMock) as mock_user,
            patch("app.web.routes.TicketService.buy_ticket_webapp", new_callable=AsyncMock) as mock_buy,
        ):
            mock_user.return_value = Mock(id="550e8400-e29b-41d4-a716-446655440000")
            mock_buy.side_effect = ValueError("Билеты закончились")

            resp = client.post(
                "/api/events/550e8400-e29b-41d4-a716-446655440000/buy",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 409
        assert "Билеты закончились" in resp.json()["detail"]

    def test_my_tickets(self, client):
        """GET /api/tickets — список билетов пользователя."""
        from datetime import datetime, timezone

        mock_tickets = [
            {
                "id": "660e8400-e29b-41d4-a716-446655440001",
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "event_title": "Test Event",
                "purchase_date": datetime.now(timezone.utc),
                "status": "active",
            }
        ]

        with (
            patch("app.web.routes.UserService.get_or_create", new_callable=AsyncMock) as mock_user,
            patch("app.web.routes.TicketService.get_user_tickets", new_callable=AsyncMock) as mock_tickets_svc,
        ):
            mock_user.return_value = Mock(id="550e8400-e29b-41d4-a716-446655440000")
            mock_tickets_svc.return_value = mock_tickets

            resp = client.get(
                "/api/tickets",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["event_title"] == "Test Event"

    def test_cancel_ticket_success(self, client):
        """POST /api/tickets/{id}/cancel — успешная отмена."""
        with (
            patch("app.web.routes.UserService.get_or_create", new_callable=AsyncMock) as mock_user,
            patch("app.web.routes.TicketService.cancel_ticket", new_callable=AsyncMock) as mock_cancel,
        ):
            mock_ticket = Mock()
            mock_ticket.id = "660e8400-e29b-41d4-a716-446655440001"
            mock_ticket.status.value = "refunded"
            mock_ticket.event_id = "550e8400-e29b-41d4-a716-446655440000"
            mock_user.return_value = Mock(id="550e8400-e29b-41d4-a716-446655440000")
            mock_cancel.return_value = mock_ticket

            resp = client.post(
                "/api/tickets/660e8400-e29b-41d4-a716-446655440001/cancel",
                headers={"X-Skip-Auth": "1"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"


# ═══════════════════════════════════════════════════════════════
# Admin API Tests (личный кабинет + админка)
# ═══════════════════════════════════════════════════════════════

CHANNEL_ID = "11111111-1111-4111-8111-111111111111"
EVENT_ID = "22222222-2222-4222-8222-222222222222"
USER_ID = "33333333-3333-4333-8333-333333333333"


@contextlib.contextmanager
def admin_auth(is_super=False, channel_ids=None, sub_valid=True):
    """Контекст-менеджер: резолв текущего пользователя с заданной ролью."""
    channel_ids = channel_ids or []
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("app.web.dependencies.settings.admin_telegram_ids", "12345" if is_super else ""))
        _mock_user = Mock(id=USER_ID)
        _mock_user.name = "Dev"
        _mock_user.platform_user_id = "12345"
        stack.enter_context(patch(
            "app.web.dependencies.UserService.get_or_create",
            new_callable=AsyncMock,
            return_value=_mock_user,
        ))
        stack.enter_context(patch(
            "app.web.dependencies.ChannelService.get_channel_ids_by_admin",
            new_callable=AsyncMock,
            return_value=channel_ids,
        ))
        stack.enter_context(patch(
            "app.web.dependencies.ChannelService.is_subscription_valid",
            new_callable=AsyncMock,
            return_value=sub_valid,
        ))
        yield



def _mock_channel():
    ch = Mock()
    ch.id = CHANNEL_ID
    ch.telegram_channel_id = "@test"
    ch.title = "Test Channel"
    ch.is_subscription_active = True
    ch.subscription_tier.value = "pro"
    ch.subscription_until = None
    return ch

class TestAdminAPI:
    """Тесты личного кабинета и админки."""

    def test_me_role_user(self, client):
        """GET /api/me — роль user при отсутствии прав."""
        with (
            admin_auth(is_super=False, channel_ids=[]),
            patch("app.web.routes.ChannelService.get_channels_by_admin", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/me", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "user"
        assert data["is_super_admin"] is False

    def test_me_role_channel_admin(self, client):
        """GET /api/me — роль channel_admin при канале с активной подпиской."""
        with (
            admin_auth(is_super=False, channel_ids=[CHANNEL_ID], sub_valid=True),
            patch("app.web.routes.ChannelService.get_channels_by_admin", new_callable=AsyncMock, return_value=[_mock_channel()]),
        ):
            resp = client.get("/api/me", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "channel_admin"

    def test_me_role_super_admin(self, client):
        """GET /api/me — роль super_admin по config."""
        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.ChannelService.get_channels_by_admin", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/me", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "super_admin"
        assert data["is_super_admin"] is True

    def test_admin_events_forbidden_for_user(self, client):
        """GET /api/admin/events — 403 для обычного пользователя."""
        with admin_auth(is_super=False, channel_ids=[]):
            resp = client.get("/api/admin/events", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 403

    def test_admin_events_list_super(self, client):
        """GET /api/admin/events — super-admin видит все."""
        from datetime import datetime, timezone
        mock_event = Mock()
        mock_event.id = EVENT_ID
        mock_event.channel_id = CHANNEL_ID
        mock_event.title = "Test"
        mock_event.date = datetime.now(timezone.utc)
        mock_event.location = "Moscow"
        mock_event.price = 100.0
        mock_event.total_tickets = 100
        mock_event.available_tickets = 50
        mock_event.is_active = True
        mock_event.is_published = True
        mock_event.is_free = False

        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.EventService.list_all", new_callable=AsyncMock, return_value=[mock_event]),
            patch("app.web.routes.ChannelService.get_by_id", new_callable=AsyncMock, return_value=Mock(title="Channel")),
        ):
            resp = client.get("/api/admin/events", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_admin_create_event_ok(self, client):
        """POST /api/admin/events — создание черновика."""
        mock_event = Mock()
        mock_event.id = EVENT_ID
        mock_event.is_published = False

        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.EventService.create", new_callable=AsyncMock, return_value=mock_event),
        ):
            resp = client.post(
                "/api/admin/events",
                headers={"X-Skip-Auth": "1"},
                json={
                    "title": "New Event",
                    "date": "2026-12-01T19:00:00Z",
                    "price": 0,
                    "total_tickets": 50,
                    "channel_id": CHANNEL_ID,
                },
            )
        assert resp.status_code == 201
        assert resp.json()["is_published"] is False

    def test_admin_create_event_wrong_channel(self, client):
        """POST /api/admin/events — 403 если канал вне managed."""
        other_channel = "99999999-9999-4999-8999-999999999999"
        with admin_auth(is_super=False, channel_ids=[CHANNEL_ID]):
            resp = client.post(
                "/api/admin/events",
                headers={"X-Skip-Auth": "1"},
                json={
                    "title": "New Event",
                    "date": "2026-12-01T19:00:00Z",
                    "price": 0,
                    "total_tickets": 50,
                    "channel_id": other_channel,
                },
            )
        assert resp.status_code == 403

    def test_admin_create_event_conflict(self, client):
        """POST /api/admin/events — 409 при ValueError (напр. платное на basic)."""
        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.EventService.create", new_callable=AsyncMock, side_effect=ValueError("Тариф не позволяет платные мероприятия")),
        ):
            resp = client.post(
                "/api/admin/events",
                headers={"X-Skip-Auth": "1"},
                json={
                    "title": "New Event",
                    "date": "2026-12-01T19:00:00Z",
                    "price": 500,
                    "total_tickets": 50,
                    "channel_id": CHANNEL_ID,
                },
            )
        assert resp.status_code == 409

    def test_admin_publish(self, client):
        """POST /api/admin/events/{id}/publish — публикация + анонс."""
        mock_event = Mock()
        mock_event.id = EVENT_ID
        mock_event.channel_id = CHANNEL_ID

        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.EventService.get_by_id", new_callable=AsyncMock, return_value=mock_event),
            patch("app.web.routes.EventService.update", new_callable=AsyncMock, return_value=mock_event),
            patch("app.web.routes.post_event_announcement", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.post(f"/api/admin/events/{EVENT_ID}/publish", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert resp.json()["announced"] is True

    def test_admin_checkin_ok(self, client):
        """POST /api/admin/tickets/checkin — успешный вход."""
        mock_ticket = Mock()
        mock_ticket.id = EVENT_ID
        mock_ticket.status.value = "checked_in"
        mock_ticket.event_id = EVENT_ID
        mock_ticket.checked_in_at = None

        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.TicketService.check_in_by_code", new_callable=AsyncMock, return_value=mock_ticket),
        ):
            resp = client.post(
                "/api/admin/tickets/checkin",
                headers={"X-Skip-Auth": "1"},
                json={"code": "AB3X-K7M9"},
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_admin_checkin_conflict(self, client):
        """POST /api/admin/tickets/checkin — 409 при ошибке."""
        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.TicketService.check_in_by_code", new_callable=AsyncMock, side_effect=ValueError("Билет не найден")),
        ):
            resp = client.post(
                "/api/admin/tickets/checkin",
                headers={"X-Skip-Auth": "1"},
                json={"code": "ZZZZ-ZZZZ"},
            )
        assert resp.status_code == 409

    def test_admin_validate_ticket(self, client):
        """GET /api/admin/tickets/validate — проверка кода."""
        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.TicketService.validate_ticket", new_callable=AsyncMock, return_value={"found": False, "status": "not_found"}),
        ):
            resp = client.get("/api/admin/tickets/validate?code=ZZZZ-ZZZZ", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert resp.json()["found"] is False

    def test_admin_channels_forbidden_for_channel_admin(self, client):
        """GET /api/admin/channels — 403 для channel-admin."""
        with admin_auth(is_super=False, channel_ids=[CHANNEL_ID]):
            resp = client.get("/api/admin/channels", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 403

    def test_admin_channels_list_super(self, client):
        """GET /api/admin/channels — super-admin видит каналы."""
        mock_channel = Mock()
        mock_channel.id = CHANNEL_ID
        mock_channel.telegram_channel_id = "@test"
        mock_channel.title = "Test Channel"
        mock_channel.is_subscription_active = True
        mock_channel.subscription_tier.value = "pro"
        mock_channel.subscription_until = None

        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.ChannelService.list_all", new_callable=AsyncMock, return_value=[mock_channel]),
            patch("app.web.routes.ChannelAdminService.get_admin_ids", new_callable=AsyncMock, return_value=["123"]),
        ):
            resp = client.get("/api/admin/channels", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_admin_subscribe(self, client):
        """POST /api/admin/channels/{id}/subscribe."""
        mock_channel = Mock()
        mock_channel.is_subscription_active = True
        mock_channel.subscription_tier.value = "pro"
        mock_channel.subscription_until = None

        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.ChannelService.activate_subscription", new_callable=AsyncMock, return_value=mock_channel),
        ):
            resp = client.post(
                f"/api/admin/channels/{CHANNEL_ID}/subscribe",
                headers={"X-Skip-Auth": "1"},
                json={"duration_days": 30, "tier": "pro"},
            )
        assert resp.status_code == 200
        assert resp.json()["subscription_tier"] == "pro"

    def test_admin_stats_forbidden(self, client):
        """GET /api/admin/stats — 403 для channel-admin."""
        with admin_auth(is_super=False, channel_ids=[CHANNEL_ID]):
            resp = client.get("/api/admin/stats", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 403

    def test_admin_stats_ok(self, client):
        """GET /api/admin/stats — super-admin видит статистику."""
        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.StatsService.get_global_stats", new_callable=AsyncMock, return_value={"users_count": 1, "revenue": 0}),
        ):
            resp = client.get("/api/admin/stats", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert resp.json()["users_count"] == 1

    def test_admin_event_stats_channel_admin(self, client):
        """GET /api/admin/events/{id}/stats — channel-admin видит (без тарифного гейта)."""
        mock_event = Mock()
        mock_event.id = EVENT_ID
        mock_event.channel_id = CHANNEL_ID

        with (
            admin_auth(is_super=False, channel_ids=[CHANNEL_ID]),
            patch("app.web.routes.EventService.get_by_id", new_callable=AsyncMock, return_value=mock_event),
            patch("app.web.routes.EventService.get_event_stats", new_callable=AsyncMock, return_value={"total_tickets": 10, "sold": 2}),
        ):
            resp = client.get(f"/api/admin/events/{EVENT_ID}/stats", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert resp.json()["sold"] == 2

    def test_admin_csv_export(self, client):
        """GET /api/admin/events/{id}/tickets.csv — CSV экспорт."""
        mock_event = Mock()
        mock_event.id = EVENT_ID
        mock_event.channel_id = CHANNEL_ID
        mock_tickets = [{
            "ticket_id": "t1", "event_title": "Test", "user_name": "User",
            "purchase_date": "2026-08-01T10:00:00Z", "status": "active",
            "validation_code": "AB3X-K7M9", "checked_in_at": "", "checked_in_by": "", "is_free": "нет",
        }]

        with (
            admin_auth(is_super=True, channel_ids=[]),
            patch("app.web.routes.EventService.get_by_id", new_callable=AsyncMock, return_value=mock_event),
            patch("app.web.routes.TicketService.export_event_tickets", new_callable=AsyncMock, return_value=mock_tickets),
        ):
            resp = client.get(f"/api/admin/events/{EVENT_ID}/tickets.csv", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "AB3X-K7M9" in resp.text
