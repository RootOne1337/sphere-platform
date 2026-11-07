from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from backend.websocket.channels import ChannelPattern
from backend.websocket.direct_probe_protocol import InvalidDirectProbe
from backend.websocket.stream_bridge import VideoStreamBridge
from backend.websocket.video_delivery import delivery_mode, select_delivery

IDR = b"\x00\x00\x00\x01\x65\x42"
P = b"\x00\x00\x00\x01\x41\x42"
SPS = b"\x00\x00\x00\x01\x67\x42"


def test_media_handover_never_accepts_commands_identity_or_partial_fields():
    assert delivery_mode({"type": "video_delivery", "mode": "legacy"}) == (True, None)
    assert delivery_mode({"type": "video_delivery", "mode": "direct", "peer_session": "a" * 32}) == (False, "a" * 32)
    for value in [None, [], {"type": "viewer_telemetry", "sample": {"mode": "direct"}},
                  {"type": "video_delivery", "mode": "direct"},
                  {"type": "video_delivery", "mode": "direct", "peer_session": 1},
                  {"type": "video_delivery", "mode": "legacy", "user": "other"},
                  {"type": "video_delivery", "mode": "direct", "peer_session": "a" * 32, "command": "tap"}]:
        with pytest.raises(ValueError):
            delivery_mode(value)


@pytest.mark.asyncio
async def test_unbound_peer_cannot_retire_a_viewer_copy():
    bridge, runtime = AsyncMock(), AsyncMock()
    runtime.video_peer.return_value = False
    kwargs = dict(runtime=runtime, bridge=bridge, device="device", org="org", user="user", viewer_session="own")
    with pytest.raises(InvalidDirectProbe):
        await select_delivery({"type": "video_delivery", "mode": "direct", "peer_session": "a" * 32}, **kwargs)
    bridge.set_legacy_delivery.assert_not_awaited()
    assert await select_delivery({"type": "video_delivery", "mode": "legacy"}, **kwargs) == "legacy"
    bridge.set_legacy_delivery.assert_awaited_once_with("device", "own", True)


@pytest.mark.asyncio
async def test_direct_only_worker_keeps_capture_alive_and_other_workers_receive_fallback():
    server = FakeServer()
    clients = [FakeRedis(server=server, decode_responses=False) for _ in range(2)]
    managers = [AsyncMock(), AsyncMock()]
    bridges = [VideoStreamBridge(manager, client) for manager, client in zip(managers, clients)]
    direct, fallback = AsyncMock(), AsyncMock()
    try:
        await bridges[0].register_viewer("device", direct, "direct")
        await bridges[0].set_legacy_delivery("device", "direct", False)
        presence = ChannelPattern.video_presence("device")
        legacy = ChannelPattern.video_stream("device")
        assert dict(await clients[1].pubsub_numsub(presence))[presence.encode()] == 1
        assert dict(await clients[1].pubsub_numsub(legacy))[legacy.encode()] == 0
        assert await bridges[1].transport.has_viewers("device")
        await bridges[1].register_viewer("device", fallback, "fallback")
        assert dict(await clients[0].pubsub_numsub(legacy))[legacy.encode()] == 1
        await bridges[0].handle_agent_frame("device", IDR)
        async with asyncio.timeout(1):
            while not fallback.send_bytes.await_count:
                await asyncio.sleep(.005)
        fallback.send_bytes.assert_awaited_once_with(IDR)
        direct.send_bytes.assert_not_awaited()
        await bridges[1].unregister_viewer("device", "fallback")
        assert await bridges[0].set_legacy_delivery("device", "direct", True)
        await bridges[1].handle_agent_frame("device", P)
        await asyncio.sleep(.02)
        direct.send_bytes.assert_not_awaited()  # A resumed chain cannot start with a delta picture.
        await bridges[1].handle_agent_frame("device", SPS)
        await bridges[1].handle_agent_frame("device", IDR)
        async with asyncio.timeout(1):
            while direct.send_bytes.await_count < 2:
                await asyncio.sleep(.005)
        assert [call.args[0] for call in direct.send_bytes.await_args_list] == [SPS, IDR]
        assert await bridges[0].transport.has_viewers("device")
    finally:
        for bridge in bridges:
            await bridge.close()
        for client in clients:
            await client.aclose()


@pytest.mark.asyncio
async def test_missing_presentation_renewal_restores_legacy_and_retired_timer_cannot_touch_replacement(monkeypatch):
    monkeypatch.setattr("backend.websocket.stream_bridge.DIRECT_DELIVERY_SECONDS", .02)
    bridge = VideoStreamBridge(AsyncMock())
    ws = AsyncMock()
    try:
        await bridge.register_viewer("device", ws, "viewer")
        await bridge.set_legacy_delivery("device", "viewer", False)
        async with asyncio.timeout(1):
            while not bridge._viewers["device"]["viewer"].legacy:
                await asyncio.sleep(.005)
        bridge.manager.send_to_device.assert_awaited_with("device", {"type": "viewer_connected"})
        await bridge.set_legacy_delivery("device", "viewer", False)
        old = bridge._viewers["device"]["viewer"]
        old.direct_until = time.monotonic() - 1
        await bridge.unregister_viewer("device", "viewer")
        await bridge.register_viewer("device", ws, "viewer")
        await asyncio.sleep(.03)
        replacement = bridge._viewers["device"]["viewer"]
        assert replacement is not old and replacement.legacy and replacement.delivery_task is None
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_uncertain_unsubscribe_restores_subscription_and_reference_chain(monkeypatch):
    client = FakeRedis(decode_responses=False)
    bridge = VideoStreamBridge(AsyncMock(), client)
    try:
        await bridge.register_viewer("device", AsyncMock(), "viewer")
        unsubscribe = bridge.transport.unsubscribe

        async def uncertain(device):
            await unsubscribe(device)
            raise OSError("acknowledgement lost")

        monkeypatch.setattr(bridge.transport, "unsubscribe", uncertain)
        with pytest.raises(OSError):
            await bridge.set_legacy_delivery("device", "viewer", False)
        async with asyncio.timeout(2):
            while bridge._viewers["device"]["viewer"].direct_until:
                await asyncio.sleep(.005)
        topic = ChannelPattern.video_stream("device")
        assert dict(await client.pubsub_numsub(topic))[topic.encode()] == 1
        bridge.manager.send_to_device.assert_awaited_with("device", {"type": "viewer_connected"})
        monkeypatch.setattr(bridge.transport, "unsubscribe", unsubscribe)
    finally:
        await bridge.close()
        await client.aclose()


@pytest.mark.asyncio
async def test_reference_recovery_retries_when_command_transport_is_temporarily_unavailable(monkeypatch):
    monkeypatch.setattr("backend.websocket.stream_bridge.DIRECT_DELIVERY_SECONDS", .01)
    bridge = VideoStreamBridge(AsyncMock())
    try:
        await bridge.register_viewer("device", AsyncMock(), "viewer")
        bridge.send_control = AsyncMock(side_effect=[False, True])
        await bridge.set_legacy_delivery("device", "viewer", False)
        async with asyncio.timeout(2):
            while bridge._viewers["device"]["viewer"].direct_until:
                await asyncio.sleep(.005)
        assert bridge.send_control.await_count == 2
        assert bridge._viewers["device"]["viewer"].legacy
    finally:
        await bridge.close()
