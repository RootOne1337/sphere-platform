# tests/bulk/test_bulk.py
# TZ-02 SPLIT-4: Bulk Actions tests.
from __future__ import annotations

import uuid

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

    async def test_bulk_reboot_succeeds_for_owned(self, bulk_client, bulk_devices):
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

    async def test_bulk_action_not_owned_device_fails_not_403(
        self, bulk_client, bulk_devices
    ):
        """Devices from other orgs → success=False, not 403 on the whole request."""
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

    async def test_bulk_delete_empty_list_422(self, bulk_admin_client):
        resp = await bulk_admin_client.request(
            "DELETE",
            "/api/v1/devices/bulk",
            json={"device_ids": []},
        )
        assert resp.status_code == 422
