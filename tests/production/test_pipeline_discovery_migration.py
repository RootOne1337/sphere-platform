"""Validate the frozen lookup contract in a rolled-back private namespace."""

import importlib.util
import uuid
from datetime import timedelta
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


async def test_pipeline_discovery_migration_filters_bounds_and_preserves_rows(world):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260921_pipeline_discovery.py"
    spec = importlib.util.spec_from_file_location("pipeline_discovery_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def exercise(connection):
        schema = "pipeline_discovery_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("""CREATE TABLE pipeline_runs (
            id uuid PRIMARY KEY, org_id uuid, status text, cancel_requested_at timestamptz,
            created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
            execution_owner uuid, execution_lease_until timestamptz)"""))
        tenant = uuid.uuid4()
        expected = {"queued": set(), "recovery": set(), "cancel": set()}
        for status, owner, expiry, cancel, kind in [
            ("queued", None, None, False, "queued"),
            ("queued", None, None, True, "cancel"),
            ("running", None, None, False, "recovery"),
            ("running", uuid.uuid4(), timedelta(seconds=-1), False, "recovery"),
            ("waiting", uuid.uuid4(), timedelta(seconds=-1), False, "recovery"),
            ("paused", uuid.uuid4(), timedelta(seconds=-1), False, "recovery"),
            ("running", uuid.uuid4(), timedelta(hours=1), False, None),
            ("paused", None, None, False, None),
            ("completed", None, None, True, None),
            ("running", uuid.uuid4(), timedelta(seconds=-1), True, "cancel"),
        ]:
            run_id = uuid.uuid4()
            connection.execute(text("""INSERT INTO pipeline_runs(id,org_id,status,execution_owner,execution_lease_until,cancel_requested_at)
                VALUES (:id,:org,:status,:owner,now()+CAST(:expiry AS interval),CASE WHEN :cancel THEN now() END)"""),
                {"id": run_id, "org": tenant, "status": status, "owner": owner, "expiry": expiry, "cancel": cancel})
            if kind:
                expected[kind].add(run_id)
        operation = Operations(MigrationContext.configure(connection))
        execute = operation.execute

        def isolated(statement):
            return execute(statement.replace("sphere_auth.pipeline_work", f'"{schema}".pipeline_work')
                           .replace("public.pipeline_runs", f'"{schema}".pipeline_runs'))
        operation.execute = isolated
        module.op = operation
        module.upgrade()
        for kind, ids in expected.items():
            rows = connection.execute(text(f'SELECT * FROM "{schema}".pipeline_work(:kind)'), {"kind": kind}).all()
            assert {row[0] for row in rows} == ids and all(row[1] == tenant for row in rows)
        assert connection.scalar(text("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
            LATERAL aclexplode(p.proacl) a WHERE n.nspname=:schema AND a.grantee=0"""), {"schema": schema}) == 0
        for _ in range(70):
            connection.execute(text("INSERT INTO pipeline_runs(id,org_id,status) VALUES (:id,:org,'queued')"),
                               {"id": uuid.uuid4(), "org": tenant})
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".pipeline_work(\'queued\')')) == 64
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".pipeline_work(\'invalid\')')) == 0
        module.downgrade()
        assert connection.scalar(text("SELECT count(*) FROM pipeline_runs")) == 80
        module.upgrade()
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".pipeline_work(\'queued\')')) == 64

    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
