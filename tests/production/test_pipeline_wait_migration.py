"""Waiting lookup migration retains ACLs and wakes only due/terminal parents."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


async def test_waiting_migration_keeps_acl_and_reverses_without_losing_runs(world):
    def load(filename):
        spec = importlib.util.spec_from_file_location(filename, Path(__file__).resolve().parents[2] / "alembic/versions" / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    prior, migration = load("20260921_pipeline_discovery.py"), load("20260921_pipeline_wait.py")

    def exercise(connection):
        schema = "pipeline_wait_migration_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("""CREATE TABLE pipeline_runs (
            id uuid PRIMARY KEY, org_id uuid, device_id uuid, status text,
            cancel_requested_at timestamptz, created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now(), execution_owner uuid,
            execution_lease_until timestamptz, current_child_run_id uuid, context jsonb DEFAULT '{}')"""))
        operation = Operations(MigrationContext.configure(connection))
        execute = operation.execute
        operation.execute = lambda statement: execute(
            statement.replace("sphere_auth.pipeline_work", f'"{schema}".pipeline_work')
            .replace("public.pipeline_runs", f'"{schema}".pipeline_runs')
        )
        prior.op = migration.op = operation
        prior.upgrade()
        original_acl = connection.scalar(text("""SELECT p.proacl::text FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema"""), {"schema": schema})
        tenant, device, parent, child = (uuid.uuid4() for _ in range(4))
        connection.execute(text("""INSERT INTO pipeline_runs(id,org_id,device_id,status,current_child_run_id)
            VALUES (:id,:org,:device,'waiting',:child)"""), {"id": parent, "org": tenant, "device": device, "child": child})
        connection.execute(text("""INSERT INTO pipeline_runs(id,org_id,device_id,status,context)
            VALUES (:id,:org,:device,'queued',jsonb_build_object('parent_run_id',CAST(:parent AS text)))"""),
            {"id": child, "org": tenant, "device": device, "parent": str(parent)})
        migration.upgrade()
        def candidates():
            return {row[0] for row in connection.execute(text(f'SELECT * FROM "{schema}".pipeline_work(\'recovery\')'))}
        assert parent in candidates()  # legacy WAITING without deadline is still recoverable
        connection.execute(text("UPDATE pipeline_runs SET wait_deadline_at=now()+interval '1 hour' WHERE id=:id"), {"id": parent})
        assert parent not in candidates()
        connection.execute(text("UPDATE pipeline_runs SET status='completed' WHERE id=:id"), {"id": child})
        assert parent in candidates()
        connection.execute(text("UPDATE pipeline_runs SET status='queued' WHERE id=:id"), {"id": child})
        connection.execute(text("UPDATE pipeline_runs SET wait_deadline_at=now()-interval '1 second' WHERE id=:id"), {"id": parent})
        assert parent in candidates()
        connection.execute(text("UPDATE pipeline_runs SET wait_deadline_at=now()+interval '1 hour' WHERE id=:id"), {"id": parent})
        connection.execute(text("UPDATE pipeline_runs SET org_id=:foreign WHERE id=:id"), {"id": child, "foreign": uuid.uuid4()})
        assert parent in candidates()  # foreign reference is not a valid active child
        assert connection.scalar(text("""SELECT p.proacl::text FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema"""), {"schema": schema}) == original_acl
        assert any(i["name"] == "ix_pipeline_runs_wait_deadline" for i in inspect(connection).get_indexes("pipeline_runs"))
        migration.downgrade()
        assert "wait_deadline_at" not in {c["name"] for c in inspect(connection).get_columns("pipeline_runs")}
        assert connection.scalar(text("SELECT count(*) FROM pipeline_runs")) == 2
        assert parent in candidates()
        migration.upgrade()
        assert parent in candidates()

    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
