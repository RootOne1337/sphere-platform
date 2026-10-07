"""Same static Lua runs in fakeredis[lua] and an optional real Redis canary.

Optional SPHERE_CONTINUOUS_TEST_REDIS_URL selects an explicitly supplied Redis.
All keys/channels are per-test random audit namespaces, expire in 1500ms and
are removed by exact name. No DB flush, scan, device commands or agent channel.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fakeredis import FakeServer
from fakeredis import aioredis as fake_async
from fakeredis.aioredis import FakeRedis
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError, TimeoutError

from backend.websocket.connection_manager import ConnectionInfo, ConnectionManager
from backend.websocket.continuous_delivery import ContinuousDelivery, deliver_continuous
from backend.websocket.continuous_lease import (
    AUTH_MS,
    LEASE_MS,
    ContinuousLeaseStore,
    InputLease,
    InputLeaseUnavailable,
    LeaseBinding,
    no_replay_redis,
)
from backend.websocket.continuous_protocol import CaptureBinding, TouchEvent

EPOCH = "00112233-4455-6677-8899-aabbccddeeff"


@pytest_asyncio.fixture
async def world():
    url = os.environ.get("SPHERE_CONTINUOUS_TEST_REDIS_URL")
    server = FakeServer()
    # FakeRedis's convenience constructor strips several transport kwargs.
    # Use the same actual bounded pool with a fake connection implementation.
    clients = [no_replay_redis(url) if url else FakeRedis(connection_pool=ConnectionPool(
        connection_class=getattr(fake_async, "FakeAsyncRedisConnection", fake_async.FakeConnection),
        server=server, decode_responses=True,
        max_connections=8, socket_timeout=0.25, socket_connect_timeout=0.25,
        retry=Retry(NoBackoff(), 0), retry_on_error=[], retry_on_timeout=False,
    )) for _ in range(2)]
    namespace = "audit:continuous:" + uuid4().hex
    stores = [ContinuousLeaseStore(client, namespace=namespace) for client in clients]
    binding = LeaseBinding("org_fixture_01", "device_" + uuid4().hex, "user_fixture_01",
                           "worker_fixture_01", "viewer_fixture_01", "agent_fixture_01",
                           CaptureBinding(EPOCH, 960, 540))
    pubsub = clients[1].pubsub()
    await pubsub.subscribe(stores[0].channel(binding))
    await pubsub.get_message(timeout=1)  # Drain subscription acknowledgement.
    try:
        yield stores[0], stores[1], binding, pubsub
    finally:
        await pubsub.aclose()
        await clients[0].delete(stores[0].key(binding))
        for client in clients:
            await client.aclose()


async def published(pubsub):
    for _ in range(3):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if message:
            return json.loads(message["data"])
    pytest.fail("Expected one scoped publication")


def receipt(lease, **changes):
    return {"type": "continuous_input_status", "session_id": lease.binding.viewer_session,
            "owner": lease.owner, "capture_epoch": EPOCH, "sequence": 0, "status": 0,
            "stage": "startup", "origin": "injector", "device_uptime_ms": 12345, **changes}


async def ready(world):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    assert lease is not None
    assert await store.open(lease) == "published"
    await published(pubsub)
    assert await store.receipt(lease, receipt(lease), agent_session=binding.agent_session)
    return lease


async def test_twenty_competing_workers_have_exactly_one_owner(world):
    store, other, binding, _ = world
    results = await asyncio.gather(*[
        (store if i % 2 else other).acquire(replace(binding, viewer_worker=f"worker_fixture_{i:02d}"))
        for i in range(20)
    ], return_exceptions=True)
    # A real bounded 8-connection pool may refuse overload. Wait for ALL
    # attempts before fixture cleanup; no retry or pool-size increase.
    assert all(result is None or isinstance(result, (InputLease, InputLeaseUnavailable)) for result in results)
    winners = [result for result in results if isinstance(result, InputLease)]
    assert len(winners) == 1
    assert len(winners[0].owner) == 32
    assert 0 < await store.redis.pttl(store.key(binding)) <= LEASE_MS


async def test_canonical_identity_roundtrip_and_wire_budget(world):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    assert InputLease.from_identity(lease.identity) == lease
    assert await store.open(lease) == "published"
    envelope = await published(pubsub)
    assert len(json.dumps(envelope, separators=(",", ":")).encode()) <= 2048


async def test_maximum_integer_gesture_is_not_rounded_by_lua_cjson(world):
    store, _, _, pubsub = world
    lease = await ready(world)
    maximum = 2_147_483_647
    assert await store.event(lease, TouchEvent(maximum, maximum, 0, 959, 539)) == "published"
    envelope = await published(pubsub)
    assert type(envelope["command"]["gesture"]) is int
    assert envelope["command"]["gesture"] == maximum


async def test_owner_exclusion_is_global_even_during_device_retenanting(world):
    store, other, binding, _ = world
    assert await store.acquire(binding)
    assert await other.acquire(replace(binding, org="org_fixture_02")) is None


async def test_open_is_sent_once_and_down_requires_native_ready(world):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    assert await store.event(lease, TouchEvent(1, 1, 0, 10, 20)) == "not_ready"
    assert await store.open(lease) == "published"
    envelope = await published(pubsub)
    assert envelope["command"] == {"type": "continuous_input_open", "owner": lease.owner,
                                    "session_id": binding.viewer_session, "capture_epoch": EPOCH,
                                    "frame_width": 960, "frame_height": 540}
    assert await store.open(lease) == "already_sent"
    assert await store.event(lease, TouchEvent(1, 1, 0, 10, 20)) == "not_ready"
    assert await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01) is None


@pytest.mark.parametrize("change", ["owner", "viewer_session", "agent_session", "capture", "org", "user", "viewer_worker"])
async def test_foreign_binding_cannot_renew_cancel_or_release(world, change):
    store, other, binding, _ = world
    lease = await ready(world)
    if change == "owner":
        foreign = replace(lease, owner="foreign_owner_nonce")
    elif change == "capture":
        foreign = replace(lease, binding=replace(binding, capture=CaptureBinding(str(uuid4()), 960, 540)))
    else:
        foreign = replace(lease, binding=replace(binding, **{change: "foreign_identity_01"}))
    assert not await other.authorize(foreign)
    assert await other.close(foreign) == "stale"
    assert not await other.receipt(foreign, receipt(foreign, stage="release", status=3),
                                   agent_session=foreign.binding.agent_session)
    assert await store.redis.hget(store.key(binding), "phase") == "ready"


async def test_down_move_before_up_are_distinct_immediate_publications(world):
    store, other, binding, pubsub = world
    lease = await ready(world)
    for event in [TouchEvent(1, 1, 0, 10, 20), TouchEvent(2, 1, 2, 30, 40), TouchEvent(3, 1, 1, 50, 60)]:
        assert await store.event(lease, event) == "published"
        envelope = await published(pubsub)
        command = await other.delivery_command(envelope, device_id=binding.device,
                                               org_id=binding.org, agent_session=binding.agent_session)
        assert command["action"] == event.action
        assert command["sequence"] == event.sequence
        assert command["x"] == event.x
    assert await store.redis.hget(store.key(binding), "held") == "0"


@pytest.mark.parametrize("event", [TouchEvent(1, 1, 2, 10, 20), TouchEvent(1, 1, 1, 10, 20),
                                  TouchEvent(1, 1, 4, 10, 20)])
async def test_move_up_or_foreign_heartbeat_without_down_retires_owner(world, event):
    store, _, binding, pubsub = world
    lease = await ready(world)
    assert await store.event(lease, event) == "invalid_order"
    assert await store.redis.hget(store.key(binding), "phase") == "closing"
    assert await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01) is None


async def test_duplicate_sequence_cannot_replay_a_down(world):
    store, _, binding, pubsub = world
    lease = await ready(world)
    down = TouchEvent(1, 1, 0, 10, 20)
    assert await store.event(lease, down) == "published"
    await published(pubsub)
    assert await store.event(lease, down) == "invalid_order"
    assert await store.event(lease, TouchEvent(2, 1, 2, 30, 40)) == "closing"
    assert await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01) is None


async def test_gesture_cannot_be_reused_after_up(world):
    store, _, _, pubsub = world
    lease = await ready(world)
    assert await store.event(lease, TouchEvent(1, 1, 0, 10, 20)) == "published"
    await published(pubsub)
    assert await store.event(lease, TouchEvent(2, 1, 1, 10, 20)) == "published"
    await published(pubsub)
    assert await store.event(lease, TouchEvent(3, 1, 0, 10, 20)) == "invalid_order"


async def test_idle_heartbeat_can_keep_startup_alive_without_granting_ready(world):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    await published(pubsub)
    assert await store.event(lease, TouchEvent(1, 0, 4, 0, 0)) == "published"
    await published(pubsub)
    assert await store.redis.hget(store.key(binding), "phase") == "opening_sent"
    assert await store.event(lease, TouchEvent(2, 1, 0, 1, 1)) == "not_ready"


async def test_movement_renewal_does_not_extend_authorization(world):
    store, _, binding, pubsub = world
    lease = await ready(world)
    before = await store.redis.hget(store.key(binding), "auth_until")
    assert await store.event(lease, TouchEvent(1, 0, 4, 0, 0)) == "published"
    await published(pubsub)
    assert await store.redis.hget(store.key(binding), "auth_until") == before
    await store.redis.hset(store.key(binding), "auth_until", 0)
    assert await store.event(lease, TouchEvent(2, 0, 4, 0, 0)) == "auth_expired"
    assert not await store.authorize(lease)  # A retired owner cannot be resurrected.
    assert await store.close(lease) == "published"  # Revocation sends one cancel even after fencing.
    await published(pubsub)
    assert await store.close(lease) == "closing"


async def test_auth_refresh_does_not_keep_a_dead_viewer_alive(world):
    store, _, binding, _ = world
    lease = await ready(world)
    await store.redis.pexpire(store.key(binding), 300)
    assert await store.authorize(lease)
    assert 0 < await store.redis.pttl(store.key(binding)) <= 300
    seconds, microseconds = await store.redis.time()
    assert 0 < int(await store.redis.hget(store.key(binding), "auth_until")) - (seconds * 1000 + microseconds // 1000) <= AUTH_MS


async def test_lease_expiry_and_late_receipt_cannot_release_replacement(world):
    store, other, binding, _ = world
    old = await ready(world)
    await store.redis.pexpire(store.key(binding), 1)
    await asyncio.sleep(0.03)
    new = await other.acquire(replace(binding, viewer_session="new_viewer_session"))
    assert new is not None and new.owner != old.owner
    assert not await store.receipt(old, receipt(old, stage="release", status=3), agent_session=binding.agent_session)
    assert not await store.authorize(old)
    assert await store.redis.hget(store.key(binding), "identity") == new.identity


@pytest.mark.parametrize("changes,origin", [({"session_id": "other_viewer_session"}, "agent_fixture_01"),
                                          ({}, "replaced_agent_session"),
                                          ({"capture_epoch": str(uuid4())}, "agent_fixture_01")])
async def test_receipt_requires_current_authenticated_socket_and_viewer(world, changes, origin):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    await published(pubsub)
    assert not await store.receipt(lease, receipt(lease, **changes), agent_session=origin)
    assert await store.redis.hget(store.key(binding), "phase") == "opening_sent"


async def test_execution_receipt_never_promotes_readiness_and_unknown_release_fences(world):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    await published(pubsub)
    assert not await store.receipt(lease, receipt(lease, stage="input", status=1, sequence=1), agent_session=binding.agent_session)
    assert await store.redis.hget(store.key(binding), "phase") == "opening_sent"
    assert not await store.receipt(lease, receipt(lease, stage="release", status=6), agent_session=binding.agent_session)
    assert await store.redis.hget(store.key(binding), "phase") == "closing"
    assert await store.redis.exists(store.key(binding)) == 1


async def test_close_keeps_ownership_until_known_native_cleanup(world):
    store, other, binding, pubsub = world
    lease = await ready(world)
    assert await store.close(lease) == "published"
    envelope = await published(pubsub)
    assert await other.delivery_command(envelope, device_id=binding.device, org_id=binding.org,
                                        agent_session=binding.agent_session) == {"type": "continuous_input_close", "owner": lease.owner}
    assert await other.acquire(binding) is None
    assert await store.receipt(lease, receipt(lease, stage="release", status=3), agent_session=binding.agent_session)
    assert await other.acquire(binding)


@pytest.mark.parametrize("scope", [{"agent_session": "agent_replacement"}, {"org_id": "org_replacement"},
                                  {"device_id": "device_replacement"}])
async def test_other_socket_tenant_or_device_cannot_receive_scoped_open(world, scope):
    store, other, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    origin = {"device_id": binding.device, "org_id": binding.org, "agent_session": binding.agent_session, **scope}
    assert await other.delivery_command(envelope, **origin) is None


async def test_stale_queued_command_and_future_clock_claim_are_not_delivered(world):
    store, other, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    seconds, micros = await store.redis.time()
    now = seconds * 1000 + micros // 1000
    scope = {"device_id": binding.device, "org_id": binding.org, "agent_session": binding.agent_session}
    assert await other.delivery_command({**envelope, "expires_at_ms": now - 1}, **scope) is None
    assert await other.delivery_command({**envelope, "expires_at_ms": now + 10_000}, **scope) is None
    assert await other.delivery_command({**envelope, "expires_at_ms": True}, **scope) is None


@pytest.mark.parametrize("mutation", ["extra", "owner", "capture", "boolean", "native_type", "identity_extra"])
async def test_corrupt_internal_envelope_cannot_forward_unvalidated_commands(world, mutation):
    store, other, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    if mutation == "extra":
        envelope["command"]["shell"] = "private_command"
    elif mutation == "owner":
        envelope["command"]["owner"] = "foreign_nonce_01"
    elif mutation == "capture":
        envelope["command"]["capture_epoch"] = str(uuid4())
    elif mutation == "boolean":
        envelope["command"]["frame_width"] = True
    elif mutation == "native_type":
        envelope["command"] = {"type": "shell", "owner": lease.owner}
    else:
        raw = json.loads(envelope["identity"])
        raw["extra"] = 1
        envelope["identity"] = json.dumps(raw)
    assert await other.delivery_command(envelope, device_id=binding.device,
                                        org_id=binding.org, agent_session=binding.agent_session) is None


async def test_no_subscriber_is_not_success_and_never_uses_offline_queue(world):
    store, _, binding, pubsub = world
    await pubsub.unsubscribe()
    await pubsub.get_message(timeout=1)
    lease = await store.acquire(binding)
    assert await store.open(lease) == "no_subscriber"
    assert await store.redis.hget(store.key(binding), "phase") == "closing"
    assert await store.open(lease) == "closing"


async def test_outside_frame_is_rejected_before_any_redis_command(world):
    store, _, _, _ = world
    lease = await ready(world)
    with pytest.raises(ValueError, match="outside"):
        await store.event(lease, TouchEvent(1, 1, 0, 960, 539))


@pytest.mark.parametrize("failure", [TimeoutError("private_timeout_detail"), ConnectionError("private_socket_detail")])
async def test_uncertain_redis_mutation_is_not_retried_or_exposed(failure):
    client = AsyncMock()
    client.eval.side_effect = failure
    binding = LeaseBinding("org_fixture_01", "device_fixture_01", "user_fixture_01", "worker_fixture_01",
                           "viewer_fixture_01", "agent_fixture_01", CaptureBinding(EPOCH, 960, 540))
    with pytest.raises(InputLeaseUnavailable, match="^continuous_input_transport_unavailable$"):
        await ContinuousLeaseStore(client).acquire(binding)
    assert client.eval.await_count == 1


async def test_operation_deadline_cancels_one_attempt_without_replay():
    async def stuck(*args):
        await asyncio.sleep(10)
    client = AsyncMock()
    client.eval.side_effect = stuck
    binding = LeaseBinding("org_fixture_01", "device_fixture_01", "user_fixture_01", "worker_fixture_01",
                           "viewer_fixture_01", "agent_fixture_01", CaptureBinding(EPOCH, 960, 540))
    with pytest.raises(InputLeaseUnavailable):
        await ContinuousLeaseStore(client).acquire(binding)
    assert client.eval.await_count == 1


async def test_dedicated_client_has_no_retry_even_when_url_tries_to_override():
    with pytest.raises(ValueError, match="query options"):
        no_replay_redis("redis://127.0.0.1:6379/0?retry_on_timeout=true")
    client = no_replay_redis("redis://127.0.0.1:6379/0")
    try:
        kwargs = client.connection_pool.connection_kwargs
        assert kwargs["retry"]._retries == 0
        assert kwargs["retry_on_timeout"] is False
        assert kwargs["retry_on_error"] == []
        assert kwargs["socket_timeout"] == 0.25
        assert client.connection_pool.max_connections == 8
    finally:
        await client.aclose()


async def test_application_retrying_pool_is_refused_before_any_io():
    client = Redis.from_url("redis://127.0.0.1:1/0", retry_on_timeout=True,
                            max_connections=50, socket_timeout=5)
    try:
        with pytest.raises(ValueError, match="bounded non-retrying"):
            ContinuousLeaseStore(client)
        assert not client.connection_pool._in_use_connections
    finally:
        await client.aclose()


def connected_manager(binding, socket, *, agent_type="android"):
    manager = ConnectionManager()
    manager._connections[binding.device] = ConnectionInfo(
        socket, binding.device, agent_type, binding.org, binding.agent_session,
    )
    return manager


async def test_receiver_sends_only_original_command_to_exact_android_socket(world):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    socket = AsyncMock()
    manager = connected_manager(binding, socket)
    assert await deliver_continuous(store, manager, binding.device, envelope) == ContinuousDelivery.SOCKET_SENT
    socket.send_json.assert_awaited_once_with(envelope["command"])
    assert await store.redis.hget(store.key(binding), "phase") == "opening_sent"  # Send is not READY.


async def test_socket_replacement_during_redis_guard_never_receives_old_command(world, monkeypatch):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    old_socket, replacement_socket = AsyncMock(), AsyncMock()
    manager = connected_manager(binding, old_socket)
    original = store.delivery_command

    async def replace_after_guard(*args, **kwargs):
        command = await original(*args, **kwargs)
        manager._connections[binding.device] = ConnectionInfo(
            replacement_socket, binding.device, "android", binding.org, "new_agent_session",
        )
        return command

    monkeypatch.setattr(store, "delivery_command", replace_after_guard)
    assert await deliver_continuous(store, manager, binding.device, envelope) == ContinuousDelivery.UNKNOWN
    old_socket.send_json.assert_not_awaited()
    replacement_socket.send_json.assert_not_awaited()
    assert await store.redis.hget(store.key(binding), "phase") == "closing"


@pytest.mark.parametrize("reason", ["disconnected", "pc", "tenant"])
async def test_wrong_connection_scope_is_rejected_without_socket_write(world, reason):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    socket = AsyncMock()
    manager = connected_manager(binding, socket)
    if reason == "disconnected":
        manager._connections.clear()
    elif reason == "pc":
        manager._connections[binding.device].agent_type = "pc"
    else:
        manager._connections[binding.device].org_id = "other_tenant_session"
    assert await deliver_continuous(store, manager, binding.device, envelope) == ContinuousDelivery.REJECTED
    socket.send_json.assert_not_awaited()


@pytest.mark.parametrize("reason", ["failure", "timeout"])
async def test_socket_loss_is_unknown_fenced_and_never_replayed(world, reason):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    socket = AsyncMock()
    if reason == "failure":
        socket.send_json.side_effect = RuntimeError("private_socket_error")
    else:
        async def stuck(*args):
            await asyncio.sleep(10)
        socket.send_json.side_effect = stuck
    manager = connected_manager(binding, socket)
    assert await deliver_continuous(store, manager, binding.device, envelope) == ContinuousDelivery.UNKNOWN
    socket.send_json.assert_awaited_once()
    assert await store.redis.hget(store.key(binding), "phase") == "closing"
    assert await deliver_continuous(store, manager, binding.device, envelope) == ContinuousDelivery.REJECTED
    socket.send_json.assert_awaited_once()


async def test_cancelled_socket_write_fences_without_replaying_and_preserves_cancellation(world):
    store, _, binding, pubsub = world
    lease = await store.acquire(binding)
    await store.open(lease)
    envelope = await published(pubsub)
    writing = asyncio.Event()
    socket = AsyncMock()

    async def wait_after_consumption(*args):
        writing.set()
        await asyncio.sleep(10)

    socket.send_json.side_effect = wait_after_consumption
    manager = connected_manager(binding, socket)
    task = asyncio.create_task(deliver_continuous(store, manager, binding.device, envelope))
    await writing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    socket.send_json.assert_awaited_once()
    assert await store.redis.hget(store.key(binding), "phase") == "closing"
    assert await deliver_continuous(store, manager, binding.device, envelope) == ContinuousDelivery.REJECTED
    socket.send_json.assert_awaited_once()
