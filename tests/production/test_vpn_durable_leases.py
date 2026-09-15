"""Durable VPN ownership under real SQL transactions and simulated router faults."""

import asyncio
import ipaddress
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.device import Device
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.awg_config import AWGConfigBuilder
from backend.services.vpn.ip_pool import IPPoolAllocator
from backend.services.vpn.pool_service import VPNPoolService


@pytest_asyncio.fixture
async def lease_world(world):
    # Poisoned legacy cache is deliberately identical for both tenants. Durable
    # allocation must not trust it, even after reinitialization or eviction.
    prefix = 0x0AF00000 + ((uuid.uuid4().int % 2048) * 256)
    network = ipaddress.ip_network((prefix, 24))
    first_ip = str(next(network.hosts()))
    keys = [f"vpn:ip_pool:{org.id}" for org in (world.org_a, world.org_b)]
    for key in keys:
        await world.redis.zadd(key, {first_ip: 0})
    cipher = Fernet(Fernet.generate_key())
    builder = AWGConfigBuilder("audit-server-key", "127.0.0.1:9")
    services = []
    requests = []

    def service(db, handle=None):
        svc = VPNPoolService(db, IPPoolAllocator(world.redis, str(network)), builder,
                             cipher, "http://127.0.0.1:9")
        original_client = svc._http

        async def transport(request):
            requests.append(request)
            if handle:
                return await handle(request)
            return httpx.Response(201 if request.method == "POST" else 204)

        svc._http = httpx.AsyncClient(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(transport))
        services.append((svc, original_client))
        return svc

    try:
        yield SimpleNamespace(**locals())
    finally:
        for svc, client in services:
            await svc.close()
            await client.aclose()
        await world.redis.delete(*keys)


async def test_two_tenants_cannot_reserve_the_same_vpn_address(lease_world):
    h = lease_world
    async with h.world.sessions() as first, h.world.sessions() as second:
        a = await h.service(first).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        await first.commit()
        b = await h.service(second).assign_vpn(str(h.world.dev_b.id), h.world.org_b.id)
        await second.commit()
    assert a.assigned_ip != b.assigned_ip


async def test_router_can_observe_committed_provisioning_intent_before_post(lease_world):
    h = lease_world
    observed = []

    async def handle(request):
        async with h.world.sessions() as observer:
            peers = (await observer.scalars(select(VPNPeer).where(VPNPeer.device_id == h.world.dev_a.id))).all()
            observed.extend((peer.public_key, peer.tunnel_ip) for peer in peers)
        return httpx.Response(201)

    async with h.world.sessions() as db:
        assignment = await h.service(db, handle).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        await db.commit()
    assert observed == [(assignment.public_key, assignment.assigned_ip)], "Provider effects require a durable SQL intent"


async def test_applied_post_with_lost_response_retains_address_after_rollback(lease_world):
    h = lease_world

    async def handle(request):
        raise httpx.ReadTimeout("audit POST applied but response lost", request=request)

    async with h.world.sessions() as db:
        with pytest.raises(Exception):
            await h.service(db, handle).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        await db.rollback()
    async with h.world.sessions() as verify:
        retained = await verify.scalar(select(VPNPeer).where(VPNPeer.device_id == h.world.dev_a.id))
        assert retained is not None, "Lost response must leave a durable reservation"
        assert retained.status != VPNPeerStatus.FREE
        other = await h.service(verify).assign_vpn(str(h.world.dev_b.id), h.world.org_b.id)
        assert other.assigned_ip != retained.tunnel_ip


async def test_failed_intent_commit_prevents_router_mutation(lease_world):
    h = lease_world
    async with h.world.sessions() as db:
        with patch.object(db, "commit", AsyncMock(side_effect=ConnectionError("audit failed intent commit"))):
            with pytest.raises(ConnectionError):
                await h.service(db).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
                await db.commit()  # legacy endpoint boundary
        await db.rollback()
    assert h.requests == [], "A rejected SQL intent must never reach the router"


async def test_failed_final_commit_retains_provisioning_intent(lease_world):
    h = lease_world
    async with h.world.sessions() as db:
        async def handle(request):
            db.commit = AsyncMock(side_effect=ConnectionError("audit commit after provider failed"))
            return httpx.Response(201)

        with pytest.raises(ConnectionError):
            await h.service(db, handle).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
            await db.commit()
        await db.rollback()
    async with h.world.sessions() as verify:
        retained = await verify.scalar(select(VPNPeer).where(VPNPeer.device_id == h.world.dev_a.id))
        assert retained is not None
        assert retained.status != VPNPeerStatus.FREE
        assert len(h.requests) == 1


async def test_unknown_provisioning_rejects_retry_without_new_router_effect(lease_world):
    h = lease_world

    async def handle(request):
        raise httpx.ReadTimeout("audit unknown provisioning", request=request)

    async with h.world.sessions() as db:
        svc = h.service(db, handle)
        with pytest.raises(httpx.ReadTimeout):
            await svc.assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        for action in (svc.assign_vpn, svc.revoke_vpn):
            with pytest.raises(HTTPException) as error:
                await action(str(h.world.dev_a.id), h.world.org_a.id)
            assert error.value.status_code == 409
    assert len(h.requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "final_commit"])
async def test_revoke_retains_ip_until_delete_and_sql_commit_are_confirmed(lease_world, failure):
    h = lease_world
    async with h.world.sessions() as db:
        svc = h.service(db)
        assigned = await svc.assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        seen_intents = []

        async def handle(request):
            async with h.world.sessions() as observer:
                peer = await observer.get(VPNPeer, uuid.UUID(assigned.peer_id))
                seen_intents.append(peer.status)
            if failure == "timeout":
                raise httpx.ReadTimeout("audit unknown delete", request=request)
            db.commit = AsyncMock(side_effect=ConnectionError("audit release commit failed"))
            return httpx.Response(204)

        revoke = h.service(db, handle)
        with pytest.raises((httpx.ReadTimeout, ConnectionError)):
            await revoke.revoke_vpn(str(h.world.dev_a.id), h.world.org_a.id)
    assert seen_intents == [VPNPeerStatus.REVOKING]
    async with h.world.sessions() as verify:
        peer = await verify.get(VPNPeer, uuid.UUID(assigned.peer_id))
        assert peer.status == VPNPeerStatus.REVOKING
        other = await h.service(verify).assign_vpn(str(h.world.dev_b.id), h.world.org_b.id)
        assert other.assigned_ip != assigned.assigned_ip


async def test_confirmed_revoke_releases_address_in_postgresql(lease_world):
    h = lease_world
    async with h.world.sessions() as db:
        svc = h.service(db)
        assigned = await svc.assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        await svc.revoke_vpn(str(h.world.dev_a.id), h.world.org_a.id)
    async with h.world.sessions() as verify:
        freed = await verify.get(VPNPeer, uuid.UUID(assigned.peer_id))
        assert freed.status == VPNPeerStatus.FREE
        repeated = await h.service(verify).assign_vpn(str(h.world.dev_b.id), h.world.org_b.id)
        assert repeated.assigned_ip == assigned.assigned_ip


@pytest.mark.parametrize("cache_fault", ["evicted", "reinitialized", "unavailable"])
async def test_redis_loss_or_stale_free_list_cannot_reissue_owned_address(lease_world, cache_fault):
    h = lease_world
    async with h.world.sessions() as db:
        svc = h.service(db)
        assigned = await svc.assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        if cache_fault == "evicted":
            await h.world.redis.delete(*h.keys)
        elif cache_fault == "reinitialized":
            for key in h.keys:
                await h.world.redis.zadd(key, {assigned.assigned_ip: -1})
        else:
            svc.ip_pool.redis = AsyncMock()
            svc.ip_pool.redis.zpopmin.side_effect = ConnectionError("audit Redis down")
        other = await svc.assign_vpn(str(h.world.dev_a2.id), h.world.org_a.id)
        assert other.assigned_ip != assigned.assigned_ip


async def test_late_provider_response_cannot_complete_a_changed_generation(lease_world):
    h = lease_world
    replacement = uuid.uuid4()

    async def handle(request):
        async with h.world.sessions() as other:
            peer = await other.scalar(select(VPNPeer).where(VPNPeer.device_id == h.world.dev_a.id))
            peer.operation_id = replacement
            await other.commit()
        return httpx.Response(201)

    async with h.world.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await h.service(db, handle).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        assert error.value.status_code == 409
    async with h.world.sessions() as verify:
        peer = await verify.scalar(select(VPNPeer).where(VPNPeer.device_id == h.world.dev_a.id))
        assert peer.operation_id == replacement
        assert peer.status == VPNPeerStatus.PROVISIONING


async def test_global_unique_constraint_also_protects_unknown_peer_states(lease_world):
    h = lease_world
    async with h.world.sessions() as db:
        assigned = await h.service(db).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
    async with h.world.sessions() as db:
        db.add(VPNPeer(org_id=h.world.org_b.id, device_id=h.world.dev_b.id,
            public_key="audit-conflicting-key", private_key_enc=b"synthetic",
            tunnel_ip=assigned.assigned_ip, status=VPNPeerStatus.PROVISIONING))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_concurrent_64_assignments_have_unique_durable_addresses(lease_world):
    h = lease_world
    async with h.world.sessions() as db:
        devices = [Device(org_id=h.world.org_a.id if i % 2 else h.world.org_b.id,
                          name=f"audit-vpn-concurrent-{i}") for i in range(64)]
        db.add_all(devices)
        await db.commit()

    async def assign(device):
        async with h.world.sessions() as db:
            return await h.service(db).assign_vpn(str(device.id), device.org_id)

    assignments = await asyncio.wait_for(asyncio.gather(*(assign(device) for device in devices)), 45)
    assert len({assignment.assigned_ip for assignment in assignments}) == 64
    assert len({assignment.peer_id for assignment in assignments}) == 64
    assert len(h.requests) == 64
    assert len({json.loads(request.content)["allowed_ip"] for request in h.requests}) == 64


async def test_assignment_retry_preserves_persisted_route_selection(lease_world):
    h = lease_world
    async with h.world.sessions() as db:
        svc = h.service(db)
        first = await svc.assign_vpn(str(h.world.dev_a.id), h.world.org_a.id, split_tunnel=False)
        again = await svc.assign_vpn(str(h.world.dev_a.id), h.world.org_a.id, split_tunnel=True)
        assert first.config == again.config
    assert len(h.requests) == 1


async def test_cancellation_after_post_started_does_not_erase_durable_intent(lease_world):
    h = lease_world
    entered = asyncio.Event()

    async def handle(request):
        entered.set()
        await asyncio.Event().wait()

    async with h.world.sessions() as db:
        task = asyncio.create_task(h.service(db, handle).assign_vpn(str(h.world.dev_a.id), h.world.org_a.id))
        try:
            await asyncio.wait_for(entered.wait(), 3)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with h.world.sessions() as verify:
        peer = await verify.scalar(select(VPNPeer).where(VPNPeer.device_id == h.world.dev_a.id))
        assert peer.status == VPNPeerStatus.PROVISIONING
        assert peer.operation_id is not None
    assert len(h.requests) == 1


async def test_exhausted_single_address_pool_rejects_new_peer_without_post(lease_world):
    h = lease_world
    async with h.world.sessions() as db:
        svc = h.service(db)
        svc.ip_pool.network = ipaddress.ip_network(h.first_ip + "/32")
        await svc.assign_vpn(str(h.world.dev_a.id), h.world.org_a.id)
        with pytest.raises(HTTPException) as error:
            await svc.assign_vpn(str(h.world.dev_b.id), h.world.org_b.id)
        assert error.value.status_code == 503
    assert len(h.requests) == 1


async def test_lifecycle_di_commit_does_not_commit_http_callers_pending_writes(lease_world):
    h = lease_world
    from contextlib import asynccontextmanager

    from backend.api.v1.vpn.router import get_pool_service

    @asynccontextmanager
    async def owned_session():
        async with h.world.sessions() as db:
            yield db

    async with h.world.sessions() as caller:
        device = await caller.get(Device, h.world.dev_a.id)
        original_name = device.name
        device.name = "audit-uncommitted-caller-change"
        with (
            patch("backend.api.v1.vpn.router.get_db_session", owned_session),
            patch.object(VPNPoolService, "_add_peer_to_server", AsyncMock()),
        ):
            factory = get_pool_service(
                ip_pool=IPPoolAllocator(h.world.redis, str(h.network)), builder=h.builder, cipher=h.cipher,
            )
            service = await anext(factory)
            try:
                await service.assign_vpn(str(device.id), h.world.org_a.id)
            finally:
                await factory.aclose()
        async with h.world.sessions() as verify:
            unchanged = await verify.get(Device, h.world.dev_a.id)
            assert unchanged.name == original_name
            assert await verify.scalar(select(VPNPeer.id).where(VPNPeer.device_id == device.id)) is not None
        await caller.rollback()
