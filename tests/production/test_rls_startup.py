"""Production role checks must reject actual PostgreSQL RLS escape paths."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.core.config import settings
from backend.core.startup_checks import check_db_role_not_superuser


@pytest_asyncio.fixture
async def role_world(world, monkeypatch):
    # UUID-derived names and a loopback-only world; no existing roles or tables are changed.
    owner = "audit_owner_" + world.suffix
    runtime = "audit_runtime_" + world.suffix
    schema = "audit_rls_" + world.suffix
    async with world.engine.begin() as db:
        await db.execute(text(f'CREATE ROLE "{owner}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
        await db.execute(text(f'CREATE ROLE "{runtime}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
        await db.execute(text(f'CREATE SCHEMA "{schema}" AUTHORIZATION "{owner}"'))
        await db.execute(text(f'CREATE TABLE "{schema}".devices (org_id uuid, name text)'))
        await db.execute(text(f'ALTER TABLE "{schema}".devices OWNER TO "{owner}"'))
        await db.execute(text(f'ALTER TABLE "{schema}".devices ENABLE ROW LEVEL SECURITY'))
        await db.execute(text(f'''CREATE POLICY tenant ON "{schema}".devices
            USING (org_id::text = nullif(current_setting('app.current_org_id', true), ''))'''))
        await db.execute(text(f'INSERT INTO "{schema}".devices VALUES (:a, :an), (:b, :bn)'),
                         {"a": world.org_a.id, "an": "tenant A", "b": world.org_b.id, "bn": "tenant B"})
        await db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{runtime}"'))
        await db.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".devices TO "{runtime}"'))

    @asynccontextmanager
    async def connect(role=runtime):
        async with world.engine.connect() as db:
            await db.execute(text(f'SET LOCAL ROLE "{role}"'))
            await db.execute(text("SELECT set_config('search_path', :path, true)"), {"path": schema})
            await db.execute(text("SELECT set_config('app.current_org_id', :org, true)"), {"org": str(world.org_a.id)})
            yield db

    def check_as(role):
        monkeypatch.setattr("backend.database.engine.engine", SimpleNamespace(connect=lambda: connect(role)))

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    try:
        yield SimpleNamespace(**locals())
    finally:
        async with world.engine.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await db.execute(text(f'DROP ROLE "{runtime}"'))
            await db.execute(text(f'DROP ROLE "{owner}"'))


@pytest.mark.parametrize("mode", ["owner", "forced_owner", "inherited_owner", "noinherit_owner"])
async def test_startup_rejects_table_ownership_even_without_superuser_or_bypass(role_world, mode):
    w = role_world
    if mode == "forced_owner":
        async with w.world.engine.begin() as db:
            await db.execute(text(f'ALTER TABLE "{w.schema}".devices FORCE ROW LEVEL SECURITY'))
    if mode in {"inherited_owner", "noinherit_owner"}:
        async with w.world.engine.begin() as db:
            if mode == "noinherit_owner":
                await db.execute(text(f'ALTER ROLE "{w.runtime}" NOINHERIT'))
            await db.execute(text(f'GRANT "{w.owner}" TO "{w.runtime}"'))
    role = w.runtime if "inherit" in mode else w.owner
    w.check_as(role)
    async with w.connect(role) as db:
        flags = (await db.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
        assert flags == (False, False)
        if mode == "noinherit_owner":
            await db.execute(text(f'SET LOCAL ROLE "{w.owner}"'))
        if mode == "forced_owner":
            # FORCE does not remove the owner's ability to disable RLS.
            await db.execute(text("ALTER TABLE devices DISABLE ROW LEVEL SECURITY"))
        assert (await db.execute(text("SELECT name FROM devices ORDER BY name"))).scalars().all() == ["tenant A", "tenant B"]
    with pytest.raises(RuntimeError):
        await check_db_role_not_superuser()


@pytest.mark.parametrize("defect", ["disabled", "missing_policy", "truncate", "bypass_membership"])
async def test_startup_rejects_unsafe_runtime_database_configuration(role_world, defect):
    w = role_world
    async with w.world.engine.begin() as db:
        if defect == "disabled":
            await db.execute(text(f'ALTER TABLE "{w.schema}".devices DISABLE ROW LEVEL SECURITY'))
        elif defect == "missing_policy":
            await db.execute(text(f'DROP POLICY tenant ON "{w.schema}".devices'))
        elif defect == "truncate":
            await db.execute(text(f'GRANT TRUNCATE ON "{w.schema}".devices TO "{w.runtime}"'))
        else:
            await db.execute(text(f'ALTER ROLE "{w.owner}" BYPASSRLS'))
            await db.execute(text(f'GRANT "{w.owner}" TO "{w.runtime}"'))
    if defect == "truncate":
        async with w.connect() as db:
            await db.execute(text("TRUNCATE devices"))
            assert await db.scalar(text("SELECT count(*) FROM devices")) == 0
        # Context rollback restores both synthetic tenant rows.
    w.check_as(w.runtime)
    with pytest.raises(RuntimeError):
        await check_db_role_not_superuser()


async def test_nonowner_runtime_with_enforced_policy_passes_and_sees_only_its_tenant(role_world):
    w = role_world
    w.check_as(w.runtime)
    await check_db_role_not_superuser()
    async with w.connect() as db:
        assert (await db.execute(text("SELECT name FROM devices"))).scalars().all() == ["tenant A"]


async def test_unsafe_development_role_warns_without_claiming_active_rls(role_world, monkeypatch, caplog):
    w = role_world
    w.check_as(w.owner)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    await check_db_role_not_superuser()
    assert "SECURITY" in caplog.text
