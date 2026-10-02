"""F32: explicit targets and honest VPN outcomes; no live Android/router commands."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.v1.vpn.router import (
    get_key_cipher_factory,
    get_killswitch_service,
    get_pool_service,
)
from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.main import app
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.killswitch_service import KillSwitchService


async def request(world, path, body, role="org_admin"):
    return await world.client.post("/api/v1/vpn/" + path, json=body,
                                   headers=world.auth(world.users[role]))


def pool(world, *, assignments=None):
    service = SimpleNamespace(revoke_vpn=AsyncMock(), assign_vpn=AsyncMock(
        side_effect=assignments or [SimpleNamespace(assigned_ip="10.200.0.10")]))
    app.dependency_overrides[get_pool_service] = lambda: service
    return service


def killswitch(world, outcomes=None):
    publisher = SimpleNamespace(supports_killswitch=True,
        send_command_to_device=AsyncMock(side_effect=outcomes or [True]))
    service = KillSwitchService(publisher)
    app.dependency_overrides[get_killswitch_service] = lambda: service
    return publisher


async def peers(world):
    async with world.sessions() as db:
        for index, device in enumerate([world.dev_a, world.dev_a2]):
            db.add(VPNPeer(org_id=world.org_a.id, device_id=device.id,
                           public_key=f"f32-{world.suffix}-{index}", private_key_enc=b"unused",
                           tunnel_ip=f"10.200.0.{index + 20}", status=VPNPeerStatus.ASSIGNED))
        await db.commit()


@pytest.mark.parametrize("body", [
    {"device_ids": [], "action": "disable"},
    {"device_ids": ["invalid"], "action": "enable"},
    {"device_ids": [str(uuid.uuid4())], "enabled": False},
    {"device_ids": [str(uuid.uuid4())]},
    {"device_ids": [str(uuid.uuid4())], "action": "suspend"},
    {"device_ids": [str(uuid.uuid4())], "action": "enable", "method": "shell"},
])
async def test_invalid_killswitch_contract_never_dispatches(world, body):
    publisher = killswitch(world)
    response = await request(world, "killswitch", body)
    assert response.status_code == 422
    publisher.send_command_to_device.assert_not_awaited()


@pytest.mark.parametrize("endpoint", ["rotate", "killswitch"])
async def test_duplicates_and_empty_targets_are_not_global_operations(world, endpoint):
    service = pool(world)
    publisher = killswitch(world)
    for targets in [[], [str(world.dev_a.id)] * 2]:
        body = {"device_ids": targets}
        if endpoint == "killswitch":
            body["action"] = "enable"
        response = await request(world, endpoint, body)
        assert response.status_code == 422
    service.revoke_vpn.assert_not_awaited()
    publisher.send_command_to_device.assert_not_awaited()


@pytest.mark.parametrize("endpoint", ["rotate", "killswitch"])
async def test_foreign_target_rejects_whole_selection_before_any_side_effect(world, endpoint):
    service = pool(world)
    publisher = killswitch(world)
    body = {"device_ids": [str(world.dev_a.id), str(world.dev_b.id)]}
    if endpoint == "killswitch":
        body["action"] = "disable"
    response = await request(world, endpoint, body)
    assert response.status_code == 404 and response.json()["detail"] == "Device not found"
    service.revoke_vpn.assert_not_awaited()
    publisher.send_command_to_device.assert_not_awaited()


async def test_real_unwired_killswitch_is_reported_as_unsupported(world):
    response = await request(world, "killswitch", {"device_ids": [str(world.dev_a.id)], "action": "disable"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] == 0 and body["execution_confirmed"] is False
    assert body["outcomes"] == {str(world.dev_a.id): "unsupported"}
    assert body["results"] == {str(world.dev_a.id): False}


async def test_disable_and_partial_dispatch_are_explicit_and_not_execution(world):
    publisher = killswitch(world, [True, RuntimeError("private transport credentials")])
    response = await request(world, "killswitch", {
        "device_ids": [str(world.dev_a.id), str(world.dev_a2.id)], "action": "disable"})
    assert response.status_code == 200
    body = response.json()
    assert body["outcomes"] == {str(world.dev_a.id): "submitted", str(world.dev_a2.id): "unknown"}
    assert body["execution_confirmed"] is False and body["success"] == 1
    assert publisher.send_command_to_device.await_count == 2
    assert all(call.args[1]["action"] == "disable" for call in publisher.send_command_to_device.await_args_list)
    assert "private transport credentials" not in response.text


async def test_false_dispatch_is_not_sent(world):
    killswitch(world, [False])
    response = await request(world, "killswitch", {"device_ids": [str(world.dev_a.id)], "action": "enable"})
    assert response.json()["outcomes"][str(world.dev_a.id)] == "not_sent"


async def test_rotate_missing_assigned_peer_does_not_create_one(world):
    service = pool(world)
    response = await request(world, "rotate", {"device_ids": [str(world.dev_a.id)]})
    assert response.status_code == 200
    assert response.json()["details"][0]["outcome"] == "rejected"
    service.revoke_vpn.assert_not_awaited()
    service.assign_vpn.assert_not_awaited()


async def test_partial_rotation_retains_evidence_and_continues_without_replaying(world):
    await peers(world)
    service = pool(world, assignments=[RuntimeError("private router token"), SimpleNamespace(assigned_ip="10.200.0.10")])
    response = await request(world, "rotate", {"device_ids": [str(world.dev_a.id), str(world.dev_a2.id)]})
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["success"], body["failed"]) == (2, 1, 1)
    first, second = body["details"]
    assert first["outcome"] == "unknown" and first["revoke_confirmed"] is True
    assert first["old_ip"] == "10.200.0.20" and first["new_ip"] is None
    assert second["outcome"] == "configured" and second["new_ip"] == "10.200.0.10"
    assert body["execution_confirmed"] is False
    assert service.revoke_vpn.await_count == service.assign_vpn.await_count == 2
    assert "private router token" not in response.text


@pytest.mark.parametrize("endpoint", ["rotate", "killswitch"])
async def test_viewer_cannot_change_vpn(world, endpoint):
    service = pool(world)
    publisher = killswitch(world)
    body = {"device_ids": [str(world.dev_a.id)]}
    if endpoint == "killswitch":
        body["action"] = "enable"
    response = await request(world, endpoint, body, role="viewer")
    assert response.status_code == 403
    service.revoke_vpn.assert_not_awaited()
    publisher.send_command_to_device.assert_not_awaited()


async def test_ownership_preflight_with_actual_non_owner_rls_role(world, runtime_db):
    async def scoped_db():
        async with runtime_db.sessions() as db:
            await bind_tenant_context(db, str(world.org_a.id))
            yield db
    app.dependency_overrides[get_db] = scoped_db
    publisher = killswitch(world)
    response = await request(world, "killswitch", {
        "device_ids": [str(world.dev_a.id), str(world.dev_b.id)], "action": "enable"})
    assert response.status_code == 404
    publisher.send_command_to_device.assert_not_awaited()


@pytest.mark.parametrize("body,expected", [({"device_ids": []}, 422), ({"device_ids": ["invalid"]}, 422)])
async def test_missing_provider_credentials_do_not_mask_request_validation(world, body, expected):
    from fastapi import HTTPException

    calls = []

    def unavailable():
        calls.append(True)
        raise HTTPException(503, "Provider not configured")

    app.dependency_overrides[get_key_cipher_factory] = lambda: unavailable
    response = await request(world, "rotate", body)
    assert response.status_code == expected
    assert not calls


async def test_provider_credentials_are_not_loaded_for_foreign_rotation(world):
    from fastapi import HTTPException

    calls = []

    def unavailable():
        calls.append(True)
        raise HTTPException(503, "Provider not configured")

    app.dependency_overrides[get_key_cipher_factory] = lambda: unavailable
    response = await request(world, "rotate", {"device_ids": [str(world.dev_b.id)]})
    assert response.status_code == 404
    assert not calls
