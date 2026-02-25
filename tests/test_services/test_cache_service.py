# tests/test_services/test_cache_service.py
# TZ-02 / TZ-03: Unit-тесты для CacheService (Redis).
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.cache_service import CacheService


def _make_redis():
    r = AsyncMock()
    r.set = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.delete = AsyncMock()
    r.exists = AsyncMock(return_value=0)
    r.mget = AsyncMock(return_value=[])
    pipeline = AsyncMock()
    pipeline.incr = MagicMock()
    pipeline.expire = MagicMock()
    pipeline.execute = AsyncMock(return_value=[1, True])
    r.pipeline = MagicMock(return_value=pipeline)
    return r


@pytest.fixture
def svc():
    return CacheService()


def _patch_redis(fake_redis):
    return patch("backend.services.cache_service.get_redis", AsyncMock(return_value=fake_redis))


class TestSetGetDeviceStatus:
    @pytest.mark.asyncio
    async def test_set_device_status(self, svc):
        r = _make_redis()
        with _patch_redis(r):
            await svc.set_device_status("org-1", "dev-1", "online", ttl=90)
            r.set.assert_called_once_with("device:status:org-1:dev-1", "online", ex=90)

    @pytest.mark.asyncio
    async def test_get_device_status(self, svc):
        r = _make_redis()
        r.get.return_value = "online"
        with _patch_redis(r):
            result = await svc.get_device_status("org-1", "dev-1")
            assert result == "online"

    @pytest.mark.asyncio
    async def test_get_device_status_ttl_expired(self, svc):
        r = _make_redis()
        r.get.return_value = None
        with _patch_redis(r):
            result = await svc.get_device_status("org-1", "dev-1")
            assert result is None


class TestGetAllDeviceStatuses:
    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_dict(self, svc):
        r = _make_redis()
        with _patch_redis(r):
            result = await svc.get_all_device_statuses("org-1", [])
            assert result == {}

    @pytest.mark.asyncio
    async def test_mget_returns_correct_mapping(self, svc):
        r = _make_redis()
        r.mget.return_value = ["online", None, "offline"]
        with _patch_redis(r):
            result = await svc.get_all_device_statuses("org-1", ["d1", "d2", "d3"])
            assert result == {"d1": "online", "d2": None, "d3": "offline"}


class TestBlacklist:
    @pytest.mark.asyncio
    async def test_blacklist_token(self, svc):
        r = _make_redis()
        with _patch_redis(r):
            await svc.blacklist_token("jti-123", ttl_seconds=300)
            r.set.assert_called_once_with("jwt:blacklist:jti-123", "1", ex=300)

    @pytest.mark.asyncio
    async def test_is_token_blacklisted_true(self, svc):
        r = _make_redis()
        r.exists.return_value = 1
        with _patch_redis(r):
            result = await svc.is_token_blacklisted("jti-123")
            assert result is True

    @pytest.mark.asyncio
    async def test_is_token_blacklisted_false(self, svc):
        r = _make_redis()
        r.exists.return_value = 0
        with _patch_redis(r):
            result = await svc.is_token_blacklisted("jti-abc")
            assert result is False


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_allowed(self, svc):
        r = _make_redis()
        pipe = r.pipeline.return_value
        pipe.execute.return_value = [5, True]
        with _patch_redis(r):
            allowed, count = await svc.check_rate_limit("user:123", window_seconds=60, max_requests=100)
            assert allowed is True
            assert count == 5

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, svc):
        r = _make_redis()
        pipe = r.pipeline.return_value
        pipe.execute.return_value = [101, True]
        with _patch_redis(r):
            allowed, count = await svc.check_rate_limit("user:123", max_requests=100)
            assert allowed is False
            assert count == 101


class TestGenericSetGetDelete:
    @pytest.mark.asyncio
    async def test_set(self, svc):
        r = _make_redis()
        with _patch_redis(r):
            await svc.set("my:key", "value", ttl=60)
            r.set.assert_called_once_with("my:key", "value", ex=60)

    @pytest.mark.asyncio
    async def test_get(self, svc):
        r = _make_redis()
        r.get.return_value = "stored"
        with _patch_redis(r):
            result = await svc.get("my:key")
            assert result == "stored"

    @pytest.mark.asyncio
    async def test_delete(self, svc):
        r = _make_redis()
        with _patch_redis(r):
            await svc.delete("my:key")
            r.delete.assert_called_once_with("my:key")
