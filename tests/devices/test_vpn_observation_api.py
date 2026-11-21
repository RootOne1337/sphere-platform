"""Main list/detail responses must expose independent VPN freshness consistently."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import msgpack
import pytest
from fakeredis.aioredis import FakeRedis
from redis.exceptions import ConnectionError
from sqlalchemy import update

from backend.api.v1.devices import router as devices_router
from backend.api.v1.devices.router import get_status_cache
from backend.main import app
from backend.models.device import Device, DeviceStatus
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache


@pytest.mark.parametrize("flag,age,expected,state", [
    (True, 0, True, "fresh"), (False, 0, False, "fresh"),
    (True, 121, None, "stale"), (True, None, None, "unknown"),
])
async def test_list_and_detail_expose_vpn_observation_without_changing_presence(device_client, flag, age, expected, state):
    created = await device_client.post('/api/v1/devices', json={'name': 'VPN observation', 'serial': 'vpn-observation'})
    assert created.status_code == 201
    device_id = created.json()['id']
    redis = FakeRedis(decode_responses=False)
    cache = DeviceStatusCache(redis)
    now = datetime.now(timezone.utc)
    observed = now - timedelta(seconds=age) if age is not None else None
    await cache.set_status(device_id, DeviceLiveStatus(
        device_id=device_id, status='online', ws_session_id='api-session',
        last_heartbeat=now, vpn_active=flag, vpn_observed_at=observed,
        vpn_observed_session_id='api-session' if observed else None,
    ))

    async def override_cache():
        return cache

    app.dependency_overrides[get_status_cache] = override_cache
    try:
        listed = await device_client.get('/api/v1/devices?per_page=100')
        detailed = await device_client.get(f'/api/v1/devices/{device_id}')
        assert listed.status_code == detailed.status_code == 200
        row = next(item for item in listed.json()['items'] if item['id'] == device_id)
        for payload in [row, detailed.json()]:
            assert payload['status'] == 'online'
            assert payload['vpn_active'] is expected
            assert payload['vpn_observation_state'] == state
            assert payload['vpn_observation_max_age_seconds'] == 120
            if observed:
                assert datetime.fromisoformat(payload['vpn_observed_at']) == observed
            else:
                assert payload['vpn_observed_at'] is None
        assert listed.json()['status_counts']['online'] >= 1
    finally:
        app.dependency_overrides.pop(get_status_cache, None)
        await redis.aclose()


async def test_presence_lookup_failure_is_counted_without_polling_log_spam(monkeypatch, caplog):
    from prometheus_client import REGISTRY

    redis = AsyncMock()
    redis.mget.side_effect = ConnectionError("fixture")
    cache = DeviceStatusCache(redis)
    monkeypatch.setattr(devices_router, "_next_presence_warning", 0)
    monkeypatch.setattr(devices_router, "monotonic", lambda: 100.0)
    labels = {"reason": "lookup_error"}
    metric = "sphere_inventory_presence_failures_total"
    before = REGISTRY.get_sample_value(metric, labels) or 0

    for _ in range(4):
        observed, _, available = await devices_router._read_inventory_presence(cache, ["fixture"])
        assert observed == {} and available is False

    assert REGISTRY.get_sample_value(metric, labels) == before + 4
    assert caplog.text.count("Device presence lookup failed") == 1


@pytest.mark.parametrize('condition,expected,available', [
    ('absent-client', 'unknown', False), ('read-failed', 'unknown', False), ('absent-key', 'offline', True),
    ('malformed', 'unknown', True), ('wrong-device', 'unknown', True),
    ('missing-heartbeat', 'unknown', True), ('missing-session', 'unknown', True), ('stale-heartbeat', 'unknown', True),
])
async def test_list_and_detail_agree_when_redis_presence_cannot_confirm_online(device_client, db_session, condition, expected, available):
    created = await device_client.post('/api/v1/devices', json={'name': 'Previously online'})
    assert created.status_code == 201
    device_id = created.json()['id']
    await db_session.execute(update(Device).where(Device.id == UUID(device_id)).values(last_status=DeviceStatus.ONLINE))
    await db_session.flush()

    redis = FakeRedis(decode_responses=False)
    cache = DeviceStatusCache(None if condition == 'absent-client' else redis)
    if condition == 'read-failed':
        redis.mget = AsyncMock(side_effect=ConnectionError('fixture'))
    elif condition == 'malformed':
        await redis.set(cache._key(device_id), msgpack.packb({'status': 'online'}))
    elif condition not in ('absent-client', 'absent-key'):
        now = datetime.now(timezone.utc)
        heartbeat = None if condition == 'missing-heartbeat' else now - timedelta(seconds=121 if condition == 'stale-heartbeat' else 0)
        await cache.set_status(device_id, DeviceLiveStatus(
            device_id='foreign' if condition == 'wrong-device' else device_id,
            status='online', ws_session_id=None if condition == 'missing-session' else 'fixture',
            last_heartbeat=heartbeat, vpn_active=True, vpn_observed_at=now, vpn_observed_session_id='fixture',
        ))

    async def override_cache():
        return cache

    app.dependency_overrides[get_status_cache] = override_cache
    try:
        listed = await device_client.get('/api/v1/devices')
        detailed = await device_client.get(f'/api/v1/devices/{device_id}')
        assert listed.status_code == detailed.status_code == 200
        assert listed.json()['presence_available'] is available
        row = next(item for item in listed.json()['items'] if item['id'] == device_id)
        assert listed.json()['status_counts']['online'] == 0
        for payload in [row, detailed.json()]:
            assert payload['status'] == expected
            assert payload['vpn_active'] is None
            assert payload['vpn_observation_state'] == 'unknown'
    finally:
        app.dependency_overrides.pop(get_status_cache, None)
        await redis.aclose()
