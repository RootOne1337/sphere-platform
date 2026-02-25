# tests/test_agent_discovery/test_device_register.py
# TZ-12: Тесты эндпоинта POST /api/v1/devices/register
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
async def reg_org(db_session: AsyncSession):
    """Тестовая организация."""
    from backend.models.organization import Organization

    org = Organization(name="Register Test Org", slug="register-test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def enrollment_key(db_session: AsyncSession, reg_org):
    """API-ключ с правом device:register."""
    raw = "sphr_test_reg_enroll_key_abcdef1234"
    api_key = APIKey(
        org_id=reg_org.id,
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
async def no_register_key(db_session: AsyncSession, reg_org):
    """API-ключ БЕЗ права device:register."""
    raw = "sphr_test_no_register_key_xyz789"
    api_key = APIKey(
        org_id=reg_org.id,
        name="No Register Key",
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
async def reg_client(
    db_session: AsyncSession,
    mock_redis: FakeRedis,
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент без авторизации (агент)."""

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


# ── POST /api/v1/devices/register ────────────────────────────────────────────


class TestDeviceRegister:
    """Тесты автоматической регистрации устройства."""

    VALID_BODY = {
        "fingerprint": "sha256-abc123def456789012345678901234567890",
        "workstation_id": "ws-PC-FARM-01",
        "instance_index": 0,
        "android_version": "12",
        "model": "LDPlayer samsung SM-G988N",
        "location": "msk-office-1",
        "device_type": "ldplayer",
        "meta": {"ldplayer_name": "Farm-000", "clone_source": "master-v3"},
    }

    @pytest.mark.asyncio
    async def test_register_new_device(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Регистрация нового устройства — 201 + JWT токены."""
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=self.VALID_BODY,
            headers={"X-API-Key": enrollment_key},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["device_id"]
        assert data["name"] == "msk-office-1-ld-000"  # автогенерация
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["expires_in"] > 0
        assert data["server_url"]
        assert data["is_new"] is True

    @pytest.mark.asyncio
    async def test_register_idempotent_same_fingerprint(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Повторная регистрация с тем же fingerprint — re-enrollment."""
        headers = {"X-API-Key": enrollment_key}
        body = {**self.VALID_BODY, "fingerprint": "sha256-idempotent-test-unique-fp"}

        # Первая регистрация
        resp1 = await reg_client.post(
            "/api/v1/devices/register", json=body, headers=headers,
        )
        assert resp1.status_code == 201
        device_id_1 = resp1.json()["device_id"]
        assert resp1.json()["is_new"] is True

        # Повторная регистрация
        resp2 = await reg_client.post(
            "/api/v1/devices/register", json=body, headers=headers,
        )
        assert resp2.status_code == 201
        device_id_2 = resp2.json()["device_id"]
        assert resp2.json()["is_new"] is False

        # Тот же device_id
        assert device_id_1 == device_id_2

    @pytest.mark.asyncio
    async def test_register_without_api_key_returns_422(
        self, reg_client: AsyncClient
    ):
        """Без API-ключа — 422 (обязательный заголовок)."""
        resp = await reg_client.post(
            "/api/v1/devices/register", json=self.VALID_BODY,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_api_key_returns_401(
        self, reg_client: AsyncClient
    ):
        """С невалидным API-ключом — 401."""
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=self.VALID_BODY,
            headers={"X-API-Key": "sphr_test_invalid_key_999"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_register_no_register_permission_returns_403(
        self, reg_client: AsyncClient, no_register_key: str
    ):
        """API-ключ без device:register — 403."""
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=self.VALID_BODY,
            headers={"X-API-Key": no_register_key},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_register_invalid_fingerprint(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Невалидный fingerprint (спецсимволы) — 422."""
        body = {**self.VALID_BODY, "fingerprint": "drop table; --"}
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=body,
            headers={"X-API-Key": enrollment_key},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_auto_generated_name(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Автогенерация имени: {location}-{type_short}-{index:03d}."""
        body = {
            "fingerprint": "sha256-autoname-test-unique",
            "instance_index": 42,
            "location": "fra-dc-2",
            "device_type": "ldplayer",
        }
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=body,
            headers={"X-API-Key": enrollment_key},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "fra-dc-2-ld-042"

    @pytest.mark.asyncio
    async def test_register_custom_name(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Пользовательское имя — используется как есть."""
        body = {
            "fingerprint": "sha256-customname-test-unique",
            "name": "My-Device-007",
        }
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=body,
            headers={"X-API-Key": enrollment_key},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "My-Device-007"

    @pytest.mark.asyncio
    async def test_register_different_fingerprints_create_different_devices(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Разные fingerprint → разные устройства."""
        headers = {"X-API-Key": enrollment_key}

        resp1 = await reg_client.post(
            "/api/v1/devices/register",
            json={**self.VALID_BODY, "fingerprint": "sha256-device-a-unique"},
            headers=headers,
        )
        resp2 = await reg_client.post(
            "/api/v1/devices/register",
            json={**self.VALID_BODY, "fingerprint": "sha256-device-b-unique"},
            headers=headers,
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["device_id"] != resp2.json()["device_id"]

    @pytest.mark.asyncio
    async def test_register_invalid_device_type(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Недопустимый device_type — 422."""
        body = {**self.VALID_BODY, "fingerprint": "sha256-type-test", "device_type": "xbox"}
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=body,
            headers={"X-API-Key": enrollment_key},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_physical_device(
        self, reg_client: AsyncClient, enrollment_key: str
    ):
        """Регистрация физического устройства (без workstation_id)."""
        body = {
            "fingerprint": "sha256-physical-phone-unique",
            "android_version": "14",
            "model": "Samsung Galaxy S24",
            "device_type": "physical",
            "location": "msk-office-1",
        }
        resp = await reg_client.post(
            "/api/v1/devices/register",
            json=body,
            headers={"X-API-Key": enrollment_key},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "ph" in data["name"]  # msk-office-1-ph-000
