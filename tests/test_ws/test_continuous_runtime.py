from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fakeredis import FakeServer
from fakeredis import aioredis as fake_async
from fakeredis.aioredis import FakeRedis
from redis.asyncio.connection import ConnectionPool
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.metrics import continuous_stage_duration_seconds
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.continuous_lease import ContinuousLeaseStore
from backend.websocket.continuous_protocol import InvalidContinuousInput
from backend.websocket.continuous_runtime import (
    ContinuousAdmissionRejected,
    ContinuousRuntime,
    TouchViewer,
    ViewerTransportUnavailable,
)

EPOCH = '00112233-4455-6677-8899-aabbccddeeff'


async def eventually(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest_asyncio.fixture
async def live():
    server = FakeServer()
    clients = [FakeRedis(connection_pool=ConnectionPool(
        connection_class=getattr(fake_async, 'FakeAsyncRedisConnection', fake_async.FakeConnection),
        server=server, decode_responses=False, max_connections=8,
        socket_timeout=0.25, socket_connect_timeout=0.25,
        retry=Retry(NoBackoff(), 0), retry_on_error=[], retry_on_timeout=False,
    )) for _ in range(2)]
    managers = [ConnectionManager(), ConnectionManager()]
    namespace = 'audit:continuous:' + uuid4().hex
    runtimes = [ContinuousRuntime(ContinuousLeaseStore(client, namespace=namespace), manager)
                for client, manager in zip(clients, managers)]
    device, org = 'device_' + uuid4().hex, 'org_fixture_01'
    agent = AsyncMock()
    session = await managers[0].connect(agent, device, 'android', org)
    await DeviceStatusCache(clients[0]).set_status(device, DeviceLiveStatus(
        device_id=device, status='online', ws_session_id=session))
    viewer = TouchViewer(device, org, 'user_fixture_01', 'viewer_fixture_01', AsyncMock())
    for runtime in runtimes:
        await runtime.start()
    assert runtimes[1].register(viewer)

    async def native(message):
        if message['type'] == 'continuous_input_probe':
            reply = dict(type='continuous_input_offer', session_id=viewer.session,
                protocol_version=1, injector_ready=False, frame_protocol_version=2,
                display_id=0, max_pointers=1, capture_epoch=EPOCH, frame_width=960,
                frame_height=540, physical_width=960, physical_height=540, rotation=0)
        elif message['type'] == 'continuous_input_open':
            reply = dict(type='continuous_input_status', session_id=viewer.session,
                owner=message['owner'], capture_epoch=EPOCH, sequence=0, status=0,
                stage='startup', origin='injector', device_uptime_ms=100)
        elif message['type'] == 'continuous_input_event':
            reply = dict(type='continuous_input_status', session_id=viewer.session,
                owner=message['owner'], capture_epoch=EPOCH, sequence=message['sequence'],
                status=2 if message['action'] == 4 else 3 if message['action'] == 3 else 1,
                stage='input', origin='injector', device_uptime_ms=110)
        elif message['type'] == 'continuous_input_authorize':
            return  # Authority renewal has no input/native execution receipt.
        else:
            reply = dict(type='continuous_input_status', session_id=viewer.session,
                owner=message['owner'], capture_epoch=EPOCH, sequence=0, status=3,
                stage='release', origin='injector', device_uptime_ms=120)
        await runtimes[0].agent_message(device, session, reply)
    agent.send_json.side_effect = native
    try:
        yield runtimes, viewer, agent, clients, session
    finally:
        for runtime in reversed(runtimes):
            await runtime.stop()


async def open_view(live):
    runtimes, viewer, agent, clients, session = live
    runtime = runtimes[1]
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH,
        frame_width=960, frame_height=540))
    await eventually(lambda: any(c.args[0].get('stage') == 'startup' for c in viewer.ws.send_json.call_args_list))
    return runtime, viewer, agent


@pytest.mark.asyncio
async def test_direct_release_can_be_seen_before_server_release_without_rejecting_fresh_probe(live):
    runtime, viewer, agent = await open_view(live)
    runtimes, _, _, _, session = live
    old = viewer.lease
    probes_before = sum(c.args[0]['type'] == 'continuous_input_probe' for c in agent.send_json.call_args_list)
    # The browser already saw RELEASE3 over RTC, while the authenticated copy
    # is still travelling to this worker. Probing grants no new input authority.
    for _ in range(100):
        await runtime.handle(viewer, {'type': 'touch_probe'})
    assert viewer.lease == old and not viewer.closing
    assert sum(c.args[0]['type'] == 'continuous_input_probe' for c in agent.send_json.call_args_list) == probes_before
    await runtimes[0].agent_message(viewer.device, session, {
        'type': 'continuous_input_status', 'session_id': viewer.session, 'owner': old.owner,
        'capture_epoch': EPOCH, 'sequence': 0, 'status': 3, 'stage': 'release',
        'origin': 'injector', 'device_uptime_ms': 120,
    })
    await eventually(lambda: viewer.lease is None and viewer.offer is not None)
    assert sum(c.args[0]['type'] == 'continuous_input_probe' for c in agent.send_json.call_args_list) == probes_before + 1
    messages = [c.args[0] for c in viewer.ws.send_json.call_args_list]
    assert [m['type'] for m in messages][-2:] == ['continuous_input_status', 'touch_capability']
    assert messages[-2]['status'] == 3
    assert all(c.args[0]['type'] not in {'continuous_input_event', 'continuous_input_close'} for c in agent.send_json.call_args_list)
    await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540))
    assert viewer.lease is not None and viewer.lease.owner != old.owner


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['unknown_release', 'expired_probe', 'unregistered', 'explicit_close'])
async def test_deferred_probe_never_substitutes_for_current_confirmed_native_release(live, monkeypatch, ending):
    runtime, viewer, agent = await open_view(live)
    runtimes, _, _, _, session = live
    old = viewer.lease
    previous_offer = viewer.offer
    original_now = await runtime.now()
    clock = AsyncMock(return_value=original_now)
    monkeypatch.setattr(runtime, 'now', clock)
    await runtime.handle(viewer, {'type': 'touch_probe'})
    probes_before = sum(c.args[0]['type'] == 'continuous_input_probe' for c in agent.send_json.call_args_list)
    if ending == 'expired_probe':
        clock.return_value = original_now + 5001
    if ending == 'unregistered':
        await runtime.unregister(viewer)
    elif ending == 'explicit_close':
        await runtime.handle(viewer, {'type': 'touch_close'})
        await eventually(lambda: viewer.lease is None)
    else:
        await runtimes[0].agent_message(viewer.device, session, {
            'type': 'continuous_input_status', 'session_id': viewer.session, 'owner': old.owner,
            'capture_epoch': EPOCH, 'sequence': 0, 'status': 6 if ending == 'unknown_release' else 3,
            'stage': 'release', 'origin': 'injector', 'device_uptime_ms': 120,
        })
        await eventually(lambda: any(c.args[0].get('stage') == 'release' for c in viewer.ws.send_json.call_args_list))
    await asyncio.sleep(.03)
    assert sum(c.args[0]['type'] == 'continuous_input_probe' for c in agent.send_json.call_args_list) == probes_before
    if ending == 'unknown_release':
        assert viewer.lease == old and viewer.offer == previous_offer
    else:
        assert viewer.offer is None


@pytest.mark.asyncio
async def test_foreign_release_cannot_flush_deferred_probe_or_release_current_authority(live):
    runtime, viewer, agent = await open_view(live)
    runtimes, _, _, _, session = live
    old = viewer.lease
    await runtime.handle(viewer, {'type': 'touch_probe'})
    probes_before = sum(c.args[0]['type'] == 'continuous_input_probe' for c in agent.send_json.call_args_list)
    await runtimes[0].agent_message(viewer.device, session, {
        'type': 'continuous_input_status', 'session_id': viewer.session, 'owner': 'foreign_owner_01',
        'capture_epoch': EPOCH, 'sequence': 0, 'status': 3, 'stage': 'release',
        'origin': 'injector', 'device_uptime_ms': 120,
    })
    await asyncio.sleep(.03)
    assert viewer.lease == old and not viewer.closing
    assert sum(c.args[0]['type'] == 'continuous_input_probe' for c in agent.send_json.call_args_list) == probes_before


@pytest.mark.asyncio
async def test_native_pre_owner_refusal_clears_local_slot_and_allows_fresh_probe(live):
    runtimes, viewer, agent, _, session = live
    runtime = runtimes[1]
    original = agent.send_json.side_effect

    async def decline_open(message):
        if message['type'] != 'continuous_input_open':
            return await original(message)
        await runtimes[0].agent_message(viewer.device, session, {
            'type': 'continuous_input_status', 'session_id': viewer.session,
            'owner': message['owner'], 'capture_epoch': EPOCH,
            'sequence': 0, 'status': 5, 'stage': 'startup', 'origin': 'admission',
            'device_uptime_ms': 100,
        })

    agent.send_json.side_effect = decline_open
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    await runtime.handle(viewer, {'type': 'touch_open', 'capture_epoch': EPOCH,
                                  'frame_width': 960, 'frame_height': 540})
    await eventually(lambda: any(c.args[0].get('status') == 5 for c in viewer.ws.send_json.call_args_list))
    assert viewer.lease is None and viewer.offer is None and not viewer.closing
    assert not any(c.args[0].get('stage') == 'release' for c in viewer.ws.send_json.call_args_list)
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)


@pytest.mark.asyncio
async def test_old_release_send_callback_cannot_erase_replacement_owner(live):
    runtime, viewer, _ = await open_view(live)
    old = viewer.lease
    replaced = asyncio.Event()
    newer = None

    async def during_send(message):
        nonlocal newer
        if message.get('stage') == 'release':
            newer = await runtime.store.acquire(old.binding)
            assert newer is not None
            viewer.lease = newer
            viewer.closing = False
            replaced.set()

    viewer.ws.send_json.side_effect = during_send
    await runtime.handle(viewer, {'type': 'touch_close'})
    await asyncio.wait_for(replaced.wait(), 1)
    assert viewer.lease == newer
    assert await runtime.store.redis.hget(runtime.store.key(newer.binding), 'identity') == newer.identity.encode()


@pytest.mark.asyncio
async def test_open_cancelled_before_agent_delivery_confirms_admission_only_and_can_negotiate_again(live, monkeypatch):
    runtimes, viewer, agent, _, _ = live
    runtime = runtimes[1]
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = runtimes[0].store.delivery_command

    async def delayed_guard(envelope, **scope):
        if envelope['command']['type'] == 'continuous_input_open':
            reached.set()
            await proceed.wait()
        return await original(envelope, **scope)

    monkeypatch.setattr(runtimes[0].store, 'delivery_command', delayed_guard)
    try:
        await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH,
            frame_width=960, frame_height=540))
        await asyncio.wait_for(reached.wait(), 1)
        old = viewer.lease
        await runtime.handle(viewer, {'type': 'touch_close', 'cancel_unstarted': True})
        assert viewer.lease is None and not viewer.closing
        assert viewer.ws.send_json.call_args_list[-1].args[0] == {
            'type': 'touch_cancelled', 'session_id': viewer.session, 'owner': old.owner,
            'capture_epoch': EPOCH, 'origin': 'admission'}
        proceed.set()
        await runtime.handle(viewer, {'type': 'touch_probe'})
        await eventually(lambda: viewer.offer is not None)
        assert all(c.args[0]['type'] != 'continuous_input_open' for c in agent.send_json.call_args_list)
        assert all(c.args[0].get('stage') != 'release' for c in viewer.ws.send_json.call_args_list)
    finally:
        proceed.set()


@pytest.mark.asyncio
async def test_opted_in_cancel_after_delivery_still_requires_native_cleanup(live):
    runtime, viewer, agent = await open_view(live)
    await runtime.handle(viewer, {'type': 'touch_close', 'cancel_unstarted': True})
    await eventually(lambda: viewer.lease is None)
    assert all(c.args[0].get('type') != 'touch_cancelled' for c in viewer.ws.send_json.call_args_list)
    assert any(c.args[0]['type'] == 'continuous_input_close' for c in agent.send_json.call_args_list)


@pytest.mark.asyncio
async def test_two_workers_route_late_native_release_then_accept_fresh_owner_without_input_replay(live):
    runtime, viewer, agent = await open_view(live)
    runtimes, _, _, clients, _ = live
    old = viewer.lease
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = agent.send_json.side_effect

    async def delayed_release(message):
        if message['type'] == 'continuous_input_close':
            reached.set()
            await proceed.wait()
        await original(message)

    agent.send_json.side_effect = delayed_release
    try:
        await runtime.handle(viewer, {'type': 'touch_close'})
        await asyncio.wait_for(reached.wait(), 1)
        assert viewer.closing and viewer.lease == old
        await clients[0].pexpire(runtime.store.key(old.binding), 1)
        await asyncio.sleep(0.02)
        proceed.set()
        await eventually(lambda: viewer.lease is None)
        assert not viewer.closing
        release = viewer.ws.send_json.call_args_list[-1].args[0]
        assert release['stage'] == 'release' and release['status'] == 3 and release['owner'] == old.owner
        assert not await clients[0].exists(runtime.store.key(old.binding))
        await runtime.handle(viewer, {'type': 'touch_probe'})
        await eventually(lambda: viewer.offer is not None)
        await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540))
        assert viewer.lease is not None and viewer.lease.owner != old.owner
        await eventually(lambda: len([c for c in viewer.ws.send_json.call_args_list
                                     if c.args[0].get('stage') == 'startup']) == 2)
        assert all(c.args[0]['type'] != 'continuous_input_event' for c in agent.send_json.call_args_list)
        assert runtimes[0].available and runtime.available
    finally:
        proceed.set()


@pytest.mark.asyncio
async def test_direct_open_is_bound_to_this_viewer_and_rechecks_peer_before_each_authority_renewal(live, monkeypatch):
    from types import SimpleNamespace

    from backend.websocket import direct_probe_runtime
    runtimes, viewer, agent, _, session = live
    runtime = runtimes[1]
    peer_check = AsyncMock(return_value=True)
    monkeypatch.setattr(direct_probe_runtime, 'get_direct_probe_runtime', lambda: SimpleNamespace(input_peer=peer_check))
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    await runtime.handle(viewer, dict(type='touch_direct_open', capture_epoch=EPOCH, frame_width=960,
        frame_height=540, direct_session='a' * 32))
    await eventually(lambda: any(c.args[0].get('stage') == 'startup' for c in viewer.ws.send_json.call_args_list))
    peer_check.assert_awaited_once_with(device=viewer.device, org=viewer.org, user=viewer.user,
        session='a' * 32, agent_session=session, viewer_session=viewer.session)
    assert viewer.direct_session == 'a' * 32
    with pytest.raises(InvalidContinuousInput):
        await runtime.handle(viewer, dict(type='touch_event', sequence=1, gesture=1, action=0, x=1, y=1))
    assert await runtime.authorize(viewer)
    await eventually(lambda: any(c.args[0]['type'] == 'continuous_input_authorize' for c in agent.send_json.call_args_list))
    assert all(c.args[0]['type'] != 'continuous_input_event' for c in agent.send_json.call_args_list)
    peer_check.return_value = False
    assert not await runtime.authorize(viewer)
    await runtime.handle(viewer, {'type': 'touch_close'})
    await eventually(lambda: viewer.lease is None)
    assert viewer.direct_session is None


@pytest.mark.asyncio
async def test_unmatched_direct_peer_cannot_acquire_or_open_native_owner(live, monkeypatch):
    from types import SimpleNamespace

    from backend.websocket import direct_probe_runtime
    runtimes, viewer, agent, clients, _ = live
    runtime = runtimes[1]
    monkeypatch.setattr(direct_probe_runtime, 'get_direct_probe_runtime', lambda: SimpleNamespace(input_peer=AsyncMock(return_value=False)))
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    with pytest.raises(ContinuousAdmissionRejected):
        await runtime.handle(viewer, dict(type='touch_direct_open', capture_epoch=EPOCH, frame_width=960,
            frame_height=540, direct_session='a' * 32))
    assert viewer.lease is None
    assert all(c.args[0]['type'] != 'continuous_input_open' for c in agent.send_json.call_args_list)
    assert await clients[0].keys(runtime.store.namespace + ':lease:*') == []


@pytest.mark.asyncio
async def test_two_workers_probe_ready_move_before_up_and_known_release(live):
    runtime, viewer, agent = await open_view(live)
    assert viewer.ws.send_json.call_args_list[1].args[0]['type'] == 'touch_session'
    for seq, action, x in [(1, 0, 100), (2, 2, 300), (3, 2, 200)]:
        await runtime.handle(viewer, dict(type='touch_event', sequence=seq, gesture=1, action=action, x=x, y=100))
    await eventually(lambda: len([c for c in agent.send_json.call_args_list if c.args[0]['type'] == 'continuous_input_event']) == 3)
    events = [c.args[0] for c in agent.send_json.call_args_list if c.args[0]['type'] == 'continuous_input_event']
    assert [e['action'] for e in events] == [0, 2, 2]  # No UP needed to deliver MOVE.
    assert [e['x'] for e in events] == [100, 300, 200]
    await runtime.handle(viewer, dict(type='touch_event', sequence=4, gesture=1, action=1, x=200, y=100))
    await eventually(lambda: any(c.args[0].get('sequence') == 4 and c.args[0].get('stage') == 'input'
                                for c in viewer.ws.send_json.call_args_list))
    assert [c.args[0]['action'] for c in agent.send_json.call_args_list
            if c.args[0]['type'] == 'continuous_input_event'] == [0, 2, 2, 1]
    await runtime.handle(viewer, {'type': 'touch_close'})
    await eventually(lambda: viewer.lease is None)
    assert not viewer.closing
    assert any(c.args[0].get('stage') == 'release' for c in viewer.ws.send_json.call_args_list)
    assert await live[3][0].keys(runtime.store.namespace + ':*') == []


@pytest.mark.asyncio
async def test_second_viewer_gets_known_busy_refusal_and_can_open_after_confirmed_release(live):
    runtime, viewer, agent = await open_view(live)
    original = viewer.lease
    offer = dict(viewer.offer)
    second = TouchViewer(viewer.device, viewer.org, viewer.user, 'second_viewer_fixture', AsyncMock(), offer=offer)
    assert runtime.register(second)
    opening = dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540)
    with pytest.raises(ContinuousAdmissionRejected) as caught:
        await runtime.handle(second, opening)
    assert caught.value.reason == 'controller_busy'
    assert second.lease is None
    assert viewer.lease == original
    second.ws.send_json.assert_not_awaited()
    assert len([c for c in agent.send_json.call_args_list if c.args[0]['type'] == 'continuous_input_open']) == 1
    await runtime.retire(second)  # The router retires only the refused viewer.
    assert viewer.lease == original
    await runtime.retire(viewer)
    await eventually(lambda: viewer.lease is None)
    second.offer = offer  # A fresh probe produces the same current capture binding.
    await runtime.handle(second, opening)
    assert second.lease is not None
    assert second.lease.binding.viewer_session == second.session
    assert second.lease.owner != original.owner
    assert not any(c.args[0]['type'] == 'continuous_input_event' for c in agent.send_json.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['offer_expired', 'capture_changed', 'agent_reconnecting'])
async def test_stale_admission_is_classified_before_acquiring_an_owner(live, monkeypatch, reason):
    runtimes, viewer, agent, _, _ = live
    runtime = runtimes[1]
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    if reason == 'offer_expired':
        viewer.offer['expires'] = await runtime.now() - 1
    elif reason == 'capture_changed':
        viewer.offer['frame_width'] = 1080
    else:
        monkeypatch.setattr(runtime, 'topology', AsyncMock(return_value=False))
    with pytest.raises(ContinuousAdmissionRejected) as caught:
        await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540))
    assert caught.value.reason == reason
    assert viewer.lease is None
    assert not any(c.args[0]['type'] == 'continuous_input_open' for c in agent.send_json.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['topology', 'renewal'])
@pytest.mark.parametrize('replacement', [False, True])
async def test_authorization_never_renews_or_rejects_a_replacement_owner(live, monkeypatch, boundary, replacement):
    runtime, viewer, _ = await open_view(live)
    old = viewer.lease
    entered, resume = asyncio.Event(), asyncio.Event()

    async def delayed(*_):
        entered.set()
        await resume.wait()
        return boundary == 'topology'

    topology = AsyncMock(return_value=True)
    renewal = AsyncMock(return_value=False)
    monkeypatch.setattr(runtime, 'topology', delayed if boundary == 'topology' else topology)
    monkeypatch.setattr(runtime.store, 'authorize', delayed if boundary == 'renewal' else renewal)
    check = asyncio.create_task(runtime.authorize(viewer))
    await asyncio.wait_for(entered.wait(), 1)
    viewer.lease = replace(old, owner='replacement_owner_01') if replacement else None
    resume.set()
    assert await asyncio.wait_for(check, 1) is True  # The obsolete check does not decide a new owner's validity.
    if boundary == 'topology':
        renewal.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('replacement', [False, True])
async def test_late_permission_failure_cannot_retire_or_error_a_replacement_owner(live, monkeypatch, replacement):
    runtime, viewer, _ = await open_view(live)
    old = viewer.lease
    entered, resume = asyncio.Event(), asyncio.Event()

    async def permission():
        entered.set()
        await resume.wait()
        return False

    retire, send = AsyncMock(), AsyncMock()
    monkeypatch.setattr(runtime, 'retire', retire)
    monkeypatch.setattr(runtime, 'send', send)
    check = asyncio.create_task(runtime.recheck_authorization(viewer, permission))
    await asyncio.wait_for(entered.wait(), 1)
    viewer.lease = replace(old, owner='replacement_owner_01') if replacement else None
    resume.set()
    await asyncio.wait_for(check, 1)
    retire.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('unavailable', [False, True])
async def test_current_owner_is_still_retired_when_control_permission_is_denied_or_unavailable(live, monkeypatch, unavailable):
    runtime, viewer, _ = await open_view(live)
    old = viewer.lease
    permission = AsyncMock(side_effect=RuntimeError('authorization_unavailable')) if unavailable else AsyncMock(return_value=False)
    send = AsyncMock()
    monkeypatch.setattr(runtime, 'send', send)
    await runtime.recheck_authorization(viewer, permission)
    # Real retirement is used; a known RELEASE may arrive before this assertion.
    assert viewer.closing or viewer.lease is None
    if viewer.lease == old:
        expected = {'type': 'touch_error', 'owner': old.owner}
        if unavailable:
            expected.update(error='input_temporarily_unavailable', reason='runtime_unavailable', retryable=True)
        else:
            expected.update(error='control_denied')
        send.assert_awaited_once_with(viewer, expected)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['lease', 'exception'])
async def test_periodic_runtime_loss_is_retryable_without_weakening_permission_or_replaying_input(live, monkeypatch, failure):
    runtime, viewer, _ = await open_view(live)
    old = viewer.lease
    permission = AsyncMock(return_value=True)
    authorize = AsyncMock(side_effect=RuntimeError('lease_unavailable')) if failure == 'exception' else AsyncMock(return_value=False)
    retire, send = AsyncMock(), AsyncMock()
    monkeypatch.setattr(runtime, 'authorize', authorize)
    monkeypatch.setattr(runtime, 'retire', retire)
    monkeypatch.setattr(runtime, 'send', send)
    await runtime.recheck_authorization(viewer, permission)
    permission.assert_awaited_once()
    authorize.assert_awaited_once_with(viewer)
    retire.assert_awaited_once_with(viewer)
    send.assert_awaited_once_with(viewer, {'type': 'touch_error', 'owner': old.owner,
        'error': 'input_temporarily_unavailable', 'reason': 'runtime_unavailable', 'retryable': True})


@pytest.mark.asyncio
@pytest.mark.parametrize('action', [0, 1, 2, 3, 4])
async def test_inflight_input_after_retirement_cannot_dispatch_or_cancel_known_release_recovery(live, monkeypatch, action):
    runtime, viewer, _ = await open_view(live)
    old = viewer.lease
    viewer.closing = True  # Exact owner's native RELEASE is still pending.
    event = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(runtime.store, 'event', event)
    monkeypatch.setattr(runtime, 'send', send)
    await runtime.handle(viewer, dict(type='touch_event', sequence=1, gesture=1, action=action, x=1, y=1))
    event.assert_not_awaited()
    send.assert_not_awaited()  # No input ACK and no second terminal rejection.
    assert viewer.lease == old and viewer.closing


@pytest.mark.asyncio
async def test_retiring_owner_does_not_accept_malformed_input_or_a_new_owner(live):
    runtime, viewer, _ = await open_view(live)
    old = viewer.lease
    viewer.closing = True
    with pytest.raises(InvalidContinuousInput):
        await runtime.handle(viewer, dict(type='touch_event', sequence=1, gesture=1, action=4, x=1, y=1, replay=True))
    with pytest.raises(InvalidContinuousInput):
        await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540))
    assert viewer.lease == old and viewer.closing


@pytest.mark.asyncio
async def test_replacement_global_topology_prevents_old_socket_offer(live):
    runtimes, viewer, agent, clients, session = live
    await DeviceStatusCache(clients[0]).set_status(viewer.device, DeviceLiveStatus(
        device_id=viewer.device, status='online', ws_session_id='replacement_session'))
    await runtimes[1].handle(viewer, {'type': 'touch_probe'})
    await asyncio.sleep(0.05)
    agent.send_json.assert_not_awaited()
    assert viewer.offer is None


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['tenant', 'epoch', 'dimensions', 'expiry', 'extra'])
async def test_offer_cannot_admit_wrong_binding(live, mutation):
    runtimes, viewer, agent, _, _ = live
    runtime = runtimes[1]
    offer = dict(type='_continuous_offer_v1', org=viewer.org, device=viewer.device,
        session=viewer.session, worker=runtime.worker, expires=await runtime.now() + 4000,
        agent_session=live[4], capture_epoch=EPOCH, frame_width=960, frame_height=540)
    if mutation == 'tenant':
        offer['org'] = 'foreign_tenant'
    if mutation == 'epoch':
        offer['capture_epoch'] = 'not-canonical'
    if mutation == 'dimensions':
        offer['frame_width'] = True
    if mutation == 'expiry':
        offer['expires'] = await runtime.now() - 1
    if mutation == 'extra':
        offer['owner'] = 'supplied_owner'
    try:
        await runtime.route(runtime.viewer_channel, json.dumps(offer))
    except InvalidContinuousInput:
        pass
    assert viewer.offer is None
    agent.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_viewer_cannot_take_active_owner(live):
    runtime, viewer, agent = await open_view(live)
    other = TouchViewer(viewer.device, viewer.org, viewer.user, 'viewer_fixture_02', AsyncMock(), offer=viewer.offer)
    assert runtime.register(other)
    with pytest.raises(InvalidContinuousInput):
        await runtime.handle(other, dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540))
    assert other.lease is None and viewer.lease is not None
    assert len([c for c in agent.send_json.call_args_list if c.args[0]['type'] == 'continuous_input_open']) == 1


@pytest.mark.asyncio
async def test_unregister_closes_only_exact_viewer_and_removes_callback(live):
    runtime, viewer, agent = await open_view(live)
    await runtime.unregister(viewer)
    assert viewer.session not in runtime.viewers
    await eventually(lambda: any(c.args[0]['type'] == 'continuous_input_close' for c in agent.send_json.call_args_list))


@pytest.mark.asyncio
async def test_retired_offer_cannot_open_or_replay(live):
    runtime, viewer, agent = await open_view(live)
    await runtime.retire(viewer)
    await runtime.handle(viewer, dict(type='touch_event', sequence=1, gesture=1, action=0, x=1, y=1))
    assert not any(c.args[0]['type'] == 'continuous_input_event' for c in agent.send_json.call_args_list)


async def offer_to(runtime, viewer, agent_session):
    await runtime.publish(runtime.viewer_channel, dict(type='_continuous_offer_v1',
        org=viewer.org, device=viewer.device, session=viewer.session, worker=runtime.worker,
        expires=await runtime.now() + 4000, agent_session=agent_session,
        capture_epoch=EPOCH, frame_width=960, frame_height=540))


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [RuntimeError('closed viewer'), OSError('viewer disconnected'), TimeoutError()])
async def test_failed_viewer_offer_does_not_stop_other_viewers_or_shared_listener(live, failure):
    runtimes, viewer, agent, _, agent_session = live
    runtime = runtimes[1]
    healthy = TouchViewer(viewer.device, viewer.org, viewer.user, 'viewer_fixture_02', AsyncMock())
    assert runtime.register(healthy)
    viewer.ws.send_json.side_effect = failure
    await offer_to(runtime, viewer, agent_session)
    await eventually(lambda: not runtime.available or viewer.session not in runtime.viewers)
    assert runtime.available and not runtime.task.done()
    assert viewer.session not in runtime.viewers
    assert runtime.viewers[healthy.session] is healthy
    await offer_to(runtime, healthy, agent_session)
    await eventually(lambda: healthy.ws.send_json.await_count == 1)
    assert healthy.ws.send_json.call_args.args[0]['type'] == 'touch_capability'
    agent.send_json.assert_not_awaited()  # No owner, Android command or replay for either offer.


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['heartbeat', 'release'])
async def test_failed_viewer_receipt_retires_only_its_owner_without_replaying_input(live, phase):
    runtime, viewer, agent = await open_view(live)
    healthy = TouchViewer(viewer.device, viewer.org, viewer.user, 'viewer_fixture_02', AsyncMock())
    assert runtime.register(healthy)
    viewer.ws.send_json.side_effect = RuntimeError('socket closed between route and send')
    if phase == 'heartbeat':
        await runtime.handle(viewer, dict(type='touch_event', sequence=1, gesture=0, action=4, x=0, y=0))
    else:
        await runtime.handle(viewer, {'type': 'touch_close'})
    await eventually(lambda: not runtime.available or viewer.session not in runtime.viewers)
    assert runtime.available and not runtime.task.done()
    assert viewer.session not in runtime.viewers
    assert runtime.viewers[healthy.session] is healthy
    await eventually(lambda: any(c.args[0]['type'] == 'continuous_input_close' for c in agent.send_json.call_args_list))
    await offer_to(runtime, healthy, live[4])
    await eventually(lambda: healthy.ws.send_json.await_count == 1)
    events = [c.args[0] for c in agent.send_json.call_args_list if c.args[0]['type'] == 'continuous_input_event']
    assert [event['action'] for event in events] == ([4] if phase == 'heartbeat' else [])
    assert len([c for c in agent.send_json.call_args_list if c.args[0]['type'] == 'continuous_input_open']) == 1


@pytest.mark.asyncio
async def test_failed_session_binding_cannot_publish_native_open_after_viewer_transport_loss(live):
    runtimes, viewer, agent, _, _ = live
    runtime = runtimes[1]
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    viewer.ws.send_json.side_effect = RuntimeError('session binding could not be delivered')
    with pytest.raises(ViewerTransportUnavailable):
        await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540))
    assert runtime.available
    assert viewer.session not in runtime.viewers
    assert not any(c.args[0]['type'] == 'continuous_input_open' for c in agent.send_json.call_args_list)


@pytest.mark.asyncio
async def test_viewer_send_preserves_cancellation_instead_of_classifying_it_as_socket_failure(live):
    runtime, viewer = live[0][1], live[1]
    entered = asyncio.Event()

    async def wait_forever(_):
        entered.set()
        await asyncio.Future()

    viewer.ws.send_json.side_effect = wait_forever
    task = asyncio.create_task(runtime.send(viewer, {'type': 'fixture'}))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.available and runtime.viewers[viewer.session] is viewer


@pytest.mark.asyncio
async def test_displaced_viewer_cannot_open_native_input_or_unregister_the_replacement(live, monkeypatch):
    runtime, viewer, agent = live[0][1], live[1], live[2]
    await runtime.handle(viewer, {'type': 'touch_probe'})
    await eventually(lambda: viewer.offer is not None)
    replacement = TouchViewer(viewer.device, viewer.org, viewer.user, viewer.session, AsyncMock())
    acquire = runtime.store.acquire

    async def displaced(binding):
        lease = await acquire(binding)
        runtime.viewers[viewer.session] = replacement
        return lease

    monkeypatch.setattr(runtime.store, 'acquire', displaced)
    with pytest.raises(ViewerTransportUnavailable):
        await runtime.handle(viewer, dict(type='touch_open', capture_epoch=EPOCH, frame_width=960, frame_height=540))
    assert runtime.available and runtime.viewers[replacement.session] is replacement
    replacement.ws.send_json.assert_not_awaited()
    assert not any(c.args[0]['type'] == 'continuous_input_open' for c in agent.send_json.call_args_list)


@pytest.mark.asyncio
async def test_shared_subscription_failure_still_fences_runtime_without_retry_or_input_replay(live, monkeypatch):
    runtime, viewer, agent = await open_view(live)
    monkeypatch.setattr(runtime.pubsub, 'get_message', AsyncMock(side_effect=RedisConnectionError('fixture outage')))
    await eventually(lambda: not runtime.available)
    await eventually(lambda: runtime.task.done())
    assert viewer.closing or viewer.lease is None
    assert not any(c.args[0]['type'] == 'continuous_input_event' for c in agent.send_json.call_args_list)


@pytest.mark.asyncio
async def test_real_two_worker_heartbeat_path_observes_each_local_boundary_once_or_more(live):
    stages = {
        'viewer_admission', 'redis_lease_operation', 'pubsub_dispatch', 'agent_delivery',
        'agent_reply_relay', 'viewer_receipt_validation', 'viewer_socket_send',
    }

    def counts():
        return {sample.labels['stage']: sample.value
                for family in continuous_stage_duration_seconds.collect()
                for sample in family.samples
                if sample.name.endswith('_count') and sample.labels['outcome'] == 'returned'}

    before = counts()
    runtime, viewer, _ = await open_view(live)
    await runtime.handle(viewer, dict(type='touch_event', sequence=1, gesture=0, action=4, x=0, y=0))
    await eventually(lambda: any(c.args[0].get('sequence') == 1 and c.args[0].get('stage') == 'input'
                                for c in viewer.ws.send_json.call_args_list))
    after = counts()
    assert all(after.get(stage, 0) > before.get(stage, 0) for stage in stages)
    # Instrumentation adds no owner/session payload fields and does not alter the native protocol.
    receipt = next(c.args[0] for c in viewer.ws.send_json.call_args_list if c.args[0].get('sequence') == 1)
    assert set(receipt) == {'type', 'session_id', 'owner', 'capture_epoch', 'sequence', 'status',
                            'stage', 'origin', 'device_uptime_ms'}
