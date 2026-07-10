"""
Тесты FastAPI (Mini App) хендлеров.

Используем TestClient от FastAPI + X-Skip-Auth header для тестов.
initData validation тестируем отдельно с известными HMAC-векторами.
"""

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
