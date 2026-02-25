# tests/groups/test_groups.py
# TZ-02 SPLIT-2: Device Groups & Tags tests.
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas.groups import (
    CreateGroupRequest,
    SetTagsRequest,
)


class TestGroupSchemaValidation:
    """Unit tests: schema-level validation without DB."""

    def test_valid_group_created(self):
        g = CreateGroupRequest(name="Farm A", color="#FF5733")
        assert g.name == "Farm A"
        assert g.color == "#FF5733"

    def test_invalid_color_rejected(self):
        with pytest.raises(ValidationError):
            CreateGroupRequest(name="X", color="red")  # must be #RRGGBB

    def test_color_none_accepted(self):
        g = CreateGroupRequest(name="No Color")
        assert g.color is None

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            CreateGroupRequest(name="x" * 256)

    def test_blank_name_rejected(self):
        with pytest.raises(ValidationError):
            CreateGroupRequest(name="   ")

    def test_tags_normalized(self):
        req = SetTagsRequest(tags=["Farm!", "test  ", "ABC"])
        # re.sub(r'[^\w-]', '', t.lower().strip())
        assert "farm" in req.tags
        assert "test" in req.tags
        assert "abc" in req.tags

    def test_tags_max_20(self):
        with pytest.raises(ValidationError):
            SetTagsRequest(tags=[f"tag{i}" for i in range(21)])

    def test_tags_empty_strings_filtered(self):
        req = SetTagsRequest(tags=["  ", "!!", "real"])
        assert req.tags == ["real"]


class TestGroupCRUD:
    """Integration tests: Groups CRUD via HTTP."""

    async def test_list_groups_empty(self, dm_client):
        resp = await dm_client.get("/api/v1/groups")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_group_success(self, dm_client):
        resp = await dm_client.post(
            "/api/v1/groups",
            json={"name": "Farm A", "color": "#FF5733", "description": "Main farm"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Farm A"
        assert data["color"] == "#FF5733"
        assert data["total_devices"] == 0

    async def test_create_group_duplicate_name_409(self, dm_client, sample_group):
        resp = await dm_client.post(
            "/api/v1/groups",
            json={"name": sample_group.name},
        )
        assert resp.status_code == 409

    async def test_update_group_name(self, dm_client, sample_group):
        resp = await dm_client.put(
            f"/api/v1/groups/{sample_group.id}",
            json={"name": "Farm B"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Farm B"

    async def test_update_group_invalid_color_422(self, dm_client, sample_group):
        resp = await dm_client.put(
            f"/api/v1/groups/{sample_group.id}",
            json={"color": "notacolor"},
        )
        assert resp.status_code == 422

    async def test_delete_group_admin_only(self, dm_client, admin_client, sample_group):
        # device_manager cannot delete
        resp = await dm_client.delete(f"/api/v1/groups/{sample_group.id}")
        assert resp.status_code == 403

        # org_admin can delete
        resp = await admin_client.delete(f"/api/v1/groups/{sample_group.id}")
        assert resp.status_code == 204

    async def test_viewer_can_list_groups(self, viewer_client):
        resp = await viewer_client.get("/api/v1/groups")
        assert resp.status_code == 200

    async def test_viewer_cannot_create_group(self, viewer_client):
        resp = await viewer_client.post("/api/v1/groups", json={"name": "X"})
        assert resp.status_code == 403

    async def test_list_groups_with_stats(self, dm_client, sample_group, group_device, db_session):
        # Add device to group via the DB directly
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.models.device import Device

        stmt = select(Device).options(selectinload(Device.groups)).where(Device.id == group_device.id)
        device = (await db_session.execute(stmt)).scalar_one()
        device.groups = [sample_group]
        await db_session.flush()

        resp = await dm_client.get("/api/v1/groups")
        assert resp.status_code == 200
        groups = resp.json()
        found = next((g for g in groups if g["id"] == str(sample_group.id)), None)
        assert found is not None
        assert found["total_devices"] == 1

    async def test_create_group_with_parent(self, dm_client, sample_group):
        resp = await dm_client.post(
            "/api/v1/groups",
            json={"name": "Sub-Farm", "parent_group_id": str(sample_group.id)},
        )
        assert resp.status_code == 201
        assert resp.json()["parent_group_id"] == str(sample_group.id)

    async def test_self_parent_rejected(self, dm_client, sample_group):
        resp = await dm_client.put(
            f"/api/v1/groups/{sample_group.id}",
            json={"parent_group_id": str(sample_group.id)},
        )
        assert resp.status_code == 400


class TestMoveDevices:
    """Tests for moving devices between groups."""

    async def test_move_device_to_group(
        self, dm_client, sample_group, group_device, db_session
    ):
        resp = await dm_client.post(
            f"/api/v1/groups/{sample_group.id}/devices/move",
            json={"device_ids": [str(group_device.id)]},
        )
        assert resp.status_code == 200
        assert resp.json()["moved"] == 1

    async def test_move_nonexistent_device_skipped(self, dm_client, sample_group):
        import uuid
        resp = await dm_client.post(
            f"/api/v1/groups/{sample_group.id}/devices/move",
            json={"device_ids": [str(uuid.uuid4())]},
        )
        assert resp.status_code == 200
        assert resp.json()["moved"] == 0


class TestTags:
    """Tests for tag management."""

    async def test_list_tags_empty(self, dm_client):
        resp = await dm_client.get("/api/v1/groups/tags")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_tags_returns_device_tags(
        self, dm_client, group_device, db_session
    ):
        # group_device has tags=["farm", "test"]
        resp = await dm_client.get("/api/v1/groups/tags")
        assert resp.status_code == 200
        tags = resp.json()
        assert "farm" in tags
        assert "test" in tags
        assert tags == sorted(tags)  # must be sorted

    async def test_set_device_tags(self, dm_client, group_device):
        resp = await dm_client.put(
            f"/api/v1/groups/devices/{group_device.id}/tags",
            json={"tags": ["new-tag", "another"]},
        )
        assert resp.status_code == 204

    async def test_set_device_tags_normalizes(self, dm_client, group_device):
        resp = await dm_client.put(
            f"/api/v1/groups/devices/{group_device.id}/tags",
            json={"tags": ["Tag With Spaces!", "UPPER"]},
        )
        assert resp.status_code == 204

    async def test_set_device_tags_too_many_422(self, dm_client, group_device):
        resp = await dm_client.put(
            f"/api/v1/groups/devices/{group_device.id}/tags",
            json={"tags": [f"tag{i}" for i in range(21)]},
        )
        assert resp.status_code == 422

    async def test_set_tags_unknown_device_404(self, dm_client):
        import uuid
        resp = await dm_client.put(
            f"/api/v1/groups/devices/{uuid.uuid4()}/tags",
            json={"tags": ["ok"]},
        )
        assert resp.status_code == 404
