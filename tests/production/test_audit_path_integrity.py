"""An HTTP Host header must not select the audit skip path or resource."""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from backend.models.audit_log import AuditLog
from backend.models.device import Device


@pytest.mark.parametrize("host", [
    "audit.local",
    "audit.local/metrics?ignored=",
    "audit.local/api/v1/auth/refresh?ignored=",
    "audit.local/api/v1/tasks/11111111-1111-4111-8111-111111111111?ignored=",
])
async def test_host_cannot_hide_or_relabel_an_authenticated_mutation(world, host):
    path = f"/api/v1/devices/{world.dev_a.id}"
    with (
        patch("backend.middleware.metrics.http_requests_total") as counter,
        patch("backend.middleware.request_id.structlog.contextvars.bind_contextvars") as context,
    ):
        response = await world.client.put(path,
            headers={**world.auth(world.users["org_admin"]), "Host": host},
            json={"name": "audit-updated-device"})
    assert response.status_code == 200, response.text
    async with world.sessions() as db:
        assert (await db.get(Device, world.dev_a.id)).name == "audit-updated-device"
        rows = list((await db.scalars(select(AuditLog).where(AuditLog.org_id == world.org_a.id))).all())
    assert len(rows) == 1, "Mutation committed without its audit entry"
    row = rows[0]
    assert row.action == "put.devices"
    assert row.resource_type == "devices"
    assert row.resource_id == str(world.dev_a.id)
    assert row.user_id == world.users["org_admin"].id
    assert row.meta["http_status"] == 200
    counter.labels.assert_called_once_with(method="PUT", endpoint="/api/v1/devices/{id}", status_code="200")
    assert context.call_args.kwargs["path"] == path
