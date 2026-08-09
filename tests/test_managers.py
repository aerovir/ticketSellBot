"""
Соработники мероприятия — event_managers (#162).

Несколько продавцов на одном событии:
- Менеджер ведёт продажи: статистика, билеты, check-in, публикация, пригласительные.
- Управление событием (редактирование/удаление/менеджеры) — только владелец (owner).
- Добавление менеджера по платформенному ID → резолв канонического организатора.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio

from app.core.models import PlatformType, SubscriptionTier
from app.core.services import UserService, EventService


@pytest_asyncio.fixture
async def owner_and_event(db_session):
    """Организатор-владелец (TG) и его мероприятие без канала."""
    user_svc = UserService(db_session)
    owner = await user_svc.get_or_create(PlatformType.telegram, "owner_123", name="Владелец")
    await user_svc.activate_subscription(owner.id, days=30, tier=SubscriptionTier.pro)

    event_svc = EventService(db_session)
    event = await event_svc.create(
        title="Событие с соработниками",
        description="",
        date=datetime.now(timezone.utc) + timedelta(days=7),
        location="Москва",
        price=500,
        total_tickets=100,
        channel_id=None,
        owner_user_id=owner.id,
    )
    event.is_published = True
    await db_session.flush()
    return owner, event


# ─── Сервисный слой ──────────────────────────────────────────────


async def test_add_and_list_managers(db_session, owner_and_event, user_svc):
    owner, event = owner_and_event
    mgr = await user_svc.get_or_create(PlatformType.telegram, "mgr_1", name="Менеджер 1")
    event_svc = EventService(db_session)

    assert await event_svc.add_manager(event.id, mgr.id) is True
    managers = await event_svc.list_managers(event.id)
    assert [m.id for m in managers] == [mgr.id]
    assert await event_svc.is_manager(event.id, mgr.id) is True


async def test_add_manager_idempotent(db_session, owner_and_event, user_svc):
    owner, event = owner_and_event
    mgr = await user_svc.get_or_create(PlatformType.telegram, "mgr_2")
    event_svc = EventService(db_session)
    await event_svc.add_manager(event.id, mgr.id)
    assert await event_svc.add_manager(event.id, mgr.id) is False
    assert len(await event_svc.list_managers(event.id)) == 1


async def test_remove_manager(db_session, owner_and_event, user_svc):
    owner, event = owner_and_event
    mgr = await user_svc.get_or_create(PlatformType.telegram, "mgr_3")
    event_svc = EventService(db_session)
    await event_svc.add_manager(event.id, mgr.id)
    assert await event_svc.remove_manager(event.id, mgr.id) is True
    assert await event_svc.is_manager(event.id, mgr.id) is False


async def test_add_manager_unknown_event(db_session, owner_and_event, user_svc):
    owner, event = owner_and_event
    event_svc = EventService(db_session)
    with pytest.raises(ValueError):
        await event_svc.add_manager(
            __import__("uuid").uuid4(), owner.id,
        )


async def test_get_manager_event_ids(db_session, owner_and_event, user_svc):
    owner, event = owner_and_event
    mgr = await user_svc.get_or_create(PlatformType.telegram, "mgr_4")
    event_svc = EventService(db_session)
    assert await event_svc.get_manager_event_ids(mgr.id) == []
    await event_svc.add_manager(event.id, mgr.id)
    assert event.id in await event_svc.get_manager_event_ids(mgr.id)


async def test_manager_resolves_canonical_identity(db_session, owner_and_event, user_svc):
    """Менеджер, зарегистрированный через VK-identity, резолвится в канона."""
    owner, event = owner_and_event
    # Канонический организатор-менеджер с VK-identity
    mgr = await user_svc.get_or_create(PlatformType.telegram, "mgr_vk", name="Менеджер VK")
    await user_svc.link_identity(mgr.id, PlatformType.vk, "vk_mgr")

    # Добавление по VK ID должно найти канона
    resolved = await user_svc.get_by_platform_user_id(PlatformType.vk, "vk_mgr")
    event_svc = EventService(db_session)
    await event_svc.add_manager(event.id, resolved.id)
    managers = await event_svc.list_managers(event.id)
    assert managers[0].id == mgr.id


# ─── Web API ─────────────────────────────────────────────────────


class TestManagersWeb:
    """Эндпоинты соработников через db_client (реальная БД)."""

    async def test_owner_adds_manager_by_tg_id(self, db_client, db_session, owner_and_event):
        owner, event = owner_and_event
        user_svc = UserService(db_session)
        mgr = await user_svc.get_or_create(PlatformType.telegram, "mgr_web", name="Менеджер Web")
        await db_session.commit()

        # X-Skip-Auth = user 12345 — должен быть владельцем события.
        # Переназначим владельца события на текущего (12345).
        event_svc = EventService(db_session)
        await event_svc.update(event.id, owner_user_id=owner.id)
        # Создадим канона с TG id 12345 как владельца
        current_owner = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Dev")
        await event_svc.update(event.id, owner_user_id=current_owner.id)
        await db_session.commit()

        resp = await db_client.post(
            f"/api/admin/events/{event.id}/managers",
            headers={"X-Skip-Auth": "1"},
            json={"platform": "telegram", "platform_user_id": "mgr_web"},
        )
        assert resp.status_code == 201
        assert resp.json()["manager"]["id"] == str(mgr.id)

    async def test_add_manager_unknown_user_404(self, db_client, db_session, owner_and_event):
        owner, event = owner_and_event
        user_svc = UserService(db_session)
        current_owner = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Dev")
        event_svc = EventService(db_session)
        await event_svc.update(event.id, owner_user_id=current_owner.id)
        await db_session.commit()

        resp = await db_client.post(
            f"/api/admin/events/{event.id}/managers",
            headers={"X-Skip-Auth": "1"},
            json={"platform": "vk", "platform_user_id": "no_such_user"},
        )
        assert resp.status_code == 404

    async def test_manager_can_see_stats(self, db_client, db_session, owner_and_event):
        owner, event = owner_and_event
        # Текущий пользователь (12345) — менеджер события, владелец — другой
        user_svc = UserService(db_session)
        other = await user_svc.get_or_create(PlatformType.telegram, "someone_else", name="Владелец")
        event_svc = EventService(db_session)
        await event_svc.update(event.id, owner_user_id=other.id)
        current = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Dev")
        await event_svc.add_manager(event.id, current.id)
        await db_session.commit()

        resp = await db_client.get(f"/api/admin/events/{event.id}/stats", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200

    async def test_manager_cannot_delete_event(self, db_client, db_session, owner_and_event):
        owner, event = owner_and_event
        user_svc = UserService(db_session)
        other = await user_svc.get_or_create(PlatformType.telegram, "someone_else2", name="Владелец")
        event_svc = EventService(db_session)
        await event_svc.update(event.id, owner_user_id=other.id)
        current = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Dev")
        await event_svc.add_manager(event.id, current.id)
        await db_session.commit()

        resp = await db_client.post(f"/api/admin/events/{event.id}/delete", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 403

    async def test_manager_cannot_add_another_manager(self, db_client, db_session, owner_and_event):
        owner, event = owner_and_event
        user_svc = UserService(db_session)
        other = await user_svc.get_or_create(PlatformType.telegram, "someone_else3", name="Владелец")
        event_svc = EventService(db_session)
        await event_svc.update(event.id, owner_user_id=other.id)
        current = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Dev")
        await event_svc.add_manager(event.id, current.id)
        await db_session.commit()

        resp = await db_client.post(
            f"/api/admin/events/{event.id}/managers",
            headers={"X-Skip-Auth": "1"},
            json={"platform": "telegram", "platform_user_id": "mgr_another"},
        )
        assert resp.status_code == 403

    async def test_non_manager_cannot_see_stats(self, db_client, db_session, owner_and_event):
        owner, event = owner_and_event
        # Владелец события — другой, текущий (12345) не менеджер и не владелец
        user_svc = UserService(db_session)
        other = await user_svc.get_or_create(PlatformType.telegram, "someone_else4", name="Владелец")
        event_svc = EventService(db_session)
        await event_svc.update(event.id, owner_user_id=other.id)
        await db_session.commit()

        resp = await db_client.get(f"/api/admin/events/{event.id}/stats", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 403

    async def test_owner_removes_manager(self, db_client, db_session, owner_and_event):
        owner, event = owner_and_event
        user_svc = UserService(db_session)
        current_owner = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Dev")
        mgr = await user_svc.get_or_create(PlatformType.telegram, "mgr_remove", name="Менеджер")
        event_svc = EventService(db_session)
        await event_svc.update(event.id, owner_user_id=current_owner.id)
        await event_svc.add_manager(event.id, mgr.id)
        await db_session.commit()

        resp = await db_client.delete(
            f"/api/admin/events/{event.id}/managers/{mgr.id}",
            headers={"X-Skip-Auth": "1"},
        )
        assert resp.status_code == 200
        assert await event_svc.is_manager(event.id, mgr.id) is False
