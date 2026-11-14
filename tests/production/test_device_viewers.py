"""Cross-worker counts use real Redis, exact nonces, server time and bounded memory."""
import asyncio
from unittest.mock import patch

from backend.services.device_viewers import MAX_VIEWERS, DeviceViewers


async def test_two_workers_count_ten_tabs_independently_and_close_exact_session(world):
    org, device = str(world.org_a.id), str(world.dev_a.id)
    first, second = DeviceViewers(world.redis), DeviceViewers(world.redis)
    sessions = [f"{i:032x}" for i in range(10)]
    assert all(await asyncio.gather(*(first.touch(org, device, "stream", s) for s in sessions)))
    assert await second.counts(org, [device]) == {device: {"card": 0, "stream": 10}}
    assert await second.touch(org, device, "stream", sessions[0], False)
    await second.touch(org, device, "stream", sessions[0], False)
    assert await first.counts(org, [device]) == {device: {"card": 0, "stream": 9}}
    await first.touch(org, device, "card", sessions[1])
    assert await first.counts(org, [device]) == {device: {"card": 1, "stream": 9}}


async def test_abrupt_worker_exit_expires_and_a_delayed_close_does_not_remove_another_tab(world):
    org, device = str(world.org_a.id), str(world.dev_a.id)
    service = DeviceViewers(world.redis)
    old, new = "a" * 32, "b" * 32
    await service.touch(org, device, "stream", old)
    # Move one score to the actual Redis clock's expiry boundary, no 45-second sleep.
    clock = await world.redis.time()
    await world.redis.zadd(service.key(org, device, "stream"), {old: clock[0] * 1000 - 1})
    assert await service.counts(org, [device]) == {device: {"card": 0, "stream": 0}}
    await service.touch(org, device, "stream", new)
    await service.touch(org, device, "stream", old, False)
    assert await service.counts(org, [device]) == {device: {"card": 0, "stream": 1}}
    assert 0 < await world.redis.ttl(service.key(org, device, "stream")) <= 46


async def test_memory_cap_and_existing_peer_renewal_are_atomic(world):
    org, device = str(world.org_a.id), str(world.dev_a.id)
    service = DeviceViewers(world.redis)
    results = await asyncio.gather(*(service.touch(org, device, "card", f"{i:032x}") for i in range(150)))
    assert sum(results) == MAX_VIEWERS
    # Concurrent Redis arrivals need not follow coroutine creation order.
    accepted_session = f"{results.index(True):032x}"
    assert await service.touch(org, device, "card", accepted_session)
    assert (await service.counts(org, [device]))[device]["card"] == MAX_VIEWERS


async def test_other_org_can_neither_read_counts_nor_register_a_foreign_device(world):
    org, device = str(world.org_a.id), str(world.dev_a.id)
    service = DeviceViewers(world.redis)
    await service.touch(org, device, "card", "a" * 32)
    assert await service.counts(str(world.org_b.id), [device]) == {device: {"card": 0, "stream": 0}}
    with patch("backend.api.v1.devices.router.redis_client.redis", world.redis):
        response = await world.client.post(f"/api/v1/devices/{device}/viewers", json={"session": "b" * 32},
            headers=world.auth(world.users["foreign"]))
    assert response.status_code == 404
    assert (await service.counts(org, [device]))[device]["card"] == 1


async def test_authenticated_pulse_counts_tabs_and_has_private_no_store(world):
    device = str(world.dev_a.id)
    with patch("backend.api.v1.devices.router.redis_client.redis", world.redis):
        for session in ("1" * 32, "2" * 32):
            r = await world.client.post(f"/api/v1/devices/{device}/viewers", json={"session": session},
                headers=world.auth(world.users["viewer"]))
            assert r.status_code == 200, r.text
            assert r.headers["cache-control"] == "private, no-store"
        assert r.json()["counts"]["card"] == 2
        r = await world.client.post(f"/api/v1/devices/{device}/viewers", json={"session": "1" * 32, "active": False},
            headers=world.auth(world.users["viewer"]))
        assert r.json()["counts"]["card"] == 1


async def test_unavailable_counter_is_unknown_instead_of_zero(world):
    service = DeviceViewers(None)
    assert await service.counts(str(world.org_a.id), [str(world.dev_a.id)]) is None
    assert await service.touch(str(world.org_a.id), str(world.dev_a.id), "stream", "1" * 16) is False
