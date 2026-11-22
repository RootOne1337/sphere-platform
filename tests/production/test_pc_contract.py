"""Security policy regressions using real local PostgreSQL, Redis and JWT authentication."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _sockets import FakeSocket


@pytest.mark.asyncio
async def test_F03_pc_agent_accepts_identifier_from_another_org(world):
    w = world
    response = await w.client.post(
        "/api/v1/auth/api-keys",
        headers=w.auth(w.users["org_owner"]),
        json={"name": "audit-agent", "key_type": "agent", "permissions": ["device:register"]},
    )
    assert response.status_code == 201
    router = importlib.import_module("backend.api.ws.agent.router")
    manager = SimpleNamespace(connect=AsyncMock(return_value="session"), disconnect=AsyncMock())
    ws = FakeSocket([{"token": response.json()["raw_key"]}])
    with (
        patch.object(router, "get_connection_manager", return_value=manager),
        patch.object(router, "AsyncSessionLocal", w.sessions),
    ):
        await router.pc_agent_ws(ws, str(w.dev_b.id))
    manager.connect.assert_not_awaited()
    assert ws.closed


@pytest.mark.asyncio
async def test_pc_registration_updates_existing_workstation(world):
    from backend.models.ldplayer_instance import LDPlayerInstance
    from backend.models.workstation import Workstation

    w = world
    router = importlib.import_module("backend.api.ws.agent.router")
    async with w.sessions() as db:
        workstation = Workstation(org_id=w.org_a.id, name="audit-workstation")
        db.add(workstation)
        await db.flush()
        instance = LDPlayerInstance(
            org_id=w.org_a.id, workstation_id=workstation.id, instance_index=0
        )
        db.add(instance)
        await db.commit()
        with patch.object(router, "get_redis", AsyncMock(return_value=w.redis)):
            await router.handle_workstation_register(
                str(workstation.id),
                {
                    "hostname": "audit-host",
                    "os_version": "test",
                    "ip_address": "127.0.0.1",
                    "agent_version": "audit",
                    "instances": [
                        {
                            "index": 0,
                            "name": "audit-instance",
                            "adb_port": 5555,
                            "android_serial": "local-only",
                        }
                    ],
                },
                str(w.org_a.id),
                db,
            )
        await db.refresh(workstation)
        await db.refresh(instance)
        assert workstation.hostname == "audit-host"
        assert workstation.agent_version == "audit"
        assert instance.android_serial == "local-only"
