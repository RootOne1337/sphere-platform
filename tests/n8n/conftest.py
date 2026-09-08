# tests/n8n/conftest.py
"""Fixtures for n8n webhook integration tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import create_access_token
from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.main import app
from backend.models import *  # noqa: F401,F403
from backend.models.organization import Organization
from backend.models.user import User


@pytest_asyncio.fixture
async def n8n_org(db_session: AsyncSession):
    org = Organization(name="N8N Org", slug="n8n-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def n8n_user(db_session: AsyncSession, n8n_org):
    user = User(
        org_id=n8n_org.id,
        email="n8nuser@sphere.local",
        password_hash="$2b$12$placeholder",
        role="org_admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_org(db_session: AsyncSession):
    org = Organization(name="Other Org", slug="other-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def other_org_user(db_session: AsyncSession, other_org):
    user = User(
        org_id=other_org.id,
        email="other@sphere.local",
        password_hash="$2b$12$placeholder",
        role="org_admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def n8n_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
    n8n_user,
    n8n_org,
):
    token, _jti = create_access_token(
        subject=str(n8n_user.id),
        org_id=str(n8n_org.id),
        role=n8n_user.role,
    )

    async def _override_db():
        # Match get_db's per-request Session lifetime; never reuse one identity
        # map for requests from different tenants. Keep the test's outer rollback.
        async with AsyncSession(
            bind=db_session.bind, expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    async def _override_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis

    with patch("backend.services.cache_service.get_redis", _override_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def other_org_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
    other_org_user,
    other_org,
):
    token, _jti = create_access_token(
        subject=str(other_org_user.id),
        org_id=str(other_org.id),
        role=other_org_user.role,
    )

    async def _override_db():
        async with AsyncSession(
            bind=db_session.bind, expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    async def _override_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis

    with patch("backend.services.cache_service.get_redis", _override_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client

    app.dependency_overrides.clear()
