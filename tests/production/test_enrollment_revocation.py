"""Enrollment must respect a key change committed while authentication waits."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from test_device_bootstrap_runtime import (
    issue_key,
    runtime_parallel,  # noqa: F401 — shared fixture
    wait_for_two_runtime_locks,
)

from backend.models import APIKey, Device


@pytest.mark.parametrize("change", ["revoke", "permission", "expire"])
async def test_enrollment_rechecks_key_after_competing_admin_commit(runtime_parallel, change):
    r = runtime_parallel
    w = r.world
    key, raw = await issue_key(w)
    async with w.sessions() as holder:
        row = await holder.scalar(select(APIKey).where(APIKey.id == key.id).with_for_update())
        pending = [asyncio.create_task(
            w.client.post("/api/v1/devices/register", headers={"X-API-Key": raw}, json={"fingerprint": w.suffix + str(i)})
        ) for i in range(2)]
        try:
            await wait_for_two_runtime_locks(r)
            if change == "revoke":
                row.is_active = False
            elif change == "permission":
                row.permissions = []
            else:
                row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await holder.commit()
            responses = await asyncio.wait_for(asyncio.gather(*pending), 5)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    expected = 403 if change == "permission" else 401
    assert [response.status_code for response in responses] == [expected, expected]
    async with w.sessions() as db:
        assert (await db.scalars(select(Device.id).where(Device.meta["fingerprint"].as_string().in_([w.suffix + "0", w.suffix + "1"])))).all() == []
