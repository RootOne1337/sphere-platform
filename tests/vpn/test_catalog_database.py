"""Catalog isolation must be explicit and fail closed without touching the primary DB."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from backend.services.vpn import catalog_database as catalog


@pytest.fixture
def urls(monkeypatch):
    monkeypatch.setattr(
        catalog.settings, "POSTGRES_URL", "postgresql+asyncpg://primary:private@postgres/sphere"
    )
    monkeypatch.setattr(
        catalog.settings,
        "VPN_PROFILE_POSTGRES_URL",
        SecretStr("postgresql+asyncpg://catalog:private@postgres:5432/sphere"),
    )


def test_catalog_requires_different_login_in_the_exact_same_database(urls):
    url = catalog.catalog_url()
    assert url.username == "catalog" and url.database == "sphere"


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "invalid-private-dsn",
        "sqlite:///catalog.db",
        "postgresql+asyncpg://primary:private@postgres/sphere",
        "postgresql+asyncpg://catalog@postgres/sphere",
        "postgresql+asyncpg://catalog:private@elsewhere/sphere",
        "postgresql+asyncpg://catalog:private@postgres/other",
        "postgresql+asyncpg://catalog:private@postgres:5555/sphere",
        "postgresql+asyncpg://catalog:private@postgres/sphere?user=primary",
    ],
)
def test_missing_or_misdirected_credentials_never_fall_back_or_echo_secret(urls, monkeypatch, dsn):
    monkeypatch.setattr(catalog.settings, "VPN_PROFILE_POSTGRES_URL", SecretStr(dsn))
    with pytest.raises(HTTPException) as failed:
        catalog.catalog_url()
    assert failed.value.status_code == 503
    assert failed.value.detail == "vpn_catalog_database_unavailable"
    assert "private" not in str(failed.value)


def session_fixture(monkeypatch, flags=None, failure=None):
    db = AsyncMock()
    result = Mock()
    result.mappings.return_value.one.return_value = (
        flags if flags is not None else dict.fromkeys(catalog._POLICY_KEYS, True)
    )
    db.execute.return_value = result
    db.execute.side_effect = failure
    context = AsyncMock()
    context.__aenter__.return_value = db
    factory = Mock(return_value=context)
    monkeypatch.setattr(catalog, "catalog_sessions", lambda: factory)
    bind = AsyncMock()
    monkeypatch.setattr(catalog, "bind_tenant_context", bind)
    return db, bind, context


@pytest.mark.asyncio
async def test_actual_connection_is_scoped_and_checked_before_yielding_to_catalog(monkeypatch):
    db, bind, context = session_fixture(monkeypatch)
    user = SimpleNamespace(org_id=uuid.uuid4())
    dependency = catalog.get_vpn_catalog_db(user)
    assert await anext(dependency) is db
    bind.assert_awaited_once_with(db, str(user.org_id))
    db.execute.assert_awaited_once_with(catalog._ROLE_CHECK, {"org_id": str(user.org_id)})
    await dependency.aclose()
    context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", sorted(catalog._POLICY_KEYS))
async def test_privileged_owner_unscoped_and_underprivileged_sessions_fail_closed(
    monkeypatch, flag
):
    flags = dict.fromkeys(catalog._POLICY_KEYS, True) | {flag: False}
    db, _, context = session_fixture(monkeypatch, flags)
    with pytest.raises(HTTPException) as failed:
        await anext(catalog.get_vpn_catalog_db(SimpleNamespace(org_id=uuid.uuid4())))
    assert (
        failed.value.status_code == 503
        and failed.value.detail == "vpn_catalog_database_policy_unavailable"
    )
    db.commit.assert_not_awaited()
    context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_schema_or_database_errors_are_bounded_and_do_not_echo_driver_message(
    monkeypatch,
):
    _, _, context = session_fixture(
        monkeypatch, failure=OperationalError("private-sql", {}, Exception("private-password"))
    )
    with pytest.raises(HTTPException) as failed:
        await anext(catalog.get_vpn_catalog_db(SimpleNamespace(org_id=uuid.uuid4())))
    assert (
        failed.value.status_code == 503
        and failed.value.detail == "vpn_catalog_database_unavailable"
    )
    assert "private" not in str(failed.value)
    context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_disposes_only_dedicated_pool(monkeypatch):
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(catalog, "_engine", engine)
    monkeypatch.setattr(catalog, "_sessions", object())
    await catalog.close_catalog_database()
    engine.dispose.assert_awaited_once()
    assert catalog._engine is None and catalog._sessions is None


def test_pool_is_lazy_bounded_and_never_uses_primary_connection(urls, monkeypatch):
    monkeypatch.setattr(catalog, "_engine", None)
    monkeypatch.setattr(catalog, "_sessions", None)
    engine, factory = object(), object()
    create = Mock(return_value=engine)
    make = Mock(return_value=factory)
    monkeypatch.setattr(catalog, "create_async_engine", create)
    monkeypatch.setattr(catalog, "async_sessionmaker", make)
    assert catalog.catalog_sessions() is factory
    assert catalog.catalog_sessions() is factory
    create.assert_called_once()
    assert create.call_args.args[0].username == "catalog"
    assert (
        create.call_args.kwargs["pool_size"] == 2 and create.call_args.kwargs["max_overflow"] == 0
    )
    assert create.call_args.kwargs["hide_parameters"] is True
