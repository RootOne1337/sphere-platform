# tests/devices/conftest.py
# TZ-02 SPLIT-1: фикстуры для тестов Device CRUD.
# Переопределяет async_engine для SQLite-совместимости (те же патчи, что у TZ-01).
from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.database.engine import Base, get_db
from backend.database.redis_client import get_redis
from backend.models import *  # noqa: F401,F403 — side-effect: registers all mappers

# ---------------------------------------------------------------------------
# Patch PostgreSQL-specific types → SQLite equivalents (same as auth/conftest.py)
# ---------------------------------------------------------------------------

class Exception:
    pass


def _patch_missing_relationships() -> None:
    """
    Патчи relationships, которые требуют явного foreign_keys для SQLite.
    1. Device.org — missing back_populates to Organization.devices
    2. ScriptVersion.script — ambiguous FK paths (script_id + current_version_id)
    Вызывается до любой инициализации ORM-объектов.
    """
    from sqlalchemy import inspect as sa_inspect

    from backend.models.device import Device

    # Patch 1: Device.org — adding missing back_populates
    try:
        sa_inspect(Device).get_property("org")
    except Exception:
        from sqlalchemy.orm import relationship

        Device.org = relationship(  # type: ignore[attr-defined]
            "Organization",
            foreign_keys=[Device.__table__.c.org_id],
            back_populates="devices",
        )

    # Patch 2: ScriptVersion.script — fix ambiguous FK join.
    # Two FK paths between script_versions ↔ scripts:
    #   script_versions.script_id → scripts.id        (what ScriptVersion.script should use)
    #   scripts.current_version_id → script_versions.id (circular back-ref)
    # We set _init_args.foreign_keys.argument before mapper configuration.
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
    """JSONB → JSON, INET → String(45), ARRAY → JSON."""
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


# Применяем патчи при импорте модуля (до создания любых ORM-объектов)
_patch_missing_relationships()


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    """SQLite in-memory с патченными PG-типами."""
    _patch_missing_relationships()
    _patch_pg_types_for_sqlite()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Device-specific fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def device_org(db_session: AsyncSession):
    from backend.models.organization import Organization

    org = Organization(name="Device Test Org", slug="device-test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def device_manager_user(db_session: AsyncSession, device_org):
    from backend.models.user import User

    user = User(
        org_id=device_org.id,
        email="device_manager@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="device_manager",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession, device_org):
    from backend.models.user import User

    user = User(
        org_id=device_org.id,
        email="viewer@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="viewer",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_org(db_session: AsyncSession):
    """Другая организация — для проверки изоляции по org_id."""
    from backend.models.organization import Organization

    org = Organization(name="Other Org", slug="other-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def sample_device(db_session: AsyncSession, device_org):
    from backend.models.device import Device

    device = Device(
        org_id=device_org.id,
        name="Test LDPlayer",
        serial="emulator-5554",
        android_version="12",
        model="LDPlayer 9",
        tags=["test", "ldplayer"],
        meta={"type": "ldplayer", "ip_address": "192.168.1.100", "adb_port": 5555},
    )
    db_session.add(device)
    await db_session.flush()
    return device


@pytest_asyncio.fixture
async def org_admin_user(db_session: AsyncSession, device_org):
    from backend.models.user import User

    user = User(
        org_id=device_org.id,
        email="org_admin@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="org_admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_client(
    db_session: AsyncSession,
    mock_redis,
    org_admin_user,
    device_org,
):
    """AsyncClient с аутентификацией org_admin (полные права на devices)."""
    from httpx import ASGITransport, AsyncClient

    from backend.core.security import create_access_token
    from backend.main import app

    token, _jti = create_access_token(
        subject=str(org_admin_user.id),
        org_id=str(device_org.id),
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
async def device_client(
    db_session: AsyncSession,
    mock_redis,
    device_manager_user,
    device_org,
):
    """AsyncClient с аутентификацией device_manager.

    Переопределяет:
    - get_db → db_session с commit() = flush() для сохранения тест-изоляции
    - get_redis → FakeRedis для JWT blacklist без реального Redis при DI
    - cache_service.get_redis → FakeRedis для прямых вызовов внутри сервисов
    """
    from httpx import ASGITransport, AsyncClient

    from backend.core.security import create_access_token
    from backend.main import app

    token, _jti = create_access_token(
        subject=str(device_manager_user.id),
        org_id=str(device_org.id),
        role=device_manager_user.role,
    )

    # Подменяем commit → flush, чтобы rollback в db_session работал после теста
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
    mock_redis,
    viewer_user,
    device_org,
):
    """AsyncClient с аутентификацией viewer (только read).

    Такая же стратегия commit→flush, что и в device_client.
    """
    from httpx import ASGITransport, AsyncClient

    from backend.core.security import create_access_token
    from backend.main import app

    token, _jti = create_access_token(
        subject=str(viewer_user.id),
        org_id=str(device_org.id),
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
