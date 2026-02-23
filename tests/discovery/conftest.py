# tests/discovery/conftest.py
# TZ-02 SPLIT-5: Fixtures for Network Discovery tests.
from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.database.engine import Base, get_db
from backend.database.redis_client import get_redis
from backend.models import *  # noqa: F401,F403


def _patch_missing_relationships() -> None:
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

    from sqlalchemy.orm import RelationshipProperty

    from backend.models.script import ScriptVersion

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


@pytest_asyncio.fixture
async def disc_org(db_session: AsyncSession):
    from backend.models.organization import Organization
    org = Organization(name="Discovery Test Org", slug="discovery-test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def disc_user(db_session: AsyncSession, disc_org):
    from backend.models.user import User
    user = User(
        org_id=disc_org.id,
        email="dm_disc@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="device_manager",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def disc_workstation(db_session: AsyncSession, disc_org):
    from backend.models.workstation import Workstation
    ws = Workstation(
        org_id=disc_org.id,
        name="ws-discovery",
        hostname="ws-discovery-host",
        meta={"ip_address": "192.168.1.1"},
    )
    db_session.add(ws)
    await db_session.flush()
    return ws


@pytest_asyncio.fixture
async def disc_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
    disc_user,
    disc_org,
):
    from httpx import ASGITransport, AsyncClient

    from backend.core.security import create_access_token
    from backend.main import app

    token, _ = create_access_token(
        subject=str(disc_user.id),
        org_id=str(disc_org.id),
        role=disc_user.role,
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
