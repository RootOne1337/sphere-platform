"""Exercise the migrated application schema as a non-owner PostgreSQL runtime role."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError

from backend.database.engine import Base
from backend.models import (
    AuditLog,
    DeviceGroup,
    Location,
    PipelineSettings,
    device_group_members,
    device_location_members,
)


@pytest_asyncio.fixture
async def tenant_role(world):
    role = "audit_policy_" + world.suffix
    tables = sorted(Base.metadata.tables)
    # Identifiers come from trusted model metadata and a generated UUID, never a request.
    table_sql = ", ".join(f'public."{table}"' for table in tables)
    async with world.sessions() as db:
        groups = [DeviceGroup(org_id=org.id, name="policy-group") for org in (world.org_a, world.org_b)]
        locations = [Location(org_id=org.id, name="policy-location") for org in (world.org_a, world.org_b)]
        settings = [PipelineSettings(org_id=org.id) for org in (world.org_a, world.org_b)]
        logs = [AuditLog(org_id=org.id, action="audit.rls") for org in (world.org_a, world.org_b)]
        db.add_all(groups + locations + settings + logs)
        await db.flush()
        for index, device in enumerate((world.dev_a, world.dev_b)):
            await db.execute(insert(device_group_members).values(device_id=device.id, group_id=groups[index].id))
            await db.execute(insert(device_location_members).values(device_id=device.id, location_id=locations[index].id))
        await db.commit()
    async with world.engine.begin() as db:
        await db.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
        await db.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        await db.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {table_sql} TO "{role}"'))

    @asynccontextmanager
    async def connect(org="a"):
        async with world.engine.connect() as db:
            await db.execute(text(f'SET LOCAL ROLE "{role}"'))
            value = {"a": str(world.org_a.id), "b": str(world.org_b.id)}.get(org, org)
            if value is not None:
                await db.execute(text("SELECT set_config('app.current_org_id', :org, true)"), {"org": value})
            yield db
            # Always rolled back, including destructive DML against synthetic fixtures.

    try:
        yield SimpleNamespace(**locals())
    finally:
        async with world.engine.begin() as db:
            await db.execute(text(f'REVOKE ALL PRIVILEGES ON {table_sql} FROM "{role}"'))
            await db.execute(text(f'REVOKE USAGE ON SCHEMA public FROM "{role}"'))
            await db.execute(text(f'DROP ROLE "{role}"'))


async def test_every_mapped_table_has_active_rls_and_policies_for_runtime(tenant_role):
    w = tenant_role
    async with w.connect() as db:
        rows = (await db.execute(text("""
            SELECT c.relname, row_security_active(c.oid) AS active,
                   EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid) AS has_policy
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(:tables)
        """), {"tables": w.tables})).all()
    assert len(rows) == len(w.tables)
    assert [(name, active, policy) for name, active, policy in rows if not active or not policy] == []


@pytest.mark.parametrize("table, key", [
    ("devices", "id"), ("users", "org_id"), ("organizations", "id"),
    ("pipeline_settings", "org_id"), ("audit_logs", "org_id"),
])
async def test_runtime_can_read_its_own_rows_without_explicit_tenant_filter(tenant_role, table, key):
    w = tenant_role
    async with w.connect() as db:
        values = set((await db.scalars(text(f'SELECT "{key}" FROM "{table}"'))).all())
    expected = {w.world.dev_a.id, w.world.dev_a2.id} if table == "devices" else {w.world.org_a.id}
    assert values == expected


@pytest.mark.parametrize("table, key, index", [
    ("device_group_members", "group_id", "groups"),
    ("device_location_members", "location_id", "locations"),
])
async def test_association_reads_and_deletes_are_tenant_scoped(tenant_role, table, key, index):
    w = tenant_role
    async with w.connect() as db:
        assert (await db.scalars(text(f'SELECT "{key}" FROM "{table}"'))).all() == [getattr(w, index)[0].id]
        result = await db.execute(text(f'DELETE FROM "{table}" WHERE device_id=:foreign'),
                                  {"foreign": w.world.dev_b.id})
        assert result.rowcount == 0


@pytest.mark.parametrize("table, key, index", [
    ("device_group_members", "group_id", "groups"),
    ("device_location_members", "location_id", "locations"),
])
@pytest.mark.parametrize("foreign_device", [False, True])
async def test_association_insert_requires_both_endpoints_in_current_tenant(tenant_role, table, key, index, foreign_device):
    w = tenant_role
    device = w.world.dev_b if foreign_device else w.world.dev_a2
    endpoint = getattr(w, index)[0 if foreign_device else 1]
    async with w.connect() as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(text(f'INSERT INTO "{table}" (device_id, "{key}") VALUES (:device, :endpoint)'),
                             {"device": device.id, "endpoint": endpoint.id})


@pytest.mark.parametrize("table, key, index", [
    ("device_group_members", "group_id", "groups"),
    ("device_location_members", "location_id", "locations"),
])
async def test_same_tenant_association_crud_remains_available(tenant_role, table, key, index):
    w = tenant_role
    async with w.connect() as db:
        await db.execute(text(f'INSERT INTO "{table}" (device_id, "{key}") VALUES (:device, :endpoint)'),
                         {"device": w.world.dev_a2.id, "endpoint": getattr(w, index)[0].id})
        assert await db.scalar(text(f'SELECT count(*) FROM "{table}"')) == 2
        result = await db.execute(text(f'DELETE FROM "{table}" WHERE device_id=:device'), {"device": w.world.dev_a2.id})
        assert result.rowcount == 1


async def test_runtime_cannot_read_or_change_foreign_orchestration_settings(tenant_role):
    w = tenant_role
    async with w.connect() as db:
        result = await db.execute(text("UPDATE pipeline_settings SET orchestration_enabled=true WHERE org_id=:foreign"),
                                  {"foreign": w.world.org_b.id})
        assert result.rowcount == 0
        result = await db.execute(text("DELETE FROM pipeline_settings WHERE org_id=:foreign"), {"foreign": w.world.org_b.id})
        assert result.rowcount == 0
        # The same role must still be able to write its own configuration.
        result = await db.execute(text("UPDATE pipeline_settings SET orchestration_enabled=true WHERE org_id=:own"),
                                  {"own": w.world.org_a.id})
        assert result.rowcount == 1


async def test_runtime_cannot_transfer_its_row_to_another_tenant(tenant_role):
    w = tenant_role
    async with w.connect() as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(text("UPDATE devices SET org_id=:foreign WHERE id=:own"),
                             {"foreign": w.world.org_b.id, "own": w.world.dev_a.id})


@pytest.mark.parametrize("table, key, index", [
    ("device_group_members", "group_id", "groups"),
    ("device_location_members", "location_id", "locations"),
])
async def test_association_update_cannot_attach_foreign_endpoint(tenant_role, table, key, index):
    w = tenant_role
    async with w.connect() as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(text(f'UPDATE "{table}" SET "{key}"=:foreign WHERE device_id=:own'),
                             {"foreign": getattr(w, index)[1].id, "own": w.world.dev_a.id})


async def test_actual_runtime_role_passes_startup_on_complete_migrated_schema(tenant_role, monkeypatch):
    from backend.core.config import settings
    from backend.core.startup_checks import check_db_role_not_superuser

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr("backend.database.engine.engine", SimpleNamespace(connect=tenant_role.connect))
    await check_db_role_not_superuser()


@pytest.mark.parametrize("context", [None, ""])
async def test_absent_or_empty_context_fails_closed(tenant_role, context):
    async with tenant_role.connect(context) as db:
        for table in tenant_role.tables:
            assert await db.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0, table


async def test_malformed_context_cannot_write_orchestration_settings(tenant_role):
    async with tenant_role.connect("invalid-uuid") as db:
        with pytest.raises(DBAPIError, match="invalid input syntax for type uuid"):
            await db.execute(text("UPDATE pipeline_settings SET orchestration_enabled=true"))


@pytest.mark.parametrize("target", ["own", "foreign", "platform"])
async def test_audit_insert_requires_current_tenant_and_audit_is_append_only(tenant_role, target):
    w = tenant_role
    org = {"own": w.world.org_a.id, "foreign": w.world.org_b.id, "platform": None}[target]
    async with w.connect() as db:
        stmt = text("INSERT INTO audit_logs (org_id, action) VALUES (:org, 'audit.rls.insert')")
        if target != "own":
            with pytest.raises(DBAPIError, match="row-level security"):
                await db.execute(stmt, {"org": org})
        else:
            await db.execute(stmt, {"org": org})
            assert await db.scalar(text("SELECT count(*) FROM audit_logs")) == 2
            assert (await db.execute(text("UPDATE audit_logs SET action='tampered'"))).rowcount == 0
            assert (await db.execute(text("DELETE FROM audit_logs"))).rowcount == 0
