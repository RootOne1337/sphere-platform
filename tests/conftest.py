# tests/conftest.py
# CANONICAL конфигурация pytest — источник истины для всех тестов.
# Каждый TZ-этап добавляет свои фикстуры в tests/<stage>/conftest.py,
# импортируя base-фикстуры отсюда.
#
# ВАЖНО: тесты используют SQLite in-memory (aiosqlite) чтобы не требовать
# запущенного PostgreSQL в CI. RLS-политики НЕ тестируются здесь —
# для них есть отдельный job `rls-check` в ci-backend.yml.
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database.engine import Base, get_db
from backend.database.redis_client import get_redis
from backend.main import app
from backend.models import *  # noqa: F401,F403 — side-effect: registers all mappers


# ---------------------------------------------------------------------------
# Event loop — один на всю сессию (pytest-asyncio)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# SQLite in-memory engine
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def async_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Изолированная сессия БД с rollback после каждого теста.
    Использует SAVEPOINT для вложенных транзакций.
    """
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def mock_redis() -> AsyncGenerator[FakeRedis, None]:
    """FakeRedis — полная in-memory реализация команд Redis."""
    redis = FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


# ---------------------------------------------------------------------------
# Базовые объекты домена
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_org(db_session: AsyncSession):
    from backend.models.organization import Organization
    org = Organization(name="Test Org", slug="test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_org):
    from backend.models.user import User
    user = User(
        org_id=test_org.id,
        email="test@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_device(db_session: AsyncSession, test_org):
    from backend.models.device import Device
    device = Device(
        org_id=test_org.id,
        name="Test Device",
        serial="emulator-5554",
        android_version="12",
        model="LDPlayer",
    )
    db_session.add(device)
    await db_session.flush()
    return device


@pytest_asyncio.fixture
async def test_script(db_session: AsyncSession, test_org):
    from backend.models.script import Script
    script = Script(
        org_id=test_org.id,
        name="Test Script",
        description="Smoke test script",
    )
    db_session.add(script)
    await db_session.flush()
    return script


@pytest_asyncio.fixture
async def test_vpn_peer(db_session: AsyncSession, test_org, test_device):
    from backend.models.vpn_peer import VPNPeer
    peer = VPNPeer(
        org_id=test_org.id,
        device_id=test_device.id,
        public_key="dGVzdF9wdWJsaWNfa2V5X2Jhc2U2NF9wYWQ=",
        private_key_enc=b"\x00" * 60,  # encrypted stub
        tunnel_ip="10.20.0.2",
    )
    db_session.add(peer)
    await db_session.flush()
    return peer


# ---------------------------------------------------------------------------
# HTTP test client с переопределёнными зависимостями
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def authenticated_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
    test_user,
    test_org,
) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient с:
      - get_db → db_session (SQLite, rollback после теста)
      - get_redis → FakeRedis
      - Authorization header с тестовым JWT (stub)
    """
    from backend.core.security import create_access_token

    token, _jti = create_access_token(
        subject=str(test_user.id),
        org_id=str(test_org.id),
        role=test_user.role,
    )

    async def _override_get_db():
        yield db_session

    async def _override_get_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def tenant_session(db_session: AsyncSession, test_org) -> AsyncSession:
    """
    Сессия БД с установленным RLS-контекстом org_id (через SET LOCAL).
    ВНИМАНИЕ: SET LOCAL работает только внутри транзакции.
    SQLite не поддерживает SET LOCAL — этот фикстур пропускается в CI unit-тестах.
    Используется только в интеграционных тестах против реального PostgreSQL.
    """
    pytest.skip("tenant_session requires PostgreSQL — use integration test suite")
    yield db_session  # unreachable, для type hints
