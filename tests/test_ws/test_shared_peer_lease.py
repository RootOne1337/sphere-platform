from __future__ import annotations

import asyncio

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from backend.websocket.shared_peer_lease import MAX_DEVICE_PEERS, SharedPeerLease


@pytest.mark.asyncio
async def test_two_workers_atomically_admit_ten_and_exact_release_keeps_other_peers():
    server = FakeServer()
    clients = [FakeRedis(server=server, decode_responses=True) for _ in range(2)]
    stores = [SharedPeerLease(client, "shared-test") for client in clients]
    bindings = [dict(device="device", session=f"{i:032x}") for i in range(20)]
    try:
        results = await asyncio.gather(*[stores[i % 2].acquire(b, str(i)) for i, b in enumerate(bindings)])
        admitted = [i for i, result in enumerate(results) if result]
        assert len(admitted) == MAX_DEVICE_PEERS == 10
        assert await clients[0].zcard(stores[0].index("device")) == 10
        i, j = admitted[:2]
        assert not await stores[1].release(bindings[i], "foreign")
        assert await stores[1].release(bindings[i], str(i))
        assert await clients[0].get(stores[0].key("device", bindings[j]["session"])) == str(j)
        assert await clients[0].zcard(stores[0].index("device")) == 9
        assert await stores[0].acquire(bindings[-1], "replacement")
        assert not await stores[0].renew(bindings[i], str(i))
        assert await stores[0].renew(bindings[j], str(j))
        assert not await stores[0].renew(bindings[j], "different-identity")
    finally:
        for client in clients:
            await client.aclose()


@pytest.mark.asyncio
async def test_expired_index_entry_frees_capacity_but_stale_identity_cannot_borrow_new_lease():
    client = FakeRedis(decode_responses=True)
    store = SharedPeerLease(client, "shared-test")
    try:
        bindings = [dict(device="device", session=f"{i:032x}") for i in range(11)]
        for i, binding in enumerate(bindings[:-1]):
            assert await store.acquire(binding, str(i))
        first = bindings[0]
        await client.delete(store.key("device", first["session"]))
        await client.zadd(store.index("device"), {first["session"]: 0})
        assert await store.acquire(bindings[-1], "new")
        assert not await store.renew(first, "0")
        assert not await store.release(first, "0")
        assert await client.zcard(store.index("device")) == 10
        assert store.key("device", first["session"]).split('{')[1].split('}')[0] == "device"
        assert '{device}' in store.index("device")
    finally:
        await client.aclose()
