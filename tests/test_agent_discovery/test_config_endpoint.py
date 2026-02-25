# tests/test_agent_discovery/test_config_endpoint.py
# TZ-12: Тесты эндпоинта GET /api/v1/config/agent
from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.main import app
from backend.models.api_key import APIKey


@pytest_asyncio.fixture
async def config_org(db_session: AsyncSession):
    """Тестовая организация для config-тестов."""
    from backend.models.organization import Organization

    org = Organization(name="Config Test Org", slug="config-test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def enrollment_api_key(db_session: AsyncSession, config_org):
    """API-ключ с правом device:register для enrollment."""
    raw = "sphr_test_enrollment_key_abc123def456"
    api_key = APIKey(
        org_id=config_org.id,
        name="Enrollment Key",
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        key_prefix="sphr_test",
        type="agent",
        permissions=["device:register"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()
    return raw


@pytest_asyncio.fixture
async def readonly_api_key(db_session: AsyncSession, config_org):
    """API-ключ БЕЗ права device:register."""
    raw = "sphr_test_readonly_key_xyz789"
    api_key = APIKey(
        org_id=config_org.id,
        name="Readonly Key",
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        key_prefix="sphr_test",
        type="agent",
        permissions=["device:read"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()
    return raw


@pytest_asyncio.fixture
async def anon_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент без аутентификации (агент при первом запуске)."""

    async def _db():
        yield db_session

    async def _redis():
        return mock_redis

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ── GET /api/v1/config/agent ─────────────────────────────────────────────────


class TestGetAgentConfig:
    """Тесты эндпоинта GET /api/v1/config/agent."""

    @pytest.mark.asyncio
    async def test_config_without_auth_returns_base_config(self, anon_client: AsyncClient):
        """Без API-ключа возвращается базовый конфиг (bootstrap)."""
        resp = await anon_client.get("/api/v1/config/agent")
        assert resp.status_code == 200
        data = resp.json()

        assert "server_url" in data
        assert data["ws_path"] == "/ws/android"
        assert data["config_version"] >= 1
        assert isinstance(data["features"], dict)
        assert data["enrollment_allowed"] is False
        assert data["org_id"] is None

    @pytest.mark.asyncio
    async def test_config_with_enrollment_key(
        self, anon_client: AsyncClient, enrollment_api_key: str, config_org
    ):
        """С enrollment API-ключом — enrollment_allowed=true + org_id."""
        resp = await anon_client.get(
            "/api/v1/config/agent",
            headers={"X-API-Key": enrollment_api_key},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["enrollment_allowed"] is True
        assert data["org_id"] == str(config_org.id)
        assert data["server_url"]  # не пустой

    @pytest.mark.asyncio
    async def test_config_with_readonly_key(
        self, anon_client: AsyncClient, readonly_api_key: str, config_org
    ):
        """С readonly ключом — enrollment_allowed=false, но org_id есть."""
        resp = await anon_client.get(
            "/api/v1/config/agent",
            headers={"X-API-Key": readonly_api_key},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["enrollment_allowed"] is False
        assert data["org_id"] == str(config_org.id)

    @pytest.mark.asyncio
    async def test_config_with_invalid_key_returns_401(self, anon_client: AsyncClient):
        """С невалидным API-ключом — 401."""
        resp = await anon_client.get(
            "/api/v1/config/agent",
            headers={"X-API-Key": "sphr_test_invalid_key_12345"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_config_response_has_all_fields(self, anon_client: AsyncClient):
        """Ответ содержит все обязательные поля."""
        resp = await anon_client.get("/api/v1/config/agent")
        data = resp.json()

        required_fields = [
            "server_url", "ws_path", "config_version", "environment",
            "config_poll_interval_seconds", "features", "min_agent_version",
            "enrollment_allowed",
        ]
        for field in required_fields:
            assert field in data, f"Отсутствует поле '{field}'"

    @pytest.mark.asyncio
    async def test_config_features_structure(self, anon_client: AsyncClient):
        """Features содержит ожидаемые флаги."""
        resp = await anon_client.get("/api/v1/config/agent")
        features = resp.json()["features"]

        assert "telemetry_enabled" in features
        assert "streaming_enabled" in features
        assert "auto_register" in features
        assert isinstance(features["telemetry_enabled"], bool)
