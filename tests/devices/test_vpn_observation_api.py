"""Main list/detail responses must expose independent VPN freshness consistently."""
from datetime import datetime, timedelta, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from backend.api.v1.devices.router import get_status_cache
from backend.main import app
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
