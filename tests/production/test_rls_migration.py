"""Upgrade legacy/operator policies transactionally in a disposable schema."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260908_tenant_policies.py"
    spec = importlib.util.spec_from_file_location("audit_tenant_policies_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate(connection, direction):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


@pytest.mark.parametrize("scenario", ["legacy", "operator_permissive", "operator_restrictive", "downgrade"])
async def test_migration_preserves_restrictions_and_cannot_restore_cross_tenant_access(world, scenario):
    module = migration()
    schema = "audit_policy_migration_" + world.suffix
    role = "audit_policy_migration_role_" + world.suffix
    async with world.engine.connect() as db:
        outer = await db.begin()
        try:
            await db.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
            await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            await db.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": schema})
            # Minimal legacy columns for policy DDL. test_rls_policies separately uses
            # the complete application schema actually upgraded by Alembic in CI.
            for table in (*module.ORG_TABLES, *module.IDENTITY_TABLES):
                await db.execute(text(f'CREATE TABLE "{table}" (id uuid, org_id uuid)'))
            for table, (_, key) in module.ASSOCIATIONS.items():
                await db.execute(text(f'CREATE TABLE "{table}" (device_id uuid, "{key}" uuid)'))
            for table in ("pipeline_settings", "devices", "audit_logs"):
                await db.execute(text(f'INSERT INTO "{table}" (org_id) VALUES (:a), (:b)'),
                                 {"a": world.org_a.id, "b": world.org_b.id})
            if scenario == "legacy":
                await db.execute(text("CREATE POLICY devices_tenant_isolation ON devices USING (org_id=current_setting('app.current_org_id')::uuid)"))
                await db.execute(text("CREATE POLICY audit_insert_only ON audit_logs FOR INSERT WITH CHECK (true)"))
            elif scenario == "operator_permissive":
                for table in ("pipeline_settings", "audit_logs"):
                    await db.execute(text(f'CREATE POLICY operator_allow ON "{table}" USING (true) WITH CHECK (true)'))
            elif scenario == "operator_restrictive":
                await db.execute(text("CREATE POLICY operator_deny ON devices AS RESTRICTIVE USING (false)"))

            await db.run_sync(migrate, "upgrade")
            if scenario == "downgrade":
                with pytest.raises(RuntimeError, match="downgrade is blocked"):
                    await db.run_sync(migrate, "downgrade")
            if scenario.startswith("operator"):
                assert await db.scalar(text("SELECT count(*) FROM pg_policies WHERE schemaname=:schema AND policyname LIKE 'operator_%'"),
                                       {"schema": schema}) == (2 if scenario == "operator_permissive" else 1)

            await db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            await db.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
            await db.execute(text(f'SET LOCAL ROLE "{role}"'))
            await db.execute(text("SELECT set_config('app.current_org_id', :org, true)"), {"org": str(world.org_a.id)})
            assert (await db.scalars(text("SELECT org_id FROM pipeline_settings"))).all() == [world.org_a.id]
            assert (await db.execute(text("UPDATE pipeline_settings SET id=org_id"))).rowcount == 1
            assert (await db.execute(text("DELETE FROM audit_logs"))).rowcount == 0
            assert (await db.execute(text("UPDATE audit_logs SET id=org_id"))).rowcount == 0
            assert await db.scalar(text("SELECT count(*) FROM devices")) == (0 if scenario == "operator_restrictive" else 1)
            savepoint = await db.begin_nested()
            with pytest.raises(DBAPIError, match="row-level security"):
                await db.execute(text("INSERT INTO audit_logs (org_id) VALUES (:foreign)"), {"foreign": world.org_b.id})
            await savepoint.rollback()
            await db.execute(text("SELECT set_config('app.current_org_id', '', true)"))
            assert await db.scalar(text("SELECT count(*) FROM devices")) == 0
        finally:
            await outer.rollback()  # Removes only this test's schema and role, too.
