"""Cross-request clone identity migration against isolated PostgreSQL."""

import asyncio
import hashlib
import secrets

import pytest

from backend.models.api_key import APIKey


@pytest.mark.asyncio
async def test_concurrent_v2_clone_registration_is_serialized_and_idempotent(world):
    raw_key = "sphr_audit_" + secrets.token_urlsafe(32)
    async with world.sessions() as db:
        db.add(APIKey(
            org_id=world.org_a.id,
            name="clone migration regression",
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            key_prefix="sphr_audit",
            type="agent",
            permissions=["device:register"],
            is_active=True,
        ))
        await db.commit()

    headers = {"X-API-Key": raw_key}
    fingerprint = "audit-clone-template-" + secrets.token_hex(8)
    template = {"fingerprint": fingerprint, "name": "audit seed"}
    legacy = await world.client.post("/api/v1/devices/register", headers=headers, json=template)
    assert legacy.status_code == 201, legacy.status_code
    base_device_id = legacy.json()["device_id"]

    old_binding = hashlib.sha256(b"legacy nic binding").hexdigest()
    old = await world.client.post("/api/v1/devices/register", headers=headers,
                                  json={**template, "instance_binding": old_binding})
    assert old.status_code == 201
    assert old.json()["device_id"] == base_device_id

    bindings = [hashlib.sha256(f"vm-serial-{index}+same-nic".encode()).hexdigest()
                for index in range(32)]

    async def register(binding: str):
        return await world.client.post(
            "/api/v1/devices/register",
            headers=headers,
            json={**template, "instance_binding": binding, "instance_binding_version": 2},
        )

    first = await asyncio.gather(*(register(binding) for binding in bindings))
    assert all(response.status_code == 201 for response in first), [response.status_code for response in first]
    first_ids = [response.json()["device_id"] for response in first]
    assert len(set(first_ids)) == len(bindings)
    assert base_device_id in first_ids

    retries = await asyncio.gather(*(register(binding) for binding in bindings))
    assert all(response.status_code == 201 for response in retries)
    assert [response.json()["device_id"] for response in retries] == first_ids
    assert all(response.json()["instance_binding_version"] == 2 for response in retries)

    stale = await world.client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={**template, "instance_binding": old_binding, "instance_binding_version": 1},
    )
    assert stale.status_code == 409
