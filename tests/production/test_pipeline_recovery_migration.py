"""Reversible PostgreSQL migration preserves ambiguous legacy work for review."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


async def test_pipeline_lease_migration_preserves_legacy_states_and_reverses(world):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260920_pipeline_lease.py"
    spec = importlib.util.spec_from_file_location("pipeline_lease_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def exercise(connection):
        schema = "pipeline_lease_migration_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("CREATE TABLE pipeline_runs (id uuid PRIMARY KEY, status text NOT NULL, started_at timestamptz)"))
        for status, started in [("queued", False), ("queued", True), ("running", True), ("paused", True), ("waiting", True), ("completed", True)]:
            connection.execute(text("INSERT INTO pipeline_runs VALUES (:id, :status, CASE WHEN :started THEN now() END)"),
                               {"id": uuid.uuid4(), "status": status, "started": started})
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            rows = connection.execute(text("SELECT status, started_at IS NOT NULL, execution_phase FROM pipeline_runs")).all()
            assert ("queued", False, "ready") in rows
            assert ("queued", True, "unknown") in rows
            for status in ("running", "paused", "waiting"):
                assert (status, True, "unknown") in rows
            assert ("completed", True, "ready") in rows
            assert connection.scalar(text("SELECT count(*) FROM pipeline_runs WHERE execution_owner IS NULL AND execution_generation=0")) == 6
            module.downgrade()
            assert {c["name"] for c in inspect(connection).get_columns("pipeline_runs")} == {"id", "status", "started_at"}
            assert connection.scalar(text("SELECT count(*) FROM pipeline_runs")) == 6
            module.upgrade()
            assert any(i["name"] == "ix_pipeline_runs_recovery" for i in inspect(connection).get_indexes("pipeline_runs"))

    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
