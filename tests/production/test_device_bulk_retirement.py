"""Device removal must preserve PostgreSQL task history."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select


async def test_bulk_delete_retires_devices_with_task_history(world):
    """A linked task must not make the entire selected-device batch fail."""
    from backend.models.device import Device
    from backend.models.task import Task, TaskStatus

    raw_refresh_token = secrets.token_urlsafe(32)
    async with world.sessions() as db:
        device = await db.get(Device, world.dev_a.id)
        device.refresh_token_hash = hashlib.sha256(raw_refresh_token.encode()).hexdigest()
        device.refresh_token_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        db.add(Task(
            org_id=world.org_a.id,
            device_id=world.dev_a.id,
            script_id=world.script.id,
            status=TaskStatus.COMPLETED,
        ))
        await db.commit()

    headers = world.auth(world.users["org_admin"])
    response = await world.client.request(
        "DELETE",
        "/api/v1/devices/bulk",
        headers=headers,
        json={"device_ids": [str(world.dev_a.id), str(world.dev_a2.id)]},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 2}

    async with world.sessions() as db:
        retired = await db.get(Device, world.dev_a.id)
        retained_task = await db.scalar(
            select(Task).where(Task.device_id == world.dev_a.id)
        )
        assert retired is not None and retired.is_active is False
        assert retired.refresh_token_hash is None
        assert retired.refresh_previous_token_hash is None
        assert retained_task is not None

    inventory = await world.client.get(
        "/api/v1/devices?per_page=5000", headers=headers
    )
    assert inventory.status_code == 200, inventory.text
    visible_ids = {item["id"] for item in inventory.json()["items"]}
    assert str(world.dev_a.id) not in visible_ids
    assert str(world.dev_a2.id) not in visible_ids

    refresh = await world.client.post(
        "/api/v1/devices/refresh",
        headers={"Cookie": "refresh_token=" + raw_refresh_token},
    )
    assert refresh.status_code == 401

    repeated = await world.client.request(
        "DELETE",
        "/api/v1/devices/bulk",
        headers=headers,
        json={"device_ids": [str(world.dev_a.id), str(world.dev_a2.id)]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {"deleted": 0}


async def test_single_delete_retires_device_with_task_history(world):
    """The single-device endpoint follows the same FK-safe retirement path."""
    from backend.models.device import Device
    from backend.models.task import Task, TaskStatus

    async with world.sessions() as db:
        db.add(Task(
            org_id=world.org_a.id,
            device_id=world.dev_a.id,
            script_id=world.script.id,
            status=TaskStatus.COMPLETED,
        ))
        await db.commit()

    response = await world.client.delete(
        f"/api/v1/devices/{world.dev_a.id}",
        headers=world.auth(world.users["org_admin"]),
    )
    assert response.status_code == 204, response.text

    async with world.sessions() as db:
        retired = await db.get(Device, world.dev_a.id)
        retained_task = await db.scalar(
            select(Task).where(Task.device_id == world.dev_a.id)
        )
        assert retired is not None and retired.is_active is False
        assert retained_task is not None
