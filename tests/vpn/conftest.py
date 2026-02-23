# tests/vpn/conftest.py  TZ-06 SPLIT-1..5 fixtures
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

from backend.services.vpn.awg_config import AWGConfigBuilder
from backend.services.vpn.dependencies import get_key_cipher
from backend.services.vpn.event_publisher import EventPublisher
from backend.services.vpn.ip_pool import IPPoolAllocator
from backend.services.vpn.pool_service import VPNPoolService

# ---------------------------------------------------------------------------
# SPLIT-1 fixtures (unchanged)
# ---------------------------------------------------------------------------

@pytest.fixture
def awg_builder() -> AWGConfigBuilder:
    return AWGConfigBuilder(
        server_public_key="dGVzdF9zZXJ2ZXJfcHVibGljX2tleV9iYXNlNjQ=",
        server_endpoint="vpn.test.local:51820",
        dns="1.1.1.1, 8.8.8.8",
        server_psk_enabled=True,
    )


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def fernet_cipher(fernet_key: str) -> Fernet:
    return Fernet(fernet_key.encode())


# ---------------------------------------------------------------------------
# SPLIT-2 fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def pool_redis() -> FakeRedis:
    """Separate FakeRedis instance for pool tests (decode_responses=True)."""
    redis = FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


@pytest.fixture
def ip_pool(pool_redis) -> IPPoolAllocator:
    return IPPoolAllocator(pool_redis, subnet="10.100.0.0/24")


@pytest_asyncio.fixture
async def pool_service(db_session, pool_redis, awg_builder, fernet_cipher) -> VPNPoolService:
    svc = VPNPoolService(
        db=db_session,
        ip_pool=IPPoolAllocator(pool_redis, subnet="10.100.0.0/24"),
        config_builder=awg_builder,
        key_cipher=fernet_cipher,
        wg_router_url="http://wg-router.test",
    )
    # Mock WG Router calls so tests don't need a real WG server
    svc._add_peer_to_server = AsyncMock(return_value=None)
    svc._remove_peer_from_server = AsyncMock(return_value=None)
    yield svc
    await svc.close()


# ---------------------------------------------------------------------------
# SPLIT-3 fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_publisher() -> EventPublisher:
    publisher = EventPublisher()
    publisher.send_command_to_device = AsyncMock(return_value=True)
    return publisher


# ---------------------------------------------------------------------------
# SPLIT-5 HTTP client fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def vpn_admin_client(db_session, pool_redis, fernet_cipher, test_org) -> AsyncClient:
    """HTTP client authenticated as org_admin, with DB + Redis overrides."""
    from backend.core.dependencies import get_current_user
    from backend.database.engine import get_db
    from backend.database.redis_client import get_redis
    from backend.main import app

    mock_user = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=test_org.id,
        role="org_admin",
        email="admin@vpn.test",
    )

    async def _db_gen():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = _db_gen
    app.dependency_overrides[get_redis] = lambda: pool_redis
    app.dependency_overrides[get_key_cipher] = lambda: fernet_cipher

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def vpn_manager_client(db_session, pool_redis, fernet_cipher, test_org) -> AsyncClient:
    """HTTP client authenticated as device_manager."""
    from backend.core.dependencies import get_current_user
    from backend.database.engine import get_db
    from backend.database.redis_client import get_redis
    from backend.main import app

    mock_user = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=test_org.id,
        role="device_manager",
        email="manager@vpn.test",
    )

    async def _db_gen():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = _db_gen
    app.dependency_overrides[get_redis] = lambda: pool_redis
    app.dependency_overrides[get_key_cipher] = lambda: fernet_cipher

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()
