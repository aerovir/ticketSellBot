"""
Сквозной сценарий промокодов (скидки на билеты, pro-фича).

Реальная БД через db_client (httpx.ASGITransport), как TestCabinetFlow.
Pro-организатор (юзер 12345, реальная подписка) создаёт owner-событие,
промокод 10% (лимит 1), покупатель покупает со скидкой → used_count=1 →
второй покупатель упирается в лимит (409 через API / ValueError в сервисе).
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import UserService, TicketService

HEADERS = {"X-Skip-Auth": "1"}


@pytest.mark.integration
class TestPromoE2E:
    """Полный цикл промокода на реальной БД."""

    async def test_full_promo_flow(self, db_client, db_session):
        # ── 1. Pro-организатор (12345) через реальную подписку пользователя ──
        user = await UserService(db_session).get_or_create(
            PlatformType.telegram, "12345", "Dev"
        )
        await UserService(db_session).activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro
        )
        await db_session.commit()

        resp = await db_client.get("/api/me", headers=HEADERS)
        assert resp.json()["role"] == "organizer", resp.json()

        # ── 2. Платное owner-событие (черновик) → публикация ──
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json={
                "title": "Promo E2E Event",
                "date": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "price": 1000,
                "total_tickets": 50,
                "owner_user_id": str(user.id),
            },
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["id"]

        with (
            patch("app.web.routes.post_event_announcement", new_callable=AsyncMock, return_value=False),
            patch("app.web.routes.send_announcement_dm", new_callable=AsyncMock, return_value=False),
        ):
            resp = await db_client.post(
                f"/api/admin/events/{event_id}/publish", headers=HEADERS,
            )
        assert resp.status_code == 200, resp.text

        # ── 3. Создать промокод 10% (лимит 1) ──
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/promo-codes",
            headers=HEADERS,
            json={"code": "E2E10", "discount_type": "percent", "discount_value": 10, "max_uses": 1},
        )
        assert resp.status_code == 201, resp.text
        promo_id = resp.json()["id"]

        # ── 4. Покупатель покупает со скидкой ──
        resp = await db_client.post(
            f"/api/events/{event_id}/buy",
            headers=HEADERS,
            json={"promo_code": "E2E10"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["amount"] == 900.0
        assert resp.json()["base_amount"] == 1000.0
        assert resp.json()["discount_amount"] == 100.0
        assert resp.json()["promo_code"] == "E2E10"

        # ── 5. Организатор видит использование ──
        resp = await db_client.get(f"/api/admin/events/{event_id}/promo-codes", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        promos = {p["id"]: p for p in resp.json()["promo_codes"]}
        assert promos[promo_id]["used_count"] == 1

        # ── 6. Второй покупатель (другой юзер, прямой сервис) → лимит исчерпан ──
        buyer2 = await UserService(db_session).get_or_create(
            PlatformType.telegram, "buyer2", "Buyer2"
        )
        await db_session.commit()
        with pytest.raises(ValueError, match="исчерпан"):
            await TicketService(db_session).buy_ticket(
                buyer2.id, uuid.UUID(event_id), promo_code="E2E10"
            )
