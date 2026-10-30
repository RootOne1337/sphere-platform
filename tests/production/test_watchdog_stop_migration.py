"""Watchdog timeout intent/lookup migration in a rollback-only schema."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


async def test_watchdog_lookup_deadlines_acl_cursor_and_downgrade(world):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260921_watchdog_stop.py"
    spec = importlib.util.spec_from_file_location("watchdog_stop_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def exercise(connection):
        schema = "watchdog_stop_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("""CREATE TABLE tasks(id uuid PRIMARY KEY,org_id uuid,status text,
            created_at timestamptz,started_at timestamptz,timeout_seconds integer,cancel_requested_at timestamptz)"""))
        tenant = uuid.uuid4()
        expected = set()
        cases = [
            ("queued", -7200, None, False, True), ("assigned", -7200, None, False, True),
            ("running", -7200, -361, False, True), ("running", -7200, -359, False, False),
            ("running", -7200, None, False, True), ("running", -3599, None, False, False),
            ("queued", -3599, None, False, False), ("assigned", -3599, None, False, False),
            ("running", -7200, -361, True, False), ("queued", -7200, None, True, False),
            ("timeout", -7200, None, False, False), ("completed", -7200, -361, False, False),
        ]
        for index, (status, age, started, cancel, due) in enumerate(cases):
            task_id = uuid.UUID(int=index+1)
            connection.execute(text("""INSERT INTO tasks VALUES(:id,:org,:status,now()+:age*interval '1 second',
                now()+:started*interval '1 second',60,CASE WHEN :cancel THEN now() END)"""),
                {"id": task_id, "org": tenant, "status": status, "age": age, "started": started, "cancel": cancel})
            if due:
                expected.add(task_id)
        operation = Operations(MigrationContext.configure(connection))
        execute = operation.execute
        def isolated(statement):
            return execute(statement.replace("sphere_auth.watchdog_work", f'"{schema}".watchdog_work')
                           .replace("public.tasks", f'"{schema}".tasks'))
        operation.execute = isolated
        module.op = operation
        module.upgrade()
        query = text(f'SELECT * FROM "{schema}".watchdog_work(:stale,:queued,:after)')
        args = {"stale": 300, "queued": 60, "after": None}
        rows = connection.execute(query, args).all()
        assert {row[0] for row in rows} == expected and all(row[1] == tenant for row in rows)
        assert not connection.execute(query, {**args, "stale": -1}).all()
        assert not connection.execute(query, {**args, "queued": -1}).all()
        assert connection.scalar(text("SELECT count(*) FROM tasks WHERE timeout_requested_at IS NOT NULL")) == 0
        assert connection.scalar(text("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
            LATERAL aclexplode(p.proacl) a WHERE n.nspname=:schema AND a.grantee=0"""), {"schema": schema}) == 0
        config = connection.execute(text("""SELECT prosecdef,proconfig FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema"""), {"schema": schema}).one()
        assert config[0] and "row_security=off" in config[1] and "search_path=pg_catalog, pg_temp" in config[1]
        for index in range(70):
            task_id = uuid.UUID(int=index+100)
            connection.execute(text("""INSERT INTO tasks(id,org_id,status,created_at,timeout_seconds)
                VALUES(:id,:org,'queued',now()-interval '2 hours',60)"""), {"id": task_id, "org": tenant})
            expected.add(task_id)
        first = connection.execute(query, args).all()
        second = connection.execute(query, {**args, "after": first[-1][0]}).all()
        assert len(first) == 64 and len(second) == 10
        assert {row[0] for row in first + second} == expected
        connection.execute(text("UPDATE tasks SET cancel_requested_at=now(),timeout_requested_at=now() WHERE id=:id"), {"id": uuid.UUID(int=3)})
        module.downgrade()
        assert "timeout_requested_at" not in {c["name"] for c in inspect(connection).get_columns("tasks")}
        assert connection.scalar(text("SELECT count(*) FROM tasks")) == 82
        assert connection.scalar(text("SELECT cancel_requested_at FROM tasks WHERE id=:id"), {"id": uuid.UUID(int=3)}) is not None
        module.upgrade()
        assert len(connection.execute(query, args).all()) == 64

    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
