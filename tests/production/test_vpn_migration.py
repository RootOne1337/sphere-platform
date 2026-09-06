"""Run the real VPN migration on a throwaway schema inside the isolated DB."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateSchema

from alembic.migration import MigrationContext
from alembic.operations import Operations


def migrate(connection, direction):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260906_vpn_intents.py"
    spec = importlib.util.spec_from_file_location("audit_vpn_intents_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.mark.parametrize("legacy_ips", [
    ["10.199.0.1", "10.199.0.1"],
    ["invalid-address"],
    ["10.199.0.1/24"],
])
async def test_migration_refuses_legacy_conflicts_without_changing_rows(world, legacy_ips):
    async with world.engine.connect() as conn:
        outer = await conn.begin()
        try:
            schema = "audit_vpn_" + uuid.uuid4().hex
            await conn.execute(CreateSchema(schema))
            await conn.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": schema})
            await conn.execute(text("CREATE TABLE vpn_peers (id integer, tunnel_ip varchar(45), status varchar(8))"))
            for i, ip in enumerate(legacy_ips):
                await conn.execute(text("INSERT INTO vpn_peers VALUES (:id, :ip, 'ASSIGNED')"), {"id": i, "ip": ip})
            nested = await conn.begin_nested()
            with pytest.raises(DBAPIError):
                await conn.run_sync(migrate, "upgrade")
            await nested.rollback()
            values = (await conn.scalars(text("SELECT tunnel_ip FROM vpn_peers ORDER BY id"))).all()
            assert values == legacy_ips
            columns = (await conn.scalars(text("""SELECT column_name FROM information_schema.columns
                WHERE table_schema=:schema AND table_name='vpn_peers'"""), {"schema": schema})).all()
            assert set(columns) == {"id", "tunnel_ip", "status"}
        finally:
            await outer.rollback()  # Includes schema creation; no persistent test schema.


@pytest.mark.parametrize("pending", ["PROVISIONING", "REVOKING"])
async def test_migration_downgrade_refuses_to_discard_pending_intents(world, pending):
    async with world.engine.connect() as conn:
        outer = await conn.begin()
        try:
            schema = "audit_vpn_" + uuid.uuid4().hex
            await conn.execute(CreateSchema(schema))
            await conn.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": schema})
            await conn.execute(text("CREATE TABLE vpn_peers (id integer, tunnel_ip varchar(45), status varchar(8))"))
            await conn.run_sync(migrate, "upgrade")
            await conn.execute(text("INSERT INTO vpn_peers (id, tunnel_ip, status) VALUES (1, '10.199.0.1', :pending)"),
                               {"pending": pending})
            nested = await conn.begin_nested()
            with pytest.raises(DBAPIError):
                await conn.run_sync(migrate, "downgrade")
            await nested.rollback()
            assert await conn.scalar(text("SELECT status FROM vpn_peers WHERE id=1")) == pending
            await conn.execute(text("UPDATE vpn_peers SET status='FREE' WHERE id=1"))
            await conn.run_sync(migrate, "downgrade")
            assert await conn.scalar(text("SELECT tunnel_ip FROM vpn_peers WHERE id=1")) == "10.199.0.1"
        finally:
            await outer.rollback()
