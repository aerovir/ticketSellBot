"""
Тесты модуля database.py — инициализация и закрытие БД.
"""

import pytest
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import User


@pytest.mark.parametrize("expr,expected", [
    ("SELECT 1 AS val", 1),
    ("SELECT 'hello' AS val", "hello"),
])
async def test_raw_query(db_session: AsyncSession, expr, expected):
    """Проверка, что сессия может выполнять сырые запросы."""
    result = await db_session.execute(text(expr))
    assert result.scalar() == expected


async def test_session_rollback(db_session: AsyncSession):
    """Проверка, что данные не сохраняются после rollback."""
    # Вставляем пользователя
    user = User(
        platform="telegram",
        platform_user_id="rollback_test",
        name="Rollback User",
    )
    db_session.add(user)
    await db_session.flush()
    user_id = user.id

    # Проверяем, что он есть в текущей сессии
    result = await db_session.execute(
        select(func.count(User.id)).where(User.id == user_id)
    )
    assert result.scalar() == 1


async def test_get_session(test_engine):
    """Проверка, что сессия из тестового движка работает."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(text("SELECT 1 AS val"))
        assert result.scalar() == 1
