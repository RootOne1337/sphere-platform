"""Bounded one-time VPN migration worker. Invoked in the admitted image only.

No HTTP server, game commands, key output, default-route changes or credential
replacement. A partial result is reconciled by the release tool, not retried here.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROLE = "sphere_vpn_catalog"
OLD = "20261006_script_catalog_metadata"
NEW = "20261021_vpn_profiles"


async def prepare(private_file: Path = Path("/run/secrets/vpn-catalog.json")) -> dict:
    from backend.core.config import settings
    from backend.services.vpn.catalog_database import catalog_url

    if private_file.stat().st_size > 8192:
        raise ValueError("catalog_secret_budget_exceeded")
    private = json.loads(private_file.read_text())
    password = private["VPN_PROFILE_DATABASE_PASSWORD"]
    if (
        private["VPN_PROFILE_DATABASE_ROLE"] != ROLE
        or not re.fullmatch(r"[a-f0-9]{64}", password)
        or catalog_url().username != ROLE
        or catalog_url().password != password
    ):
        raise ValueError("catalog_secret_identity_invalid")
    engine = create_async_engine(
        settings.POSTGRES_URL,
        echo=False,
        hide_parameters=True,
        connect_args={"command_timeout": 20},
    )
    try:
        async with engine.begin() as db:
            await db.execute(text("SET LOCAL lock_timeout = '3s'"))
            await db.execute(text("SET LOCAL statement_timeout = '15s'"))
            head = await db.scalar(text("SELECT version_num FROM alembic_version"))
            if head != OLD:
                raise ValueError("catalog_schema_baseline_changed")
            if await db.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": ROLE}
            ):
                raise ValueError("catalog_role_already_exists_requires_reconciliation")
            # Suppress native SQL statement output in this finite transaction;
            # credentials/verifiers never belong in a database statement log.
            await db.execute(text("SET LOCAL log_statement = 'none'"))
            await db.execute(text("SET LOCAL log_min_error_statement = 'panic'"))
            await db.execute(
                text(
                    f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{password}'"
                )
            )
            await db.execute(text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))
            database = db.dialect.identifier_preparer.quote(engine.url.database)
            await db.execute(text(f"GRANT CONNECT ON DATABASE {database} TO {ROLE}"))
        # Alembic runs its own bounded migration transaction. Its new revision
        # creates only the two catalog tables; the original role is preserved.
        from alembic import command
        from alembic.config import Config

        await asyncio.to_thread(command.upgrade, Config("alembic/alembic.ini"), NEW)
        async with engine.begin() as db:
            await db.execute(text("SET LOCAL lock_timeout = '3s'"))
            await db.execute(text("SET LOCAL statement_timeout = '15s'"))
            if await db.scalar(text("SELECT version_num FROM alembic_version")) != NEW:
                raise ValueError("catalog_schema_result_unknown")
            await db.execute(text(f"GRANT SELECT, INSERT, UPDATE ON vpn_profiles TO {ROLE}"))
            await db.execute(text(f"GRANT SELECT, INSERT ON vpn_profile_revisions TO {ROLE}"))
            await db.execute(text(f"GRANT INSERT ON audit_logs TO {ROLE}"))
            await db.execute(text(f"GRANT SELECT (id,created_at) ON audit_logs TO {ROLE}"))
        # Connect as the actual new login, not SET ROLE on a superuser session.
        from backend.services.vpn.catalog_database import _ROLE_CHECK

        scoped = create_async_engine(
            catalog_url(), echo=False, hide_parameters=True, connect_args={"command_timeout": 10}
        )
        try:
            async with scoped.begin() as db:
                org = "00000000-0000-4000-8000-000000000001"
                await db.execute(
                    text("SELECT set_config('app.current_org_id', :org, true)"), {"org": org}
                )
                row = (await db.execute(_ROLE_CHECK, {"org_id": org})).mappings().one()
                if not all(value is True for value in row.values()):
                    raise ValueError("catalog_runtime_policy_not_confirmed")
                for table in ["vpn_profiles", "vpn_profile_revisions"]:
                    if await db.scalar(text(f"SELECT count(*) FROM {table}")) != 0:
                        raise ValueError("new_catalog_not_empty")
        finally:
            await scoped.dispose()
        return {
            "schemaHead": NEW,
            "catalogRoleCreated": True,
            "actualLoginChecked": True,
            "minimalGrantsApplied": True,
            "catalogEmpty": True,
            "legacyRoleChanged": False,
        }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps({"state": "success", **asyncio.run(prepare())}))
    except Exception:
        # Exceptions can carry raw SQL or connection credentials. Keep them out
        # of Docker logs and public operational receipts, including tracebacks.
        print(json.dumps({"state": "unknown", "detail": "catalog_prepare_requires_reconciliation"}))
        raise SystemExit(2) from None
