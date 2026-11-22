"""Run discovery DDL and cursor predicates in a rollback-only private schema."""

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


async def test_task_discovery_filters_pages_acl_and_round_trip(world):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260921_task_dispatch.py"
    spec = importlib.util.spec_from_file_location("task_dispatch_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def exercise(connection):
        schema = "task_dispatch_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("CREATE TABLE devices(id uuid PRIMARY KEY, org_id uuid, is_active boolean)"))
        connection.execute(text("""CREATE TABLE tasks(id uuid PRIMARY KEY, org_id uuid, device_id uuid,
            status text, updated_at timestamptz, cancel_requested_at timestamptz, cancel_last_sent_at timestamptz)"""))
        tenant = uuid.uuid4()
        expected = {"assign": set(), "cancel": set()}
        cases = [
            ("queued", True, False, 0, None, "assign"),
            ("assigned", True, False, -31, None, "assign"),
            ("assigned", True, False, -29, None, None),
            ("running", True, False, -31, None, None),
            ("queued", False, False, -31, None, None),
            ("assigned", False, True, -31, None, "cancel"),
            ("running", True, True, -31, -6, "cancel"),
            ("running", True, True, -31, -4, None),
            ("completed", True, True, -31, -6, None),
            ("queued", True, True, -31, -6, None),
        ]
        for index, (status, active, cancel, updated, last_sent, kind) in enumerate(cases):
            device = uuid.UUID(int=index + 1)
            connection.execute(text("INSERT INTO devices VALUES(:id,:org,:active)"),
                               {"id": device, "org": tenant, "active": active})
            connection.execute(text("""INSERT INTO tasks VALUES(:id,:org,:device,:status,
                now()+:updated*interval '1 second', CASE WHEN :cancel THEN now() END,
                now()+:last_sent*interval '1 second')"""),
                {"id": uuid.uuid4(), "org": tenant, "device": device, "status": status,
                 "updated": updated, "cancel": cancel, "last_sent": last_sent})
            if kind:
                expected[kind].add(device)
        # Duplicate task for the same device yields one candidate, foreign org none.
        connection.execute(text("INSERT INTO tasks VALUES(:id,:org,:device,'queued',now(),NULL,NULL)"),
                           {"id": uuid.uuid4(), "org": tenant, "device": uuid.UUID(int=1)})
        connection.execute(text("INSERT INTO tasks VALUES(:id,:org,:device,'queued',now(),NULL,NULL)"),
                           {"id": uuid.uuid4(), "org": uuid.uuid4(), "device": uuid.UUID(int=3)})
        operation = Operations(MigrationContext.configure(connection))
        execute = operation.execute

        def isolated(statement):
            return execute(statement.replace("sphere_auth.task_dispatch_work", f'"{schema}".task_dispatch_work')
                           .replace("public.tasks", f'"{schema}".tasks')
                           .replace("public.devices", f'"{schema}".devices'))
        operation.execute = isolated
        module.op = operation
        module.upgrade()
        query = text(f'SELECT * FROM "{schema}".task_dispatch_work(:kind,:after)')
        for kind, ids in expected.items():
            rows = connection.execute(query, {"kind": kind, "after": None}).all()
            assert {row[0] for row in rows} == ids and all(row[1] == tenant for row in rows)
        assert not connection.execute(query, {"kind": "invalid", "after": None}).all()
        assert connection.scalar(text("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
            LATERAL aclexplode(p.proacl) a WHERE n.nspname=:schema AND a.grantee=0"""), {"schema": schema}) == 0
        config = connection.execute(text("""SELECT prosecdef, proconfig FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema"""), {"schema": schema}).one()
        assert config[0] and "search_path=pg_catalog, pg_temp" in config[1] and "row_security=off" in config[1]
        for index in range(70):
            device = uuid.UUID(int=100 + index)
            connection.execute(text("INSERT INTO devices VALUES(:id,:org,true)"), {"id": device, "org": tenant})
            connection.execute(text("INSERT INTO tasks VALUES(:id,:org,:device,'queued',now(),NULL,NULL)"),
                               {"id": uuid.uuid4(), "org": tenant, "device": device})
            expected["assign"].add(device)
        first = connection.execute(query, {"kind": "assign", "after": None}).all()
        second = connection.execute(query, {"kind": "assign", "after": first[-1][0]}).all()
        assert len(first) == 64 and len(second) == 8
        assert {row[0] for row in first + second} == expected["assign"]
        module.downgrade()
        assert connection.scalar(text("SELECT count(*) FROM tasks")) == 82
        module.upgrade()
        assert len(connection.execute(query, {"kind": "assign", "after": None}).all()) == 64

    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
