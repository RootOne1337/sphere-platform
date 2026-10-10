from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.direct_probe_protocol import (
    InvalidDirectProbe,
    agent_answer,
    description,
    viewer_offer,
)
from backend.websocket.direct_probe_runtime import DirectProbeRuntime, ProbeViewer

SDP = "v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=fingerprint:sha-256 " + ":".join(["AB"] * 32) + "\r\n"
VIDEO_SDP = SDP + "m=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\na=rtpmap:96 H264/90000\r\n"


@pytest.mark.parametrize("change", [None, 12, "", SDP + "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
                                    SDP.replace("sha-256", "sha-1"), SDP * 500,
                                    SDP + "a=candidate:x\r\n" * 65],
                         ids=["null", "number", "empty", "video", "weak_hash", "large", "candidate_count"])
def test_rejects_non_data_channel_or_unbounded_sdp(change):
    with pytest.raises(InvalidDirectProbe):
        description(change)


def test_strict_probe_contract_never_accepts_commands_or_client_identity():
    assert viewer_offer(dict(type="direct_probe_offer", sdp=SDP)) == SDP
    for data in [dict(type="tap", sdp=SDP), dict(type="direct_probe_offer", sdp=SDP, device="other"), []]:
        with pytest.raises(InvalidDirectProbe):
            viewer_offer(data)
    with pytest.raises(InvalidDirectProbe):
        agent_answer(dict(type="direct_probe_answer", session_id="wrong", sdp=SDP))


def test_video_has_separate_readonly_offer_and_sendonly_answer_contract():
    assert description(VIDEO_SDP, video=True) == VIDEO_SDP
    assert description(VIDEO_SDP.replace("recvonly", "sendonly"), video=True, offer=False)
    for bad in [SDP, VIDEO_SDP.replace("recvonly", "sendrecv"), VIDEO_SDP + "a=sendonly\r\n",
                VIDEO_SDP + "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n", VIDEO_SDP + "m=video 9 x\r\n",
                VIDEO_SDP.replace("H264", "VP8"), VIDEO_SDP.replace("sha-256", "sha-1")]:
        with pytest.raises(InvalidDirectProbe):
            description(bad, video=True)
    with pytest.raises(InvalidDirectProbe):
        description(VIDEO_SDP)
    with pytest.raises(InvalidDirectProbe):
        description(VIDEO_SDP, video=True, offer=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted,version", [(False, 10251), (True, 10250), (True, None)])
async def test_video_requires_its_own_server_gate_and_native_version(peers, monkeypatch, admitted, version):
    from backend.core.config import settings
    runtime = peers[0][1]
    monkeypatch.setattr(settings, "DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED", admitted)
    monkeypatch.setattr(settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({"device"}))
    await DeviceStatusCache(peers[1][0]).set_status("device", DeviceLiveStatus(
        device_id="device", status="online", ws_session_id=peers[4], agent_version_code=version))
    with pytest.raises(InvalidDirectProbe, match="video_probe_not_admitted"):
        await runtime.open(ProbeViewer("device", "org", "user", AsyncMock(), video=True), VIDEO_SDP)
    assert await peers[1][0].get(runtime.key("device")) is None
    assert peers[3].send_json.call_count == 0


@pytest.mark.asyncio
async def test_cross_worker_video_preserves_readonly_scope_and_rejects_echo_answer(peers, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED", True)
    monkeypatch.setattr(settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({"device"}))
    await DeviceStatusCache(peers[1][0]).set_status("device", DeviceLiveStatus(
        device_id="device", status="online", ws_session_id=peers[4], agent_version_code=10251))
    viewer = peers[-1]
    viewer.video = True
    await peers[0][1].open(viewer, VIDEO_SDP)
    await eventually(lambda: peers[3].send_json.call_count == 1)
    sent = peers[3].send_json.call_args.args[0]
    assert sent["media"] == "readonly_video_v1" and 0 < sent["ttl_ms"] <= 30000
    assert "media" in viewer.binding
    with pytest.raises(InvalidDirectProbe):
        await peers[0][0].agent_message("device", peers[4], dict(type="direct_probe_answer", session_id=viewer.session, sdp=SDP))
    await peers[0][0].agent_message("device", peers[4], dict(type="direct_probe_answer", session_id=viewer.session,
                                                             sdp=VIDEO_SDP.replace("recvonly", "sendonly")))
    await eventually(lambda: viewer.ws.send_json.call_count == 1)
    await peers[0][1].retire(viewer)
    await eventually(lambda: peers[3].send_json.call_count == 2)
    assert peers[3].send_json.call_args.args[0] == dict(type="direct_probe_close", session_id=viewer.session)
    assert await peers[1][0].get(peers[0][0].key("device")) is None


async def eventually(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(.005)


async def live_offer(peers, monkeypatch):
    from backend.core.config import settings
    monkeypatch.setattr(settings, "DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED", True)
    monkeypatch.setattr(settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({"device"}))
    await DeviceStatusCache(peers[1][0]).set_status("device", DeviceLiveStatus(
        device_id="device", status="online", ws_session_id=peers[4], agent_version_code=10252))
    viewer = peers[-1]
    viewer.video = viewer.live = True
    await peers[0][1].open(viewer, VIDEO_SDP)
    await eventually(lambda: peers[3].send_json.call_count == 1)
    await peers[0][0].agent_message("device", peers[4], dict(type="direct_probe_answer", session_id=viewer.session,
        sdp=VIDEO_SDP.replace("recvonly", "sendonly")))
    await eventually(lambda: viewer.answered)
    return viewer


@pytest.mark.asyncio
async def test_live_video_renews_exact_cross_worker_lease_and_delivers_native_ttl(peers, monkeypatch):
    viewer = await live_offer(peers, monkeypatch)
    runtimes, clients, _, agent, _, _ = peers
    assert agent.send_json.call_args.args[0]["media"] == "live_video_v1"
    await clients[0].pexpire(runtimes[0].key("device"), 10000)
    await runtimes[1].renew(viewer, 1)
    await eventually(lambda: agent.send_json.call_count == 2)
    message = agent.send_json.call_args.args[0]
    assert message["type"] == "direct_probe_renew" and message["session_id"] == viewer.session
    assert message["sequence"] == 1 and 25000 < message["ttl_ms"] <= 30000
    assert await runtimes[1].remaining(viewer.binding) > 25000
    assert set(message) == {"type", "session_id", "sequence", "ttl_ms"}


@pytest.mark.asyncio
@pytest.mark.parametrize("sequence", [True, 0, 2, "1", 1000001])
async def test_live_renewal_rejects_nonsequential_or_unbounded_messages(peers, monkeypatch, sequence):
    viewer = await live_offer(peers, monkeypatch)
    with pytest.raises(InvalidDirectProbe, match="invalid_video_renewal"):
        await peers[0][1].renew(viewer, sequence)
    assert peers[3].send_json.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["expired", "replacement", "agent_reconnect", "revoked"])
async def test_live_renewal_cannot_resurrect_expired_replaced_or_revoked_ownership(peers, monkeypatch, change):
    from backend.core.config import settings
    viewer = await live_offer(peers, monkeypatch)
    runtimes, clients, _, agent, _, _ = peers
    key = runtimes[0].key("device")
    if change == "expired":
        await clients[0].delete(key)
    elif change == "replacement":
        await clients[0].set(key, runtimes[0].encode(dict(viewer.binding, session="b" * 32)), px=30000)
    elif change == "agent_reconnect":
        await DeviceStatusCache(clients[0]).set_status("device", DeviceLiveStatus(
            device_id="device", status="online", ws_session_id="replacement", agent_version_code=10252))
    else:
        monkeypatch.setattr(settings, "DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED", False)
    before = await clients[0].get(key)
    with pytest.raises(InvalidDirectProbe, match="video_renewal_rejected"):
        await runtimes[1].renew(viewer, 1)
    assert await clients[0].get(key) == before and agent.send_json.call_count == 1


@pytest.mark.asyncio
async def test_live_renewal_rate_and_duplicate_fence_do_not_extend_another_peer(peers, monkeypatch):
    viewer = await live_offer(peers, monkeypatch)
    await peers[0][1].renew(viewer, 1)
    await eventually(lambda: peers[3].send_json.call_count == 2)
    for sequence in (1, 2):
        with pytest.raises(InvalidDirectProbe, match="invalid_video_renewal"):
            await peers[0][1].renew(viewer, sequence)
    assert peers[3].send_json.call_count == 2


@pytest.mark.asyncio
async def test_finite_probe_cannot_borrow_live_video_renewal(peers):
    await offer(peers)
    with pytest.raises(InvalidDirectProbe, match="invalid_video_renewal"):
        await peers[0][1].renew(peers[-1], 1)


@pytest_asyncio.fixture
async def peers():
    server = FakeServer()
    clients = [FakeRedis(server=server) for _ in range(2)]
    managers = [ConnectionManager(), ConnectionManager()]
    runtimes = [DirectProbeRuntime(client, manager, namespace="test:direct") for client, manager in zip(clients, managers)]
    agent = AsyncMock()
    session = await managers[0].connect(agent, "device", "android", "org")
    await DeviceStatusCache(clients[0]).set_status("device", DeviceLiveStatus(
        device_id="device", status="online", ws_session_id=session))
    for runtime in runtimes:
        await runtime.start()
    viewer = ProbeViewer("device", "org", "user", AsyncMock())
    try:
        yield runtimes, clients, managers, agent, session, viewer
    finally:
        for runtime in reversed(runtimes):
            await runtime.stop()


async def offer(peers):
    runtimes, _, _, agent, _, viewer = peers
    await runtimes[1].open(viewer, SDP)
    await eventually(lambda: agent.send_json.call_count == 1)
    return agent.send_json.call_args.args[0]


@pytest.mark.asyncio
async def test_cross_worker_answer_and_exact_close_no_offline_queue(peers):
    runtimes, clients, _, agent, session, viewer = peers
    sent = await offer(peers)
    assert sent["type"] == "direct_probe_offer" and 0 < sent["ttl_ms"] <= 30000
    await asyncio.gather(*[runtimes[0].agent_message("device", session,
        dict(type="direct_probe_answer", session_id=viewer.session, sdp=SDP)) for _ in range(2)])
    await eventually(lambda: viewer.ws.send_json.call_count == 1)
    assert viewer.ws.send_json.call_args.args[0]["session_id"] == viewer.session
    await runtimes[0].agent_message("device", session,
        dict(type="direct_probe_answer", session_id=viewer.session, sdp=SDP))
    await asyncio.sleep(.03)
    assert viewer.ws.send_json.call_count == 1
    await runtimes[1].retire(viewer)
    await eventually(lambda: agent.send_json.call_count == 2)
    assert agent.send_json.call_args.args[0] == dict(type="direct_probe_close", session_id=viewer.session)
    assert await clients[0].get(runtimes[0].key("device")) is None
    assert not runtimes[0].pending and not runtimes[1].viewers


@pytest.mark.asyncio
async def test_global_device_limit_and_tenant_mismatch(peers):
    runtimes, _, _, agent, _, _ = peers
    await offer(peers)
    with pytest.raises(InvalidDirectProbe, match="device_probe_busy"):
        await runtimes[0].open(ProbeViewer("device", "org", "other_user", AsyncMock()), SDP)
    other = ProbeViewer("device", "other_org", "intruder", AsyncMock())
    # A different tenant cannot route an offer even if a caller skipped its API check.
    await runtimes[1].retire(peers[-1])
    await eventually(lambda: agent.send_json.call_count == 2)
    await runtimes[1].open(other, SDP)
    await asyncio.sleep(.03)
    assert agent.send_json.call_count == 2


@pytest.mark.asyncio
async def test_reconnect_and_expired_binding_cannot_deliver_answer(peers):
    runtimes, clients, managers, _, old, viewer = peers
    await offer(peers)
    new = await managers[0].connect(AsyncMock(), "device", "android", "org")
    await DeviceStatusCache(clients[0]).set_status("device", DeviceLiveStatus(
        device_id="device", status="online", ws_session_id=new))
    for session in (old, new):
        await runtimes[0].agent_message("device", session, dict(type="direct_probe_answer", session_id=viewer.session, sdp=SDP))
    assert viewer.ws.send_json.call_count == 0
    await clients[0].delete(runtimes[0].key("device"))
    await runtimes[0].agent_message("device", new, dict(type="direct_probe_answer", session_id=viewer.session, sdp=SDP))
    assert viewer.ws.send_json.call_count == 0


@pytest.mark.asyncio
async def test_late_close_does_not_delete_new_owner(peers):
    runtimes, clients, _, _, _, viewer = peers
    await offer(peers)
    old_binding = dict(viewer.binding)
    replacement = dict(old_binding, session="a" * 32)
    await clients[0].set(runtimes[0].key("device"), runtimes[0].encode(replacement), px=30000)
    assert await runtimes[0].remaining(old_binding) == 0
    await runtimes[1].retire(viewer)
    assert json.loads(await clients[0].get(runtimes[0].key("device"))) == replacement


@pytest.mark.asyncio
async def test_expired_offer_is_not_replayed_and_pending_is_bounded(peers):
    runtimes, clients, _, agent, _, viewer = peers
    await offer(peers)
    binding = dict(viewer.binding)
    await clients[0].delete(runtimes[0].key("device"))
    await runtimes[0].route("test:direct:agent:device", runtimes[0].encode(dict(kind="offer", binding=binding, sdp=SDP)))
    assert agent.send_json.call_count == 1


@pytest.mark.asyncio
async def test_disabled_endpoint_never_authorizes_or_starts_probe(monkeypatch):
    from backend.api.ws.direct import router
    socket = AsyncMock()
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", False)
    auth = AsyncMock()
    monkeypatch.setattr(router, "authorize", auth)
    await router.direct_probe_ws(socket, "device")
    auth.assert_not_awaited()
    socket.receive_text.assert_not_awaited()
    socket.close.assert_awaited_once_with(code=4003, reason="direct_probe_disabled")


@pytest.mark.asyncio
async def test_unauthorized_endpoint_never_routes_sdp(peers, monkeypatch):
    from fastapi import HTTPException

    from backend.api.ws.direct import router
    runtime = peers[0][1]
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", True)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({"device"}))
    monkeypatch.setattr(router, "get_direct_probe_runtime", lambda: runtime)
    monkeypatch.setattr(router, "authorize", AsyncMock(side_effect=HTTPException(403)))
    socket = AsyncMock()
    socket.receive_text.return_value = '{"token":"not_a_user_token"}'
    await router.direct_probe_ws(socket, "device")
    assert not runtime.viewers
    assert peers[3].send_json.call_count == 0
    socket.close.assert_awaited_once_with(code=4003, reason="direct_probe_rejected_or_expired")


@pytest.mark.asyncio
async def test_enabled_without_device_allowlist_still_denies_before_auth(peers, monkeypatch):
    from backend.api.ws.direct import router
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", True)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset())
    monkeypatch.setattr(router, "get_direct_probe_runtime", lambda: peers[0][1])
    auth = AsyncMock()
    monkeypatch.setattr(router, "authorize", auth)
    socket = AsyncMock()
    await router.direct_probe_ws(socket, "device")
    auth.assert_not_awaited()
    socket.close.assert_awaited_once_with(code=4003, reason="direct_probe_device_disabled")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disconnect", "closed", "slow"])
async def test_explicit_browser_stop_and_socket_close_race_still_retires_lease(peers, monkeypatch, failure):
    from fastapi import WebSocketDisconnect

    from backend.api.ws.direct import router
    runtime = peers[0][1]
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", True)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({"device"}))
    monkeypatch.setattr(router, "get_direct_probe_runtime", lambda: runtime)
    monkeypatch.setattr(router, "authorize", AsyncMock(return_value=("org", "user")))
    socket = AsyncMock()
    socket.receive_text.side_effect = ['{"token":"fixture"}',
        json.dumps(dict(type="direct_probe_offer", sdp=SDP)), '{"type":"direct_probe_close"}']
    if failure == "slow":
        async def slow_close(**kwargs):
            await asyncio.sleep(5)
        socket.close.side_effect = slow_close
    else:
        socket.close.side_effect = WebSocketDisconnect(1006) if failure == "disconnect" else RuntimeError("already closed")
    async with asyncio.timeout(2):
        await router.direct_probe_ws(socket, "device")
    assert not runtime.viewers
    assert await peers[1][1].get(runtime.key("device")) is None
    assert runtime.available and not runtime.task.done()


@pytest.mark.asyncio
async def test_runtime_capacity_reserves_before_redis_await(peers, monkeypatch):
    runtime = peers[0][1]
    ready, release = asyncio.Event(), asyncio.Event()
    async def slow_open(viewer, sdp):
        ready.set()
        await release.wait()
    monkeypatch.setattr(runtime, "_open", slow_open)
    tasks = [asyncio.create_task(runtime.open(ProbeViewer(str(i), "org", "user", AsyncMock()), SDP)) for i in range(8)]
    await ready.wait()
    await asyncio.sleep(0)
    with pytest.raises(InvalidDirectProbe, match="probe_unavailable"):
        await runtime.open(ProbeViewer("overflow", "org", "user", AsyncMock()), SDP)
    release.set()
    await asyncio.gather(*tasks)
    assert runtime.reservations == 0


@pytest.mark.asyncio
async def test_listener_failure_retires_lease_and_socket_without_resubscribe(peers):
    runtime = peers[0][1]
    viewer = peers[-1]
    await offer(peers)
    runtime.pubsub.get_message = AsyncMock(side_effect=ConnectionError("fixture"))
    await eventually(lambda: not runtime.available)
    await eventually(lambda: viewer.ws.close.call_count == 1)
    assert not runtime.viewers
    assert await peers[1][1].get(runtime.key("device")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["closed", "slow"])
async def test_failed_viewer_answer_retires_only_that_viewer(peers, failure):
    runtime = peers[0][1]
    viewer = peers[-1]
    await offer(peers)
    if failure == "closed":
        viewer.ws.send_json.side_effect = BrokenPipeError("fixture")
    else:
        async def slow_send(*args):
            await asyncio.sleep(5)
        viewer.ws.send_json.side_effect = slow_send
    await peers[0][0].agent_message("device", peers[4],
        dict(type="direct_probe_answer", session_id=viewer.session, sdp=SDP))
    async with asyncio.timeout(2):
        while viewer.session in runtime.viewers:
            await asyncio.sleep(.005)
    await eventually(lambda: viewer.ws.close.call_count == 1)
    assert runtime.available and not runtime.task.done()
    assert await peers[1][1].get(runtime.key("device")) is None
    next_viewer = ProbeViewer("device", "org", "next_user", AsyncMock())
    await runtime.open(next_viewer, SDP)
    await eventually(lambda: next_viewer.session in peers[0][0].pending)
    await peers[0][0].agent_message("device", peers[4],
        dict(type="direct_probe_answer", session_id=next_viewer.session, sdp=SDP))
    await eventually(lambda: next_viewer.ws.send_json.call_count == 1)
    assert next_viewer.answered
