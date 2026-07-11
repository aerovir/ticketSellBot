"""
Pytest conftest — общие фикстуры для тестов TicketBot.

Фикстуры:
  db_session  — асинхронная сессия с rollback после каждого теста
                (использует SAVEPOINT + перехват commit)
  user_svc    — UserService
  event_svc   — EventService
  ticket_svc  — TicketService
  sample_event — создаёт тестовое мероприятие
"""

import os
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import NullPool

from app.core.models import Base, User, Event, Ticket, Channel
from app.core.models import PlatformType
from app.core.services import UserService, EventService, TicketService, ChannelService


# ─── Настройка тестовой БД ─────────────────────────────────────

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/ticketbot_test",
)


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Создаёт тестовый движок и все таблицы."""
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        pytest.skip("Тестовая БД недоступна. Запустите PostgreSQL.")

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Асинхронная сессия с изоляцией через SAVEPOINT.

    Схема:
    1. Открываем соединение и внешнюю транзакцию (BEGIN)
    2. Создаём SAVEPOINT внутри неё
    3. Тест может делать commit() — он закоммитит savepoint,
       а мы пересоздадим savepoint сразу после
    4. В конце rollback внешней транзакции откатывает всё
    """
    connection = await test_engine.connect()
    transaction = await connection.begin()

    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
    )

    # Создаём начальный savepoint
    await connection.execute(text("SAVEPOINT test_sp"))

    # Перехватываем commit: превращаем его в коммит savepoint
    # с немедленным пересозданием
    original_commit = session.commit

    async def savepoint_commit():
        await original_commit()
        # После commit savepoint освобождён — создаём новый
        await connection.execute(text("SAVEPOINT test_sp"))

    session.commit = savepoint_commit

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


# ─── Фабрики моделей ────────────────────────────────────────────

@pytest_asyncio.fixture
async def sample_channel(db_session: AsyncSession) -> Channel:
    """Создаёт тестовый канал."""
    svc = ChannelService(db_session)
    channel = await svc.create(
        telegram_channel_id="test_channel_1",
        admin_telegram_user_id="test_12345",
        title="Test Channel",
    )
    return channel


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Создаёт тестового пользователя."""
    svc = UserService(db_session)
    user = await svc.get_or_create(
        platform=PlatformType.telegram,
        platform_user_id="test_12345",
        name="Test User",
    )
    return user


@pytest_asyncio.fixture
async def sample_event(db_session: AsyncSession, sample_channel: Channel) -> Event:
    """Создаёт тестовое мероприятие."""
    svc = EventService(db_session)
    event = await svc.create(
        title="Тестовое мероприятие",
        description="Описание тестового мероприятия",
        date=datetime.now(timezone.utc) + timedelta(days=14),
        location="Москва",
        price=1000.0,
        total_tickets=100,
        channel_id=sample_channel.id,
    )
    return event


@pytest_asyncio.fixture
async def sample_past_event(db_session: AsyncSession, sample_channel: Channel) -> Event:
    """Создаёт прошедшее мероприятие."""
    svc = EventService(db_session)
    event = await svc.create(
        title="Прошедшее мероприятие",
        description="Уже прошло",
        date=datetime.now(timezone.utc) - timedelta(days=1),
        location="Москва",
        price=500.0,
        total_tickets=10,
        channel_id=sample_channel.id,
    )
    return event


@pytest_asyncio.fixture
async def sample_ticket(
    db_session: AsyncSession,
    sample_user: User,
    sample_event: Event,
) -> Ticket:
    """Создаёт тестовый билет."""
    svc = TicketService(db_session)
    ticket = await svc.buy_ticket(sample_user.id, sample_event.id)
    return ticket


# ─── Сервисы ─────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def user_svc(db_session: AsyncSession) -> UserService:
    return UserService(db_session)


@pytest_asyncio.fixture
async def event_svc(db_session: AsyncSession) -> EventService:
    return EventService(db_session)


@pytest_asyncio.fixture
async def ticket_svc(db_session: AsyncSession) -> TicketService:
    return TicketService(db_session)
