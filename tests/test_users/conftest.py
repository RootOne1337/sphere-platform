# tests/test_users/conftest.py
"""Fixtures for user management HTTP integration tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import create_access_token, hash_password
from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.main import app
from backend.models import *  # noqa: F401,F403
from backend.models.organization import Organization
from backend.models.user import User


@pytest_asyncio.fixture
async def users_org(db_session: AsyncSession):
    org = Organization(name="Users Test Org", slug="users-test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession, users_org):
    """org_owner — can change roles, create/deactivate users."""
    user = User(
        org_id=users_org.id,
        email="owner@sphere.local",
        password_hash=hash_password("pw"),
        role="org_owner",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession, users_org):
    """org_admin — can list/create/deactivate but NOT change roles."""
    user = User(
        org_id=users_org.id,
        email="admin@sphere.local",
        password_hash=hash_password("pw"),
        role="org_admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def subuser(db_session: AsyncSession, users_org):
    """A regular viewer user to be managed."""
    user = User(
        org_id=users_org.id,
        email="viewer@example.com",
        password_hash=hash_password("pw"),
        role="viewer",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def second_owner(db_session: AsyncSession, users_org):
    """Second org_owner — needed for last-owner guard tests."""
    user = User(
        org_id=users_org.id,
        email="owner2@sphere.local",
        password_hash=hash_password("pw"),
        role="org_owner",
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _make_client(db_session, mock_redis, user, org):
    token, _jti = create_access_token(
        subject=str(user.id),
        org_id=str(org.id),
        role=user.role,
    )

    async def _db():
        yield db_session

    async def _redis():
        return mock_redis

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest_asyncio.fixture
async def owner_client(db_session, mock_redis, owner_user, users_org):
    async def _fake_redis():
        return mock_redis
    with patch("backend.services.cache_service.get_redis", _fake_redis):
        async with _make_client(db_session, mock_redis, owner_user, users_org) as c:
            yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(db_session, mock_redis, admin_user, users_org):
    async def _fake_redis():
        return mock_redis
    with patch("backend.services.cache_service.get_redis", _fake_redis):
        async with _make_client(db_session, mock_redis, admin_user, users_org) as c:
            yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def viewer_client(db_session, mock_redis, subuser, users_org):
    """Viewer — should get 403 on all user-management endpoints."""
    async def _fake_redis():
        return mock_redis
    with patch("backend.services.cache_service.get_redis", _fake_redis):
        async with _make_client(db_session, mock_redis, subuser, users_org) as c:
            yield c
    app.dependency_overrides.clear()
