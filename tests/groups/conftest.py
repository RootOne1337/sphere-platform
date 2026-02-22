# tests/groups/conftest.py
# TZ-02 SPLIT-2: Fixtures for Device Groups & Tags tests.
from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database.engine import Base, get_db
from backend.database.redis_client import get_redis
from backend.models import *  # noqa: F401,F403


# ── PG type patches (same as devices/conftest.py) ────────────────────────────

def _patch_missing_relationships() -> None:
    """Patch Device.org and ScriptVersion.script for SQLite compatibility."""
    from sqlalchemy import inspect as sa_inspect
    from backend.models.device import Device

    try:
        sa_inspect(Device).get_property("org")
    except Exception:
        from sqlalchemy.orm import relationship
        Device.org = relationship(  # type: ignore[attr-defined]
            "Organization",
            foreign_keys=[Device.__table__.c.org_id],
            back_populates="devices",
        )

    from backend.models.script import ScriptVersion
    from sqlalchemy.orm import RelationshipProperty

    for prop in ScriptVersion.__mapper__._props.values():  # type: ignore[attr-defined]
        if isinstance(prop, RelationshipProperty) and prop.key == "script":
            if prop._init_args.foreign_keys.argument is None:
                prop._init_args.foreign_keys.argument = [
                    ScriptVersion.__table__.c.script_id
                ]
            break


def _patch_pg_types_for_sqlite() -> None:
    from sqlalchemy import JSON, String
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB

    for table in Base.metadata.tables.values():
        for column in table.columns:
            col_type = type(column.type)
            if col_type is JSONB or col_type.__name__ == "JSONB":
                column.type = JSON()
            elif col_type.__name__ == "INET":
                column.type = String(45)
            elif col_type is ARRAY or col_type.__name__ == "ARRAY":
                column.type = JSON()


_patch_missing_relationships()


# ── Engine ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def async_engine():
    _patch_missing_relationships()
    _patch_pg_types_for_sqlite()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Domain fixtures ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def group_org(db_session: AsyncSession):
    from backend.models.organization import Organization
    org = Organization(name="Group Test Org", slug="group-test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def device_manager_user(db_session: AsyncSession, group_org):
    from backend.models.user import User
    user = User(
        org_id=group_org.id,
        email="dm_groups@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="device_manager",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def org_admin_user(db_session: AsyncSession, group_org):
    from backend.models.user import User
    user = User(
        org_id=group_org.id,
        email="admin_groups@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="org_admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession, group_org):
    from backend.models.user import User
    user = User(
        org_id=group_org.id,
        email="viewer_groups@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="viewer",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_group(db_session: AsyncSession, group_org):
    from backend.models.device_group import DeviceGroup
    group = DeviceGroup(
        org_id=group_org.id,
        name="Farm A",
        description="Test farm",
        color="#FF5733",
    )
    db_session.add(group)
    await db_session.flush()
    return group


@pytest_asyncio.fixture
async def group_device(db_session: AsyncSession, group_org):
    from backend.models.device import Device
    device = Device(
        org_id=group_org.id,
        name="Emulator-1",
        serial="emulator-group-01",
        tags=["farm", "test"],
        meta={"type": "ldplayer"},
    )
    db_session.add(device)
    await db_session.flush()
    return device


# ── HTTP client fixtures ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def dm_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
    device_manager_user,
    group_org,
):
    """device_manager client for group tests."""
    from httpx import ASGITransport, AsyncClient
    from backend.core.security import create_access_token
    from backend.main import app

    token, _ = create_access_token(
        subject=str(device_manager_user.id),
        org_id=str(group_org.id),
        role=device_manager_user.role,
    )

    original_commit = db_session.commit
    db_session.commit = db_session.flush  # type: ignore[method-assign]

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _fake_get_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _fake_get_redis

    with patch("backend.services.cache_service.get_redis", _fake_get_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client

    db_session.commit = original_commit  # type: ignore[method-assign]
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
    org_admin_user,
    group_org,
):
    """org_admin client for delete/protected operations."""
    from httpx import ASGITransport, AsyncClient
    from backend.core.security import create_access_token
    from backend.main import app

    token, _ = create_access_token(
        subject=str(org_admin_user.id),
        org_id=str(group_org.id),
        role=org_admin_user.role,
    )

    original_commit = db_session.commit
    db_session.commit = db_session.flush  # type: ignore[method-assign]

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _fake_get_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _fake_get_redis

    with patch("backend.services.cache_service.get_redis", _fake_get_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client

    db_session.commit = original_commit  # type: ignore[method-assign]
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def viewer_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
    viewer_user,
    group_org,
):
    from httpx import ASGITransport, AsyncClient
    from backend.core.security import create_access_token
    from backend.main import app

    token, _ = create_access_token(
        subject=str(viewer_user.id),
        org_id=str(group_org.id),
        role=viewer_user.role,
    )

    original_commit = db_session.commit
    db_session.commit = db_session.flush  # type: ignore[method-assign]

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _fake_get_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _fake_get_redis

    with patch("backend.services.cache_service.get_redis", _fake_get_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client

    db_session.commit = original_commit  # type: ignore[method-assign]
    app.dependency_overrides.clear()
