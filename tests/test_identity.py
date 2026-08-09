"""
Каноническая идентичность организатора (фича #160).

Проверяет резолвинг канонического пользователя через user_identities,
привязку площадок (TG ↔ VK) и одноразовые коды линковки.

Принципы:
- Линковка — только для организаторов (осознанное действие с обеих сторон).
- Одна площадка+ID (platform, platform_user_id) привязана к одному канону.
- Код линковки — одноразовый, короткоживущий, не может привязать чужую identity.
"""

from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio

from app.core.models import PlatformType, User, UserIdentity, LinkCode, SubscriptionTier
from app.core.services import UserService


@pytest_asyncio.fixture
async def tg_user(user_svc: UserService) -> User:
    """Канонический организатор в Telegram."""
    return await user_svc.get_or_create(
        platform=PlatformType.telegram,
        platform_user_id="tg_12345",
        name="Организатор TG",
    )


# ─── get_or_create: резолвинг канона ────────────────────────────


async def test_get_or_create_new_creates_user_and_identity(db_session, user_svc):
    """Новый пользователь: создаются user + identity, get_or_create находит его."""
    user = await user_svc.get_or_create(
        platform=PlatformType.vk, platform_user_id="vk_777", name="Новый"
    )
    assert user is not None
    # Повторный вызов возвращает того же пользователя
    user2 = await user_svc.get_or_create(
        platform=PlatformType.vk, platform_user_id="vk_777", name="Новый"
    )
    assert user2.id == user.id


async def test_get_or_create_resolves_canonical_after_link(user_svc, tg_user):
    """После привязки VK-identity вход по VK возвращает канонического пользователя."""
    await user_svc.link_identity(
        canonical_user_id=tg_user.id,
        platform=PlatformType.vk,
        platform_user_id="vk_organizer",
    )
    vk_user = await user_svc.get_or_create(
        platform=PlatformType.vk, platform_user_id="vk_organizer", name="X"
    )
    assert vk_user.id == tg_user.id
    assert vk_user.name == "Организатор TG"


async def test_get_or_create_unlinked_platforms_are_separate(user_svc):
    """Без линковки TG и VK — два разных пользователя (покупатели раздельны)."""
    tg = await user_svc.get_or_create(PlatformType.telegram, "puid_1")
    vk = await user_svc.get_or_create(PlatformType.vk, "puid_1")
    assert tg.id != vk.id


async def test_get_or_create_backfills_identity_for_legacy_user(db_session, user_svc):
    """Существующий пользователь (созданный до фичи, без identity) получает identity."""
    # Создаём "legacy" пользователя напрямую, без identity
    user = User(
        platform=PlatformType.telegram,
        platform_user_id="legacy_user",
        name="Legacy",
    )
    db_session.add(user)
    await db_session.flush()

    found = await user_svc.get_or_create(
        platform=PlatformType.telegram, platform_user_id="legacy_user", name="Legacy"
    )
    assert found.id == user.id
    # Identity была создана
    identities = await user_svc.list_identities(found.id)
    assert any(i.platform == PlatformType.telegram for i in identities)


# ─── link_identity ───────────────────────────────────────────────


async def test_link_identity_binds_platform(user_svc, tg_user):
    await user_svc.link_identity(tg_user.id, PlatformType.vk, "vk_a")
    ids = await user_svc.list_identities(tg_user.id)
    assert any(i.platform == PlatformType.vk and i.platform_user_id == "vk_a" for i in ids)


async def test_link_identity_rejects_taken_identity(user_svc, tg_user):
    """Площадка+ID уже привязана к другому пользователю — нельзя."""
    other = await user_svc.get_or_create(PlatformType.telegram, "other_owner")
    await user_svc.link_identity(other.id, PlatformType.vk, "shared_vk")

    with pytest.raises(ValueError):
        await user_svc.link_identity(tg_user.id, PlatformType.vk, "shared_vk")


async def test_link_identity_idempotent_same_canon(user_svc, tg_user):
    """Повторная привязка той же identity к тому же канону — не ошибка."""
    await user_svc.link_identity(tg_user.id, PlatformType.vk, "vk_b")
    await user_svc.link_identity(tg_user.id, PlatformType.vk, "vk_b")


# ─── Коды линковки ──────────────────────────────────────────────


async def test_create_link_code_generates_short_code(user_svc, tg_user):
    code = await user_svc.create_link_code(
        canonical_user_id=tg_user.id,
        target_platform=PlatformType.vk,
        ttl_minutes=10,
    )
    assert 4 <= len(code) <= 16


async def test_consume_link_code_links_platform(user_svc, tg_user):
    code = await user_svc.create_link_code(tg_user.id, PlatformType.vk, ttl_minutes=10)
    result = await user_svc.consume_link_code(code, PlatformType.vk, "vk_consumer")
    assert result is True
    # Вход по VK теперь ведёт на канон
    vk_user = await user_svc.get_or_create(PlatformType.vk, "vk_consumer")
    assert vk_user.id == tg_user.id


async def test_consume_link_code_one_time(user_svc, tg_user):
    code = await user_svc.create_link_code(tg_user.id, PlatformType.vk, ttl_minutes=10)
    await user_svc.consume_link_code(code, PlatformType.vk, "vk_one")
    # Повторное использование того же кода (другая площадка) — ошибка
    with pytest.raises(ValueError):
        await user_svc.consume_link_code(code, PlatformType.vk, "vk_two")


async def test_consume_link_code_expired(user_svc, tg_user, db_session):
    code = await user_svc.create_link_code(
        tg_user.id, PlatformType.vk, ttl_minutes=10,
    )
    # Истёкший код
    await db_session.execute(
        __import__("sqlalchemy").update(LinkCode)
        .where(LinkCode.code == code)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    )
    await db_session.commit()
    with pytest.raises(ValueError):
        await user_svc.consume_link_code(code, PlatformType.vk, "vk_expired")


async def test_consume_link_code_unknown_code(user_svc, tg_user):
    with pytest.raises(ValueError):
        await user_svc.consume_link_code("NOPE1234", PlatformType.vk, "vk_unknown")


async def test_consume_link_code_cannot_steal_taken_identity(user_svc, tg_user):
    """Код не может привязать identity, уже занятую другим пользователем."""
    other = await user_svc.get_or_create(PlatformType.vk, "already_taken_vk")
    code = await user_svc.create_link_code(tg_user.id, PlatformType.vk, ttl_minutes=10)
    with pytest.raises(ValueError):
        await user_svc.consume_link_code(code, PlatformType.vk, "already_taken_vk")


# ─── list_identities / resolve ───────────────────────────────────


async def test_list_identities_returns_all(user_svc, tg_user):
    await user_svc.link_identity(tg_user.id, PlatformType.vk, "vk_list")
    ids = await user_svc.list_identities(tg_user.id)
    platforms = {i.platform for i in ids}
    assert PlatformType.telegram in platforms
    assert PlatformType.vk in platforms


# ─── Ре-биндинг существующей identity (VK-вход → канон) ──────────


async def test_consume_link_code_rebinds_own_identity(user_svc, tg_user):
    """VK-пользователь уже имеет свою identity (вошёл ранее), вводит код → перепривязка."""
    # Организатор создаёт код
    code = await user_svc.create_link_code(tg_user.id, PlatformType.vk, ttl_minutes=10)
    # VK-пользователь уже вошёл — у него своя запись + identity
    vk_entry = await user_svc.get_or_create(PlatformType.vk, "vk_existing", name="ВК юзер")
    assert vk_entry.id != tg_user.id

    # Вводит код со своей стороны (current_user_id = его запись)
    await user_svc.consume_link_code(
        code, PlatformType.vk, "vk_existing", current_user_id=vk_entry.id,
    )
    # Теперь вход по VK ведёт на канон организатора
    resolved = await user_svc.get_or_create(PlatformType.vk, "vk_existing")
    assert resolved.id == tg_user.id


# ─── Web API: генерация кода и список identities ─────────────────


class TestLinkCodeEndpoint:
    """POST /api/me/link-code (organizer-only) и GET /api/me/identities."""

    async def test_organizer_creates_link_code(self, db_client, db_session):
        user_svc = UserService(db_session)
        user = await user_svc.get_or_create(
            PlatformType.telegram, "12345", name="Организатор"
        )
        await user_svc.activate_subscription(
            user.id, days=30, tier=SubscriptionTier.pro,
        )
        await db_session.commit()

        resp = await db_client.post(
            "/api/me/link-code",
            headers={"X-Skip-Auth": "1"},
            json={"target_platform": "vk"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert 4 <= len(data["code"]) <= 16
        assert data["target_platform"] == "vk"

    async def test_non_organizer_cannot_create_link_code(self, db_client, db_session):
        # Обычный пользователь без подписки — роль user → 403
        user_svc = UserService(db_session)
        await user_svc.get_or_create(PlatformType.telegram, "99999", name="Покупатель")
        await db_session.commit()

        resp = await db_client.post(
            "/api/me/link-code",
            headers={"X-Skip-Auth": "1"},
            json={"target_platform": "vk"},
        )
        assert resp.status_code == 403

    async def test_identities_listed(self, db_client, db_session):
        user_svc = UserService(db_session)
        user = await user_svc.get_or_create(PlatformType.telegram, "12345", name="Организатор")
        await user_svc.link_identity(user.id, PlatformType.vk, "vk_web")
        await db_session.commit()

        resp = await db_client.get("/api/me/identities", headers={"X-Skip-Auth": "1"})
        assert resp.status_code == 200
        platforms = {i["platform"] for i in resp.json()}
        assert "telegram" in platforms
        assert "vk" in platforms


class TestLinkConsumeEndpoint:
    """POST /api/me/link — ввод кода с VK-стороны (launch params + sign)."""

    async def test_vk_user_links_to_organizer(self, db_client, db_session):
        from app.web.vk_auth import compute_sign
        import base64
        from urllib.parse import urlencode
        from unittest.mock import patch

        # Организатор (TG) создаёт код
        user_svc = UserService(db_session)
        org = await user_svc.get_or_create(PlatformType.telegram, "org_tg", name="Организатор")
        await user_svc.activate_subscription(org.id, days=30, tier=SubscriptionTier.pro)
        code = await user_svc.create_link_code(org.id, PlatformType.vk, ttl_minutes=10)
        await db_session.commit()

        # VK-пользователь формирует launch params с подписью
        ts = int(__import__("time").time())
        params = {"vk_app_id": "54698875", "vk_user_id": "999001", "vk_ts": str(ts)}
        params["sign"] = compute_sign(params, "test_vk_secret")
        header = base64.b64encode(urlencode(sorted(params.items())).encode()).decode()

        with (
            patch("app.web.vk_auth.settings.vk_app_id", 54698875),
            patch("app.web.vk_auth.settings.vk_secret_key", "test_vk_secret"),
        ):
            resp = await db_client.post(
                "/api/me/link",
                headers={"X-VK-Init-Data": header},
                json={"code": code},
            )
        assert resp.status_code == 201
        assert resp.json()["linked"] is True

        # Вход по VK теперь ведёт на канон организатора
        resolved = await user_svc.get_or_create(PlatformType.vk, "999001")
        assert resolved.id == org.id

    async def test_link_requires_vk_auth(self, db_client, db_session):
        # TG-пользователь (X-Skip-Auth) не может вызвать /api/me/link
        user_svc = UserService(db_session)
        org = await user_svc.get_or_create(PlatformType.telegram, "org_tg2", name="Организатор")
        await user_svc.activate_subscription(org.id, days=30, tier=SubscriptionTier.pro)
        code = await user_svc.create_link_code(org.id, PlatformType.vk, ttl_minutes=10)
        await db_session.commit()

        resp = await db_client.post(
            "/api/me/link",
            headers={"X-Skip-Auth": "1"},
            json={"code": code},
        )
        assert resp.status_code == 400
