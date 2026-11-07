"""Tenant coverage distinguishes observations, source failures and retained SQL."""
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import msgpack
import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from backend.database.redis_client import get_redis, get_redis_binary
from backend.main import app
from backend.models import Device
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache

NOW = datetime(2026, 10, 5, 18, tzinfo=timezone.utc)
PATH = '/api/v1/monitoring/fleet-coverage'


async def install_live(device_id, *, state='online', flag=True, age=0, heartbeat_age=0, owner='owner', reporter='owner'):
    redis = FakeRedis(decode_responses=False)
    cache = DeviceStatusCache(redis)
    await cache.set_status(str(device_id), DeviceLiveStatus(
        device_id=str(device_id), status=state, ws_session_id=owner,
        last_heartbeat=NOW - timedelta(seconds=heartbeat_age), vpn_active=flag,
        vpn_observed_at=NOW - timedelta(seconds=age) if age is not None else None,
        vpn_observed_session_id=reporter,
    ))
    app.dependency_overrides[get_redis_binary] = lambda: redis
    return redis


async def read(client):
    with patch('backend.services.fleet_coverage.datetime') as clock:
        clock.now.return_value = NOW
        response = await client.get(PATH)
    assert response.status_code == 200, response.text
    return response.json()


async def test_empty_inventory_is_measured_zero_not_unavailable(device_client):
    response = await device_client.get(PATH)
    assert response.status_code == 200
    data = response.json()
    assert data['inventory']['counts'] == {'total': 0}
    assert data['presence']['state'] == data['android_vpn']['state'] == 'ready'
    assert sum(data['presence']['counts'].values()) == 0
    assert data['transport_tunnels']['counts'] is None
    assert data['transport_tunnels']['state'] == 'unmeasured'


@pytest.mark.parametrize('flag,age,heartbeat_age,owner,reporter,expected,unknown_presence', [
    (True, 0, 0, 'owner', 'owner', 'active', False),
    (False, 119, 0, 'owner', 'owner', 'inactive', False),
    (True, 120, 0, 'owner', 'owner', 'stale', False),
    (True, None, 0, 'owner', 'owner', 'unknown', False),
    (True, -1, 0, 'owner', 'owner', 'unknown', False),
    (True, 0, 120, 'owner', 'owner', 'unknown', True),
    (True, 0, -1, 'owner', 'owner', 'unknown', True),
    (True, 0, 0, None, None, 'unknown', True),
    (True, 0, 0, 'owner', 'old', 'unknown', False),
])
async def test_independent_clocks_partition_android_reports(
    device_client, sample_device, flag, age, heartbeat_age, owner, reporter, expected, unknown_presence,
):
    redis = await install_live(sample_device.id, flag=flag, age=age, heartbeat_age=heartbeat_age, owner=owner, reporter=reporter)
    try:
        data = await read(device_client)
        assert data['android_vpn']['counts'][expected] == 1
        assert sum(data['android_vpn']['counts'].values()) == 1
        assert data['presence']['counts']['unknown' if unknown_presence else 'online'] == 1
        assert data['android_vpn']['max_age_seconds'] == 120
    finally:
        await redis.aclose()


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'wrong-device'])
async def test_unobserved_presence_is_unknown_not_offline(device_client, sample_device, kind):
    redis = FakeRedis(decode_responses=False)
    app.dependency_overrides[get_redis_binary] = lambda: redis
    if kind == 'malformed':
        await redis.set('device:status:' + str(sample_device.id), b'not-msgpack')
    if kind == 'wrong-device':
        await redis.set('device:status:' + str(sample_device.id), msgpack.packb(
            DeviceLiveStatus(device_id=str(uuid.uuid4()), status='offline').model_dump(mode='json'), use_bin_type=True))
    try:
        data = await read(device_client)
        assert data['presence']['state'] == 'ready'
        assert data['presence']['counts']['unknown'] == 1
        assert data['presence']['counts']['offline'] == 0
        assert data['android_vpn']['counts']['unknown'] == 1
    finally:
        await redis.aclose()


@pytest.mark.parametrize('redis_kind', ['absent', 'outage'])
async def test_redis_failure_preserves_sql_but_has_no_presence_numbers(device_client, sample_device, redis_kind):
    redis = None if redis_kind == 'absent' else AsyncMock()
    if redis is not None:
        redis.mget.side_effect = ConnectionError('private upstream must not appear in response')
    app.dependency_overrides[get_redis_binary] = lambda: redis
    data = await read(device_client)
    assert data['inventory']['counts']['total'] == 1
    assert data['presence']['state'] == data['android_vpn']['state'] == 'unavailable'
    assert data['presence']['counts'] is data['android_vpn']['counts'] is None
    assert data['vpn_assignment']['state'] == 'ready'
    assert 'private upstream' not in str(data)


async def test_tenant_and_active_scope_not_operator_selected(device_client, sample_device, db_session, device_org, other_org):
    db_session.add_all([Device(org_id=other_org.id, name='foreign'), Device(org_id=device_org.id, name='disabled', is_active=False)])
    await db_session.flush()
    response = await device_client.get(PATH, params={'org_id': str(other_org.id)})
    assert response.status_code == 200
    data = response.json()
    assert data['org_id'] == str(device_org.id)
    assert data['inventory']['counts']['total'] == 1


@pytest.mark.parametrize('age,active,state,bound,recent,stale,unknown,inactive', [
    (0, True, VPNPeerStatus.ASSIGNED, True, 1, 0, 0, 0),
    (179, True, VPNPeerStatus.ASSIGNED, True, 1, 0, 0, 0),
    (180, True, VPNPeerStatus.ASSIGNED, True, 0, 1, 0, 0),
    (None, True, VPNPeerStatus.ASSIGNED, True, 0, 0, 1, 0),
    (-1, True, VPNPeerStatus.ASSIGNED, True, 0, 0, 1, 0),
    (1, False, VPNPeerStatus.ASSIGNED, True, 0, 0, 0, 1),
    (1, True, VPNPeerStatus.PROVISIONING, True, 0, 0, 0, 0),
    (1, True, VPNPeerStatus.ASSIGNED, False, 0, 0, 0, 0),
])
async def test_handshakes_are_retained_evidence_not_live_tunnel_health(
    device_client, sample_device, device_org, db_session, age, active, state, bound, recent, stale, unknown, inactive,
):
    db_session.add(VPNPeer(org_id=device_org.id, device_id=sample_device.id if bound else None,
        public_key='unused', private_key_enc=b'unused', status=state, is_active=active,
        last_handshake_at=NOW - timedelta(seconds=age) if age is not None else None))
    await db_session.flush()
    data = await read(device_client)
    counts = data['handshakes']['counts']
    assert counts == {'recent': recent, 'stale': stale, 'unknown': unknown, 'inactive': inactive}
    assert data['handshakes']['source'] == 'retained-sql-handshakes'
    assert data['handshakes']['max_age_seconds'] == 180
    assert data['transport_tunnels']['counts'] is None
    assert data['vpn_assignment']['counts'][state.value] == 1
    assert data['vpn_assignment']['counts']['outside_active_inventory'] == (1 if state == VPNPeerStatus.ASSIGNED and not bound else 0)


async def test_script_runner_can_read_fleet_without_vpn_permission(device_client, device_manager_user, sample_device):
    device_manager_user.role = 'script_runner'
    data = await device_client.get(PATH)
    assert data.status_code == 200
    for key in ['vpn_assignment', 'handshakes', 'android_vpn']:
        assert data.json()[key]['state'] == 'forbidden'
        assert data.json()[key]['counts'] is None
    assert data.json()['inventory']['counts']['total'] == 1


async def test_anonymous_request_cannot_read_coverage():
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get(PATH)).status_code == 401


async def test_inventory_budget_retains_exact_sql_total_without_reading_redis(
    device_client, sample_device, device_org, db_session,
):
    db_session.add(Device(org_id=device_org.id, name='second'))
    await db_session.flush()
    redis = AsyncMock()
    app.dependency_overrides[get_redis_binary] = lambda: redis
    with patch('backend.services.fleet_coverage.MAX_INVENTORY_DEVICES', 1):
        data = await read(device_client)
    assert data['inventory']['counts'] == {'total': 2}
    for key in ['presence', 'android_vpn']:
        assert data[key]['state'] == 'limited'
        assert data[key]['counts'] is None
    redis.mget.assert_not_called()


async def test_later_redis_chunk_failure_discards_partial_counts(
    device_client, sample_device, device_org, db_session,
):
    db_session.add(Device(org_id=device_org.id, name='second'))
    await db_session.flush()
    redis = AsyncMock()
    redis.mget.side_effect = [[None], ConnectionError('private endpoint')]
    app.dependency_overrides[get_redis_binary] = lambda: redis
    with patch('backend.services.fleet_coverage.REDIS_BATCH_SIZE', 1):
        data = await read(device_client)
    assert redis.mget.await_count == 2
    assert data['inventory']['counts'] == {'total': 2}
    for key in ['presence', 'android_vpn']:
        assert data[key]['state'] == 'unavailable'
        assert data[key]['counts'] is data[key]['observed_at'] is None


async def test_peer_source_failure_does_not_hide_received_android_report(device_client, sample_device):
    redis = await install_live(sample_device.id, flag=False)
    try:
        with patch('backend.services.fleet_coverage._read_peer_counts', side_effect=RuntimeError('private SQL detail')):
            data = await read(device_client)
        assert data['inventory']['counts']['total'] == 1
        assert data['presence']['counts']['online'] == 1
        assert data['android_vpn']['counts']['inactive'] == 1
        for key in ['vpn_assignment', 'handshakes']:
            assert data[key]['state'] == 'unavailable'
            assert data[key]['counts'] is None
        assert 'private SQL detail' not in str(data)
    finally:
        await redis.aclose()


async def test_inventory_timeout_never_invents_zero():
    from backend.services.fleet_coverage import read_fleet_coverage

    @asynccontextmanager
    async def delayed_savepoint():
        await asyncio.sleep(1)
        yield

    db = AsyncMock()
    db.begin_nested = delayed_savepoint
    with patch('backend.services.fleet_coverage.SQL_TIMEOUT_SECONDS', 0):
        data = (await read_fleet_coverage(db, None, uuid.uuid4(), vpn_allowed=True)).model_dump()
    for key in ['inventory', 'presence', 'android_vpn', 'vpn_assignment', 'handshakes']:
        assert data[key]['state'] == 'unavailable'
        assert data[key]['counts'] is data[key]['observed_at'] is None


async def test_peers_cannot_cross_tenant_or_disabled_inventory(device_client, device_org, other_org, db_session):
    foreign = Device(org_id=other_org.id, name='foreign')
    disabled = Device(org_id=device_org.id, name='disabled', is_active=False)
    db_session.add_all([foreign, disabled])
    await db_session.flush()
    db_session.add_all([
        VPNPeer(org_id=other_org.id, device_id=foreign.id, public_key='foreign', private_key_enc=b'unused',
                status=VPNPeerStatus.ASSIGNED, is_active=True, last_handshake_at=NOW),
        VPNPeer(org_id=device_org.id, device_id=disabled.id, public_key='disabled', private_key_enc=b'unused',
                status=VPNPeerStatus.ASSIGNED, is_active=True, last_handshake_at=NOW),
    ])
    await db_session.flush()
    data = await read(device_client)
    assert data['inventory']['counts']['total'] == 0
    assert data['vpn_assignment']['counts']['assigned'] == 1
    assert data['vpn_assignment']['counts']['outside_active_inventory'] == 1
    assert sum(data['handshakes']['counts'].values()) == 0


async def test_route_uses_binary_client_when_text_and_binary_clients_coexist(device_client, sample_device):
    server = FakeServer()
    binary = FakeRedis(server=server, decode_responses=False)
    text = FakeRedis(server=server, decode_responses=True)
    cache = DeviceStatusCache(binary)
    await cache.set_status(str(sample_device.id), DeviceLiveStatus(
        device_id=str(sample_device.id), status='online', ws_session_id='owner', last_heartbeat=NOW,
        vpn_active=False, vpn_observed_at=NOW, vpn_observed_session_id='owner',
    ))
    app.dependency_overrides[get_redis] = lambda: text
    app.dependency_overrides[get_redis_binary] = lambda: binary
    try:
        with pytest.raises(UnicodeDecodeError):
            await text.mget('device:status:' + str(sample_device.id))
        data = await read(device_client)
        assert data['presence']['state'] == data['android_vpn']['state'] == 'ready'
        assert data['presence']['counts']['online'] == 1
        assert data['android_vpn']['counts']['inactive'] == 1
    finally:
        await text.aclose()
        await binary.aclose()
