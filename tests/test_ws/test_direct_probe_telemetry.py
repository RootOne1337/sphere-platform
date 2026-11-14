from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.direct_probe_telemetry import native_peer_report
from backend.websocket.stream_session_history import SESSION_BYTES, StreamSessionHistory
from tests.test_ws.test_direct_probe import VIDEO_SDP, eventually
from tests.test_ws.test_direct_probe import peers as peers

HISTORY = '1' * 16
NETWORK = dict(local_candidates=3, remote_candidates=1, pairs=1, checking_pairs=1, failed_pairs=0,
               succeeded_pairs=0, requests_sent=237, requests_received=None, responses_sent=None,
               responses_received=0, dtls_state='new')
SAMPLE = dict(schema_version=1, sequence=1, kind='sample', stage='answer_sent', profile='public-stun',
              elapsed_ms=1000, answer_sent=True, network=NETWORK,
              network_sample_elapsed_ms=900, network_sample_age_ms=100)


def message(sid='a' * 32, **changes):
    return dict(type='direct_probe_telemetry', session_id=sid, sample=SAMPLE | changes)


@pytest.mark.parametrize('changes', [
    {'schema_version': True}, {'sequence': True}, {'sequence': 2914}, {'stage': 'private exception'},
    {'profile': 'stun:private-endpoint'}, {'answer_sent': 1}, {'elapsed_ms': '1000'},
    {'network_sample_age_ms': 99}, {'network_sample_elapsed_ms': None},
    {'network': None}, {'kind': 'final'}, {'stage': 'closed'},
    {'network': NETWORK | {'address': '192.168.0.1'}},
    {'network': NETWORK | {'requests_sent': 2**53}},
    {'network': NETWORK | {'responses_received': True}},
    {'network': NETWORK | {'succeeded_pairs': 1}},
    {'network': NETWORK | {'dtls_state': 'private-key'}},
])
def test_strict_report_never_retains_private_coerced_or_inconsistent_measurements(changes):
    assert native_peer_report(message(**changes)) is None


def test_unknown_network_is_distinct_from_measured_zero_and_no_client_identity_is_accepted():
    parsed = native_peer_report(message())
    assert parsed and parsed[1].network and parsed[1].network.responses_received == 0
    assert parsed[1].network.requests_received is None
    assert native_peer_report(message(network=None, network_sample_elapsed_ms=None, network_sample_age_ms=None))
    assert native_peer_report(message() | {'org': 'borrowed'}) is None
    assert native_peer_report(message(sid='not-a-peer')) is None
    assert native_peer_report(message(stage='x' * 3000)) is None


async def correlated(peers, monkeypatch, *, user='user'):
    from backend.core.config import settings
    monkeypatch.setattr(settings, 'DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED', True)
    monkeypatch.setattr(settings, 'DIRECT_TRANSPORT_INPUT_ENABLED', False)
    monkeypatch.setattr(settings, 'DIRECT_TRANSPORT_PROBE_DEVICE_IDS', frozenset({'device'}))
    runtimes, clients, _, agent, agent_session, viewer = peers
    await DeviceStatusCache(clients[0]).set_status('device', DeviceLiveStatus(
        device_id='device', status='online', ws_session_id=agent_session, agent_version_code=10255))
    history = StreamSessionHistory(clients[0])
    assert await history.begin('org', 'device', HISTORY, user=user)
    viewer.video = viewer.live = True
    viewer.history_session = HISTORY
    await runtimes[1].open(viewer, VIDEO_SDP)
    await eventually(lambda: agent.send_json.call_count == 1)
    return history, runtimes[0], viewer


@pytest.mark.asyncio
async def test_cross_worker_native_setup_is_correlated_before_answer_without_an_input_grant(peers, monkeypatch):
    history, runtime, viewer = await correlated(peers, monkeypatch)
    native = message(viewer.session, stage='gathering', answer_sent=False)
    assert runtime.observe_native('device', peers[4], native)
    await asyncio.wait_for(runtime.diagnostics.join(), 1)
    rows = await history.read('org', 'device')
    sample = rows[0]['native_direct_samples'][0]
    assert sample['peer_id'] == viewer.session and sample['network']['responses_received'] == 0
    assert sample['network']['requests_received'] is None and sample['network_sample_age_ms'] == 100
    assert sample['answer_sent'] is False
    assert '_viewer_user' not in rows[0] and 'user' not in sample
    assert not viewer.control_session and peers[3].send_json.call_count == 1
    assert viewer.binding == peers[0][0].pending[viewer.session].binding


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['foreign_user', 'closed', 'evicted', 'agent_reconnect', 'lease_replaced'])
async def test_journal_cannot_borrow_or_resurrect_a_viewer_or_agent_generation(peers, monkeypatch, change):
    history, runtime, viewer = await correlated(peers, monkeypatch, user='other' if change == 'foreign_user' else 'user')
    if change == 'closed':
        assert await history.end('org', 'device', HISTORY)
    elif change == 'evicted':
        for index in range(10):
            assert await history.begin('org', 'device', f'new-{index}', user='user')
    elif change == 'agent_reconnect':
        replacement = await peers[2][0].connect(AsyncMock(), 'device', 'android', 'org')
        await DeviceStatusCache(peers[1][0]).set_status('device', DeviceLiveStatus(
            device_id='device', status='online', ws_session_id=replacement))
    elif change == 'lease_replaced':
        await peers[1][0].set(runtime.key('device'), json.dumps({'other': 'lease'}), px=30000)
    runtime.observe_native('device', peers[4], message(viewer.session))
    await asyncio.wait_for(runtime.diagnostics.join(), 1)
    assert all('native_direct_samples' not in row for row in await history.read('org', 'device'))


@pytest.mark.asyncio
async def test_duplicate_out_of_order_and_terminal_reports_cannot_extend_a_peer(peers, monkeypatch):
    history, runtime, viewer = await correlated(peers, monkeypatch)
    assert runtime.observe_native('device', peers[4], message(viewer.session))
    assert not runtime.observe_native('device', peers[4], message(viewer.session))
    assert not runtime.observe_native('device', peers[4], message(viewer.session, sequence=2, elapsed_ms=500,
                                                               network_sample_elapsed_ms=400))
    final = message(viewer.session, sequence=3, kind='final', stage='closed', elapsed_ms=1001,
                    network_sample_age_ms=101)
    assert runtime.observe_native('device', peers[4], final)
    assert not runtime.observe_native('device', peers[4], message(viewer.session, sequence=4))
    await asyncio.wait_for(runtime.diagnostics.join(), 1)
    rows = await history.read('org', 'device')
    assert [sample['kind'] for sample in rows[0]['native_direct_samples']] == ['sample', 'final']
    assert rows[0]['state'] == 'active' and runtime.available
    assert await runtime.remaining(viewer.binding) > 0  # A report never renews/retires media authority.


@pytest.mark.asyncio
async def test_full_diagnostic_queue_and_failed_storage_do_not_block_answer_or_retire_transport(peers, monkeypatch):
    _, runtime, viewer = await correlated(peers, monkeypatch)
    runtime.diagnostic_task.cancel()
    await asyncio.gather(runtime.diagnostic_task, return_exceptions=True)
    pending = runtime.pending[viewer.session]
    for sequence in range(1, 6):
        pending.diagnostic_at = -float('inf')
        accepted = runtime.observe_native('device', peers[4], message(viewer.session, sequence=sequence))
        assert accepted is (sequence <= 4)
    assert runtime.diagnostics.qsize() == 4 and runtime.available
    writer = AsyncMock(side_effect=RuntimeError('storage unavailable'))
    monkeypatch.setattr(StreamSessionHistory, 'native_direct', writer)
    runtime.diagnostic_task = asyncio.create_task(runtime.write_diagnostics())
    await asyncio.wait_for(runtime.diagnostics.join(), 1)
    assert writer.await_count == 4 and runtime.available
    await runtime.agent_message('device', peers[4], dict(type='direct_probe_answer', session_id=viewer.session,
                                                       sdp=VIDEO_SDP.replace('recvonly', 'sendonly')))
    await eventually(lambda: viewer.ws.send_json.call_count == 1)
    assert viewer.answered and runtime.available


@pytest.mark.asyncio
async def test_native_samples_share_the_existing_byte_budget_and_ten_session_retention(peers, monkeypatch):
    history, runtime, viewer = await correlated(peers, monkeypatch)
    for sequence in range(1, 25):
        runtime.pending[viewer.session].diagnostic_at = -float('inf')
        assert runtime.observe_native('device', peers[4], message(viewer.session, sequence=sequence))
        await asyncio.wait_for(runtime.diagnostics.join(), 1)
    row = (await history.read('org', 'device'))[0]
    assert len(row['native_direct_samples']) == 15
    assert row['native_direct_samples'][-1]['sequence'] == 24
    assert len(json.dumps(row).encode()) < SESSION_BYTES


@pytest.mark.asyncio
async def test_retirement_while_redis_is_awaited_drops_the_old_queued_report(peers, monkeypatch):
    history, runtime, viewer = await correlated(peers, monkeypatch)
    entered, released = asyncio.Event(), asyncio.Event()

    async def held_remaining(binding):
        entered.set()
        await released.wait()
        return 10000

    monkeypatch.setattr(runtime, 'remaining', held_remaining)
    assert runtime.observe_native('device', peers[4], message(viewer.session))
    await asyncio.wait_for(entered.wait(), 1)
    runtime.pending.pop(viewer.session)
    released.set()
    await asyncio.wait_for(runtime.diagnostics.join(), 1)
    assert 'native_direct_samples' not in (await history.read('org', 'device'))[0]
