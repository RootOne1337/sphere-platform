"""Test due-schedule lookup DDL/ACL/cursor without touching application rows."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


async def test_schedule_lookup_filters_bounds_and_preserves_rows(world):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260921_schedule_work.py"
    spec = importlib.util.spec_from_file_location("schedule_work_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def exercise(connection):
        schema = "schedule_work_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("CREATE TABLE schedules(id uuid PRIMARY KEY,org_id uuid,is_active boolean,next_fire_at timestamptz)"))
        tenants = [uuid.uuid4(), uuid.uuid4()]
        expected = {}
        for index in range(57):
            schedule_id = uuid.UUID(int=index+1)
            active = index != 54
            delay = None if index == 55 else (3600 if index == 56 else -60)
            tenant = tenants[index % 2]
            connection.execute(text("""INSERT INTO schedules VALUES(:id,:org,:active,
                now()+:delay*interval '1 second')"""),
                {"id": schedule_id, "org": tenant, "active": active, "delay": delay})
            if index < 54:
                expected[schedule_id] = tenant
        operation = Operations(MigrationContext.configure(connection))
        execute = operation.execute
        def isolated(statement):
            return execute(statement.replace("sphere_auth.schedule_work", f'"{schema}".schedule_work')
                           .replace("public.schedules", f'"{schema}".schedules'))
        operation.execute = isolated
        module.op = operation
        module.upgrade()
        query = text(f'SELECT * FROM "{schema}".schedule_work(:after)')
        first = connection.execute(query, {"after": None}).all()
        second = connection.execute(query, {"after": first[-1][0]}).all()
        assert len(first) == 50 and len(second) == 4
        assert dict(first + second) == expected
        assert not connection.execute(query, {"after": second[-1][0]}).all()
        assert connection.scalar(text("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
            LATERAL aclexplode(p.proacl) a WHERE n.nspname=:schema AND a.grantee=0"""), {"schema": schema}) == 0
        config = connection.execute(text("""SELECT prosecdef,proconfig FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema"""), {"schema": schema}).one()
        assert config[0] and "row_security=off" in config[1] and "search_path=pg_catalog, pg_temp" in config[1]
        module.downgrade()
        assert connection.scalar(text("SELECT count(*) FROM schedules")) == 57
        module.upgrade()
        assert len(connection.execute(query, {"after": None}).all()) == 50

    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
