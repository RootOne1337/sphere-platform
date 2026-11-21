"""Schema upgrade preserves legacy bytes; downgrade never drops encrypted secrets."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateSchema


def migrate(connection, direction):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20260906_account_ciphertext.py"
    spec = importlib.util.spec_from_file_location("audit_account_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.mark.parametrize("encrypted", [False, True])
async def test_schema_migration_preserves_legacy_values_and_blocks_unsafe_downgrade(world, encrypted):
    async with world.engine.connect() as connection:
        outer = await connection.begin()
        try:
            schema = "audit_credentials_" + uuid.uuid4().hex
            await connection.execute(CreateSchema(schema))
            await connection.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": schema})
            await connection.execute(text("CREATE TABLE game_accounts (id integer, password_encrypted text NOT NULL)"))
            await connection.execute(text("INSERT INTO game_accounts VALUES (1, 'gAAAA-legacy-audit')"))
            await connection.run_sync(migrate, "upgrade")
            assert (await connection.execute(text("SELECT password_encrypted, password_ciphertext FROM game_accounts"))).one() == (
                "gAAAA-legacy-audit", None)
            if encrypted:
                savepoint = await connection.begin_nested()
                with pytest.raises(DBAPIError):
                    await connection.execute(text("UPDATE game_accounts SET password_ciphertext='audit-token'"))
                await savepoint.rollback()
                await connection.execute(text("UPDATE game_accounts SET password_ciphertext='audit-token', password_encrypted=''"))
                savepoint = await connection.begin_nested()
                with pytest.raises(DBAPIError):
                    await connection.run_sync(migrate, "downgrade")
                await savepoint.rollback()
                assert await connection.scalar(text("SELECT password_ciphertext FROM game_accounts")) == "audit-token"
            else:
                await connection.run_sync(migrate, "downgrade")
                assert await connection.scalar(text("SELECT password_encrypted FROM game_accounts")) == "gAAAA-legacy-audit"
        finally:
            await outer.rollback()
