"""Migration round trip in a transaction-local temporary namespace."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


async def test_batch_plan_migration_preserves_legacy_and_revokes_public_lookup(world):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260920_batch_plan.py"
    spec = importlib.util.spec_from_file_location("batch_plan_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def exercise(connection):
        schema = "batch_migration_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("CREATE TABLE script_versions (id uuid PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE task_batches (id uuid PRIMARY KEY, org_id uuid, status text, created_at timestamptz DEFAULT now())"))
        connection.execute(text("INSERT INTO task_batches(id,org_id,status) VALUES (:id,:org,'running')"),
                           {"id": uuid.uuid4(), "org": uuid.uuid4()})
        operation = Operations(MigrationContext.configure(connection))
        execute = operation.execute

        def private_namespace(statement):
            # Redirect only function/schema references to this disposable namespace.
            statement = statement.replace("sphere_auth.due_batch_admissions", f'"{schema}".due_batch_admissions')
            statement = statement.replace("public.task_batches", f'"{schema}".task_batches')
            return execute(statement)

        operation.execute = private_namespace
        module.op = operation
        module.upgrade()
        assert connection.execute(text("SELECT admission_state,wave_plan FROM task_batches")).one() == ("legacy_unknown", None)
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".due_batch_admissions()')) == 0
        assert connection.scalar(text("""
            SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
                 LATERAL aclexplode(p.proacl) a
            WHERE n.nspname=:schema AND p.proname='due_batch_admissions' AND a.grantee=0
        """), {"schema": schema}) == 0
        module.downgrade()
        assert {c["name"] for c in inspect(connection).get_columns("task_batches")} == {"id", "org_id", "status", "created_at"}
        module.upgrade()
        assert connection.scalar(text("SELECT count(*) FROM task_batches")) == 1

    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
