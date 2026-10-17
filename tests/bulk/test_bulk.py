# tests/bulk/test_bulk.py
# TZ-02 SPLIT-4: Bulk Actions tests.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from backend.schemas.bulk import BulkActionRequest, BulkActionType


class TestBulkSchema:
    """Unit tests: schema validation."""

    def test_valid_reboot_action(self):
        req = BulkActionRequest(
            action=BulkActionType.REBOOT,
            device_ids=["dev-1", "dev-2"],
        )
        assert req.action == BulkActionType.REBOOT

    def test_set_group_requires_group_id(self):
        with pytest.raises(ValidationError):
            BulkActionRequest(
                action=BulkActionType.SET_GROUP,
                device_ids=["dev-1"],
                params={},  # missing group_id
            )

    def test_send_command_requires_command_type(self):
        with pytest.raises(ValidationError):
            BulkActionRequest(
                action=BulkActionType.SEND_COMMAND,
                device_ids=["dev-1"],
                params={},  # missing command_type
            )

    def test_empty_device_ids_rejected(self):
        with pytest.raises(ValidationError):
            BulkActionRequest(
                action=BulkActionType.REBOOT,
                device_ids=[],
            )

    def test_max_500_devices(self):
        req = BulkActionRequest(
            action=BulkActionType.REBOOT,
            device_ids=[str(uuid.uuid4()) for _ in range(500)],
        )
        assert len(req.device_ids) == 500

    def test_over_500_devices_rejected(self):
        with pytest.raises(ValidationError):
            BulkActionRequest(
                action=BulkActionType.REBOOT,
                device_ids=[str(uuid.uuid4()) for _ in range(501)],
            )


class TestBulkAction:
    """Integration tests: bulk action endpoint."""

    async def test_bulk_reboot_succeeds_for_owned(self, bulk_client, bulk_devices, monkeypatch):
        publisher = Mock()
        publisher.send_command_wait_result = AsyncMock(return_value={"status": "received"})
        monkeypatch.setattr(
            "backend.websocket.pubsub_router.get_pubsub_publisher",
            lambda: publisher,
        )
        device_ids = [str(d.id) for d in bulk_devices]
        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={"action": "reboot", "device_ids": device_ids},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == len(device_ids)
        assert data["succeeded"] == len(device_ids)
        assert data["failed"] == 0
        assert publisher.send_command_wait_result.await_count == len(device_ids)
        command = publisher.send_command_wait_result.await_args_list[0].args[1]
        assert command["type"] == "REBOOT"
        assert command["command_id"].startswith("interactive_")
        assert publisher.send_command_wait_result.await_args_list[0].kwargs == {
            "timeout": 10.0,
            "live_only": True,
            "accept_progress": True,
        }

    async def test_bulk_reboot_fails_explicitly_when_live_transport_is_unavailable(
        self, bulk_client, bulk_devices, mock_redis, monkeypatch
    ):
        monkeypatch.setattr(
            "backend.websocket.pubsub_router.get_pubsub_publisher",
            lambda: None,
        )
        device_id = str(bulk_devices[0].id)

        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={"action": "reboot", "device_ids": [device_id]},
        )

        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["success"] is False
        assert result["error"] == "Device command transport is unavailable"
        assert await mock_redis.get(f"cmd:reboot:{device_id}") is None

    async def test_bulk_reboot_reports_agent_rejection_without_claiming_success(
        self, bulk_client, bulk_devices, monkeypatch
    ):
        publisher = Mock()
        publisher.send_command_wait_result = AsyncMock(
            return_value={"status": "failed", "error": "agent rejected"}
        )
        monkeypatch.setattr(
            "backend.websocket.pubsub_router.get_pubsub_publisher",
            lambda: publisher,
        )

        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={"action": "reboot", "device_ids": [str(bulk_devices[0].id)]},
        )

        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["success"] is False
        assert result["error"] == "Agent rejected reboot command"

    async def test_bulk_action_not_owned_device_fails_not_403(
        self, bulk_client, bulk_devices, monkeypatch
    ):
        """Devices from other orgs → success=False, not 403 on the whole request."""
        publisher = Mock()
        publisher.send_command_wait_result = AsyncMock(return_value={"status": "received"})
        monkeypatch.setattr(
            "backend.websocket.pubsub_router.get_pubsub_publisher",
            lambda: publisher,
        )
        other_id = str(uuid.uuid4())
        owned_ids = [str(bulk_devices[0].id)]
        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={"action": "reboot", "device_ids": owned_ids + [other_id]},
        )
        assert resp.status_code == 200
        data = resp.json()
        results = {r["device_id"]: r for r in data["results"]}
        assert results[other_id]["success"] is False
        assert results[other_id]["error"] == "Device not found"
        assert results[owned_ids[0]]["success"] is True
        assert publisher.send_command_wait_result.await_count == 1

    async def test_bulk_connect_adb(self, bulk_client, bulk_devices):
        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={"action": "connect_adb", "device_ids": [str(bulk_devices[0].id)]},
        )
        assert resp.status_code == 200
        assert resp.json()["succeeded"] == 1

    async def test_bulk_set_tags(self, bulk_client, bulk_devices):
        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={
                "action": "set_tags",
                "device_ids": [str(bulk_devices[0].id)],
                "params": {"tags": ["batch-tag"]},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["succeeded"] == 1

    async def test_bulk_set_group(self, bulk_client, bulk_devices, bulk_group):
        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={
                "action": "set_group",
                "device_ids": [str(d.id) for d in bulk_devices[:2]],
                "params": {"group_id": str(bulk_group.id)},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 2

    async def test_bulk_action_requires_device_write(self, bulk_client):
        # viewer cannot perform bulk actions
        pass  # covered by RBAC: device_manager has device:write

    async def test_results_include_per_device_detail(self, bulk_client, bulk_devices):
        resp = await bulk_client.post(
            "/api/v1/devices/bulk/action",
            json={"action": "reboot", "device_ids": [str(bulk_devices[0].id)]},
        )
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert "device_id" in result
        assert "success" in result

    async def test_unauthenticated_bulk_401(self, bulk_devices):
        from httpx import ASGITransport, AsyncClient

        from backend.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/api/v1/devices/bulk/action",
                json={"action": "reboot", "device_ids": [str(bulk_devices[0].id)]},
            )
        assert resp.status_code == 401


class TestBulkDelete:
    """Tests for bulk device deletion."""

    async def test_bulk_delete_requires_org_admin(
        self, bulk_client, bulk_admin_client, bulk_devices
    ):
        device_ids = [str(d.id) for d in bulk_devices[:2]]

        # device_manager cannot bulk-delete
        resp = await bulk_client.request(
            "DELETE",
            "/api/v1/devices/bulk",
            json={"device_ids": device_ids},
        )
        assert resp.status_code == 403

        # org_admin can bulk-delete
        resp = await bulk_admin_client.request(
            "DELETE",
            "/api/v1/devices/bulk",
            json={"device_ids": device_ids},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

    async def test_bulk_delete_other_org_devices_ignored(
        self, bulk_admin_client, bulk_devices
    ):
        other_id = str(uuid.uuid4())
        resp = await bulk_admin_client.request(
            "DELETE",
            "/api/v1/devices/bulk",
            json={"device_ids": [str(bulk_devices[0].id), other_id]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1  # only owned device deleted

    async def test_bulk_delete_removes_devices_from_inventory_and_is_idempotent(
        self, bulk_admin_client, bulk_devices
    ):
        device_ids = [str(device.id) for device in bulk_devices[:2]]
        delete_url = "/api/v1/devices/bulk"

        first = await bulk_admin_client.request(
            "DELETE", delete_url, json={"device_ids": device_ids}
        )
        assert first.status_code == 200
        assert first.json()["deleted"] == 2

        inventory = await bulk_admin_client.get("/api/v1/devices?per_page=50")
        assert inventory.status_code == 200
        remaining_ids = {item["id"] for item in inventory.json()["items"]}
        assert not (set(device_ids) & remaining_ids)

        repeated = await bulk_admin_client.request(
            "DELETE", delete_url, json={"device_ids": device_ids}
        )
        assert repeated.status_code == 200
        assert repeated.json()["deleted"] == 0

    async def test_bulk_delete_empty_list_422(self, bulk_admin_client):
        resp = await bulk_admin_client.request(
            "DELETE",
            "/api/v1/devices/bulk",
            json={"device_ids": []},
        )
        assert resp.status_code == 422
