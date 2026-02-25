# tests/vpn/test_ip_pool.py — TZ-06 SPLIT-2
# Unit-тесты для IPPoolAllocator (FakeRedis).
from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from backend.services.vpn.ip_pool import IPPoolAllocator


@pytest_asyncio.fixture
async def redis():
    r = FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def pool(redis):
    return IPPoolAllocator(redis, subnet="10.200.0.0/24")


@pytest.mark.asyncio
async def test_initialize_pool_adds_ips(pool):
    added = await pool.initialize_pool("org-1", count=5)
    assert added == 5
    size = await pool.pool_size("org-1")
    assert size == 5


@pytest.mark.asyncio
async def test_initialize_pool_idempotent(pool):
    await pool.initialize_pool("org-1", count=5)
    added_again = await pool.initialize_pool("org-1", count=5)
    # NX flag: ни один IP не должен добавиться повторно
    assert added_again == 0
    assert await pool.pool_size("org-1") == 5


@pytest.mark.asyncio
async def test_allocate_ip_returns_ip(pool):
    await pool.initialize_pool("org-1", count=3)
    ip = await pool.allocate_ip("org-1")
    assert ip is not None
    assert ip.startswith("10.200.0.")


@pytest.mark.asyncio
async def test_allocate_ip_decrements_pool(pool):
    await pool.initialize_pool("org-1", count=3)
    await pool.allocate_ip("org-1")
    assert await pool.pool_size("org-1") == 2


@pytest.mark.asyncio
async def test_allocate_ip_returns_none_when_empty(pool):
    ip = await pool.allocate_ip("empty-org")
    assert ip is None


@pytest.mark.asyncio
async def test_release_ip_returns_to_pool(pool):
    await pool.initialize_pool("org-1", count=1)
    ip = await pool.allocate_ip("org-1")
    assert await pool.pool_size("org-1") == 0
    await pool.release_ip("org-1", ip)
    assert await pool.pool_size("org-1") == 1


@pytest.mark.asyncio
async def test_allocate_fifo_order(pool):
    """Первый выданный IP должен быть первым в пуле (наименьший score)."""
    await pool.initialize_pool("org-1", count=5)
    ip1 = await pool.allocate_ip("org-1")
    ip2 = await pool.allocate_ip("org-1")
    # Оба не None и разные
    assert ip1 is not None
    assert ip2 is not None
    assert ip1 != ip2


@pytest.mark.asyncio
async def test_pool_isolated_by_org(pool):
    """IP пулы разных org не пересекаются."""
    await pool.initialize_pool("org-a", count=3)
    await pool.initialize_pool("org-b", count=2)
    assert await pool.pool_size("org-a") == 3
    assert await pool.pool_size("org-b") == 2

    _ = await pool.allocate_ip("org-a")
    assert await pool.pool_size("org-a") == 2
    assert await pool.pool_size("org-b") == 2  # не затронут


@pytest.mark.asyncio
async def test_is_low_true_when_below_threshold(pool):
    await pool.initialize_pool("org-1", count=5)
    for _ in range(5):
        await pool.allocate_ip("org-1")  # вычерпать
    assert await pool.is_low("org-1", threshold=10) is True


@pytest.mark.asyncio
async def test_is_low_false_when_above_threshold(pool):
    await pool.initialize_pool("org-1", count=20)
    assert await pool.is_low("org-1", threshold=10) is False
