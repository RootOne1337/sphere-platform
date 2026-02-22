# tests/test_ws/conftest.py
# TZ-03: Base fixtures for WebSocket layer tests.
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis


@pytest.fixture
def mock_ws():
    """Мок WebSocket с AsyncMock методами."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()
    ws.receive = AsyncMock()
    ws.receive_json = AsyncMock()
    ws.accept = AsyncMock()
    return ws


@pytest_asyncio.fixture
async def fake_redis():
    """FakeRedis для тестов (без decode_responses — бинарный режим для msgpack)."""
    redis = FakeRedis(decode_responses=False)
    yield redis
    await redis.aclose()


@pytest_asyncio.fixture
async def fake_redis_str():
    """FakeRedis с decode_responses=True для строковых команд."""
    redis = FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()
