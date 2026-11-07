"""Exercise upgrade/downgrade against PostgreSQL without changing the live schema."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


async def test_nullable_cancel_migrations_preserve_existing_rows_and_reverse(world):
    modules = []
    root = Path(__file__).resolve().parents[2]
    for name in ("20260920_task_cancel_intent", "20260920_pipeline_cancel"):
        spec = importlib.util.spec_from_file_location(name, root / "alembic/versions" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)

    def exercise(connection):
        schema = "cancel_migration_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        for table in ("tasks", "pipeline_runs"):
            connection.execute(text(f'CREATE TABLE {table} (id integer PRIMARY KEY)'))
            connection.execute(text(f'INSERT INTO {table} VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            for module in modules:
                module.upgrade()
            assert connection.execute(text("SELECT cancel_requested_at, cancel_last_sent_at FROM tasks WHERE id=1")).one() == (None, None)
            assert connection.execute(text("SELECT cancel_requested_at FROM pipeline_runs WHERE id=1")).one() == (None,)
            for module in reversed(modules):
                module.downgrade()
            for table in ("tasks", "pipeline_runs"):
                assert [column["name"] for column in inspect(connection).get_columns(table)] == ["id"]
                assert connection.execute(text(f"SELECT id FROM {table}")).scalar_one() == 1
            for module in modules:
                module.upgrade()
            assert any(index["name"] == "ix_tasks_cancel_requested_at" for index in inspect(connection).get_indexes("tasks"))

    async with world.engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.run_sync(exercise)
        finally:
            await transaction.rollback()  # Includes schema creation: nothing persists.
