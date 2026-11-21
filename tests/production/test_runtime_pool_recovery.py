"""Runtime-role integration pool must recover idle disconnects like production."""

from sqlalchemy import select, text

from backend.database.tenant import bind_tenant_context
from backend.models.device import Device


async def test_idle_pool_disconnect_recovers_without_reusing_tenant_context(runtime_db):
    r = runtime_db
    w = r.world
    async with r.sessions() as db:
        await bind_tenant_context(db, str(w.org_a.id))
        assert await db.scalar(text("SELECT current_user")) == r.role
        backend_pid = await db.scalar(text("SELECT pg_backend_pid()"))
        assert await db.get(Device, w.dev_a.id) is not None
        assert await db.get(Device, w.dev_b.id) is None

    # Only the exact connection captured above in the disposable audit database.
    # Positive timeout acknowledges termination, not just signal delivery.
    async with w.engine.begin() as control:
        assert await control.scalar(text("SELECT pg_terminate_backend(:pid, 2000)"), {"pid": backend_pid})

    async with r.sessions() as db:
        assert await db.scalar(text("SELECT pg_backend_pid()")) != backend_pid
        assert list(await db.scalars(select(Device).where(Device.id.in_([w.dev_a.id, w.dev_b.id])))) == []
        await bind_tenant_context(db, str(w.org_b.id))
        assert await db.get(Device, w.dev_b.id) is not None
        assert await db.get(Device, w.dev_a.id) is None
    async with r.sessions() as db:
        assert await db.scalar(text("SELECT nullif(current_setting('app.current_org_id',true),'')")) is None
