"""
Сквозной сценарий динамических цен по дате (early bird, pro-фича).

Реальная БД через db_client (httpx.ASGITransport), как test_promo_e2e.
Pro-организатор создаёт платное owner-событие, публикует, задаёт 2 ценовых
диапазона → покупатель видит/платит актуальную цену → рост цены не меняет
купленный билет → промокод поверх → free-событие PUT 409.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import UserService, TicketService

HEADERS = {"X-Skip-Auth": "1"}


class TestPriceRangesE2E:
    """Полный цикл динамических цен на реальной БД."""

    async def _pro_organizer(self, db_session):
        user = await UserService(db_session).get_or_create(PlatformType.telegram, "12345", "Dev")
        await UserService(db_session).activate_subscription(user.id, days=30, tier=SubscriptionTier.pro)
        await db_session.commit()
        return user

    async def _create_published(self, db_client, user, price=1000):
        resp = await db_client.post(
            "/api/admin/events",
            headers=HEADERS,
            json={
                "title": "Dynamic Price E2E",
                "date": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "price": price,
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
            resp = await db_client.post(f"/api/admin/events/{event_id}/publish", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        return event_id

    async def test_full_dynamic_pricing_flow(self, db_client, db_session):
        user = await self._pro_organizer(db_session)
        event_id = await self._create_published(db_client, user, price=1000)

        # ── 1. Задать 2 диапазона: ранний 500, поздний 800 (покрытие от публикации до даты) ──
        # Первый диапазон начинается ровно с published_at события
        from sqlalchemy import select
        from app.core.models import Event as EventModel
        await db_session.flush()
        ev = (await db_session.execute(select(EventModel).where(EventModel.id == uuid.UUID(event_id)))).scalar_one()
        pub = ev.published_at or datetime.now(timezone.utc)
        event_date = ev.date  # конец последнего диапазона = дата мероприятия
        now = datetime.now(timezone.utc)
        resp = await db_client.put(
            f"/api/admin/events/{event_id}/price-ranges",
            headers=HEADERS,
            json={"ranges": [
                {"starts_at": pub.isoformat(), "ends_at": (now + timedelta(days=3)).isoformat(), "price": 500},
                {"starts_at": (now + timedelta(days=3)).isoformat(), "ends_at": event_date.isoformat(), "price": 800},
            ]},
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["price_ranges"]) == 2

        # ── 2. Покупатель видит актуальную цену (сейчас — ранний диапазон 500) ──
        resp = await db_client.get(f"/api/events/{event_id}", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert resp.json()["price"] == 500.0, resp.text

        # ── 3. Покупка: base_amount = цена диапазона 500 ──
        resp = await db_client.post(f"/api/events/{event_id}/buy", headers=HEADERS)
        assert resp.status_code == 201, resp.text
        assert resp.json()["base_amount"] == 500.0
        assert resp.json()["amount"] == 500.0
        ticket_id = resp.json()["ticket_id"]

        # ── 4. Организатор поднял ранний диапазон до 700 ──
        resp = await db_client.put(
            f"/api/admin/events/{event_id}/price-ranges",
            headers=HEADERS,
            json={"ranges": [
                {"starts_at": pub.isoformat(), "ends_at": (now + timedelta(days=3)).isoformat(), "price": 700},
                {"starts_at": (now + timedelta(days=3)).isoformat(), "ends_at": event_date.isoformat(), "price": 800},
            ]},
        )
        assert resp.status_code == 200, resp.text

        # Покупатель теперь видит 700
        resp = await db_client.get(f"/api/events/{event_id}", headers=HEADERS)
        assert resp.json()["price"] == 700.0

        # ── 5. Купленный билет НЕ изменился (цена зафиксирована) ──
        from sqlalchemy import select
        from app.core.models import Payment
        pm = (await db_session.execute(select(Payment).where(Payment.ticket_id == ticket_id))).scalar_one()
        assert float(pm.base_amount) == 500.0

        # ── 6. Промокод 10% поверх актуальной цены 700 → 630 ──
        resp = await db_client.post(
            f"/api/admin/events/{event_id}/promo-codes",
            headers=HEADERS,
            json={"code": "DYNAMO10", "discount_type": "percent", "discount_value": 10},
        )
        assert resp.status_code == 201, resp.text
        buyer2 = await UserService(db_session).get_or_create(PlatformType.telegram, "buyer2", "Buyer2")
        await db_session.commit()
        t2 = await TicketService(db_session).buy_ticket(buyer2.id, uuid.UUID(event_id), promo_code="DYNAMO10")
        await db_session.commit()
        pm2 = (await db_session.execute(select(Payment).where(Payment.ticket_id == t2.id))).scalar_one()
        assert float(pm2.base_amount) == 700.0
        assert float(pm2.amount) == 630.0

        # ── 7. Free-событие: PUT диапазонов → 409 ──
        free_id = await self._create_published(db_client, user, price=0)
        resp = await db_client.put(
            f"/api/admin/events/{free_id}/price-ranges",
            headers=HEADERS,
            json={"ranges": [{"starts_at": now.isoformat(), "ends_at": (now + timedelta(days=2)).isoformat(), "price": 100}]},
        )
        assert resp.status_code == 409, resp.text
