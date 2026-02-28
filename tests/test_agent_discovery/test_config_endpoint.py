# tests/test_agent_discovery/test_config_endpoint.py
# TZ-12: Тесты эндпоинта GET /api/v1/config/agent
from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

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


class TestConfigFromAgentConfigFile:
    """Тесты загрузки конфигурации из agent-config/environments/{env}.json."""

    @pytest.mark.asyncio
    async def test_config_loads_from_agent_config_file(
        self, anon_client: AsyncClient, tmp_path: Path,
    ):
        """Конфиг загружается из файла agent-config/environments/{env}.json."""
        # Создаём временную директорию с конфигом
        env_dir = tmp_path / "environments"
        env_dir.mkdir()
        test_config = {
            "config_version": 42,
            "server_url": "http://test-server:9000",
            "ws_path": "/ws/test",
            "enrollment_api_key": "sphr_test_key_from_file",
            "environment": "test-env",
            "config_poll_interval_seconds": 1800,
            "features": {
                "telemetry_enabled": False,
                "streaming_enabled": True,
                "ota_enabled": True,
                "auto_register": True,
            },
        }
        (env_dir / "test.json").write_text(json.dumps(test_config))

        with patch("backend.api.v1.config.router.settings") as mock_settings:
            mock_settings.AGENT_CONFIG_DIR = str(tmp_path)
            mock_settings.AGENT_CONFIG_ENV = "test"
            mock_settings.ENVIRONMENT = "test-env"
            mock_settings.SERVER_PUBLIC_URL = "http://fallback:8000"
            mock_settings.AGENT_CONFIG_CACHE_TTL = 0  # Без Redis-кэша в тесте

            resp = await anon_client.get("/api/v1/config/agent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_url"] == "http://test-server:9000"
        assert data["config_version"] == 42
        assert data["ws_path"] == "/ws/test"
        assert data["environment"] == "test-env"
        assert data["enrollment_api_key"] == "sphr_test_key_from_file"
        assert data["features"]["telemetry_enabled"] is False
        assert data["features"]["ota_enabled"] is True
        assert data["config_poll_interval_seconds"] == 1800

    @pytest.mark.asyncio
    async def test_config_fallback_when_file_missing(
        self, anon_client: AsyncClient, tmp_path: Path,
    ):
        """Если файл отсутствует — fallback на Settings.SERVER_PUBLIC_URL."""
        with patch("backend.api.v1.config.router.settings") as mock_settings:
            mock_settings.AGENT_CONFIG_DIR = str(tmp_path)
            mock_settings.AGENT_CONFIG_ENV = "nonexistent"
            mock_settings.ENVIRONMENT = "development"
            mock_settings.SERVER_PUBLIC_URL = "http://fallback-server:8000"
            mock_settings.AGENT_CONFIG_CACHE_TTL = 0

            resp = await anon_client.get("/api/v1/config/agent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_url"] == "http://fallback-server:8000"
        assert data["enrollment_api_key"] is None

    @pytest.mark.asyncio
    async def test_config_response_has_enrollment_api_key_field(self, anon_client: AsyncClient):
        """Ответ содержит поле enrollment_api_key."""
        resp = await anon_client.get("/api/v1/config/agent")
        data = resp.json()
        assert "enrollment_api_key" in data

    @pytest.mark.asyncio
    async def test_config_empty_server_url_fallback_to_settings(
        self, anon_client: AsyncClient, tmp_path: Path,
    ):
        """Если server_url в JSON пустой — fallback на SERVER_PUBLIC_URL (production сценарий)."""
        env_dir = tmp_path / "environments"
        env_dir.mkdir()
        # Production: server_url пустой, enrollment_api_key задан
        prod_config = {
            "config_version": 2,
            "server_url": "",
            "ws_path": "/ws/android",
            "enrollment_api_key": "sphr_prod_enrollment_key_2025",
            "environment": "production",
            "features": {"auto_register": True},
        }
        (env_dir / "production.json").write_text(json.dumps(prod_config))

        with patch("backend.api.v1.config.router.settings") as mock_settings:
            mock_settings.AGENT_CONFIG_DIR = str(tmp_path)
            mock_settings.AGENT_CONFIG_ENV = "production"
            mock_settings.ENVIRONMENT = "production"
            mock_settings.SERVER_PUBLIC_URL = "https://adb.leetpc.com"
            mock_settings.AGENT_CONFIG_CACHE_TTL = 0

            resp = await anon_client.get("/api/v1/config/agent")

        assert resp.status_code == 200
        data = resp.json()
        # server_url должен взяться из SERVER_PUBLIC_URL, а не из пустого JSON
        assert data["server_url"] == "https://adb.leetpc.com"
        # enrollment_api_key должен прийти из файла
        assert data["enrollment_api_key"] == "sphr_prod_enrollment_key_2025"
        assert data["features"]["auto_register"] is True

    @pytest.mark.asyncio
    async def test_config_redis_cache_used(
        self, anon_client: AsyncClient, mock_redis: FakeRedis, tmp_path: Path,
    ):
        """Второй запрос использует Redis-кэш, а не файл."""
        env_dir = tmp_path / "environments"
        env_dir.mkdir()
        test_config = {
            "server_url": "http://cached-server:9000",
            "enrollment_api_key": "sphr_cached_key",
            "features": {"auto_register": True},
        }
        (env_dir / "cached.json").write_text(json.dumps(test_config))

        with patch("backend.api.v1.config.router.settings") as mock_settings:
            mock_settings.AGENT_CONFIG_DIR = str(tmp_path)
            mock_settings.AGENT_CONFIG_ENV = "cached"
            mock_settings.ENVIRONMENT = "development"
            mock_settings.SERVER_PUBLIC_URL = "http://fallback:8000"
            mock_settings.AGENT_CONFIG_CACHE_TTL = 300

            # Первый запрос — из файла, сохраняет в кэш
            resp1 = await anon_client.get("/api/v1/config/agent")
            assert resp1.status_code == 200
            assert resp1.json()["server_url"] == "http://cached-server:9000"

            # Удаляем файл
            (env_dir / "cached.json").unlink()

            # Второй запрос — из Redis-кэша (файла уже нет)
            resp2 = await anon_client.get("/api/v1/config/agent")
            assert resp2.status_code == 200
            assert resp2.json()["server_url"] == "http://cached-server:9000"
