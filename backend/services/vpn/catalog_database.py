"""Separate, tenant-bound catalog connections; never demote the legacy API role.

Missing provisioning fails closed for the catalog, without changing media,
control, background jobs or the migration connection used by the rest of Sphere.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from backend.core.config import settings
from backend.core.dependencies import get_current_user
from backend.core.lifespan_registry import register_shutdown
from backend.database.tenant import bind_tenant_context

_engine: AsyncEngine | None = None
_sessions: async_sessionmaker | None = None
_POLICY_KEYS = {
    "restricted_role",
    "profiles_rls",
    "revisions_rls",
    "audit_rls",
    "tenant_bound",
    "catalog_grants",
}
_ROLE_CHECK = text("""
SELECT
  EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = current_user
    AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole) AS restricted_role,
  pg_catalog.row_security_active('public.vpn_profiles'::regclass) AS profiles_rls,
  pg_catalog.row_security_active('public.vpn_profile_revisions'::regclass) AS revisions_rls,
  pg_catalog.row_security_active('public.audit_logs'::regclass) AS audit_rls,
  pg_catalog.current_setting('app.current_org_id', true) = :org_id AS tenant_bound,
  pg_catalog.has_table_privilege(current_user, 'public.vpn_profiles', 'SELECT')
    AND pg_catalog.has_table_privilege(current_user, 'public.vpn_profiles', 'INSERT')
    AND pg_catalog.has_table_privilege(current_user, 'public.vpn_profiles', 'UPDATE')
    AND pg_catalog.has_table_privilege(current_user, 'public.vpn_profile_revisions', 'SELECT')
    AND pg_catalog.has_table_privilege(current_user, 'public.vpn_profile_revisions', 'INSERT')
    AND pg_catalog.has_table_privilege(current_user, 'public.audit_logs', 'INSERT')
    AND pg_catalog.has_column_privilege(current_user, 'public.audit_logs', 'id', 'SELECT')
    AND pg_catalog.has_column_privilege(current_user, 'public.audit_logs', 'created_at', 'SELECT') AS catalog_grants
""")


def catalog_url():
    """Same cluster/database, explicit different login. Never include DSN in errors."""
    try:
        raw = settings.VPN_PROFILE_POSTGRES_URL.get_secret_value()
        if not raw:
            raise ValueError()
        url, primary = make_url(raw), make_url(settings.POSTGRES_URL)
        if (
            url.drivername != "postgresql+asyncpg"
            or not url.username
            or not url.password
            or url.query
            or url.username == primary.username
            or not url.database
            or (url.host, url.port or 5432, url.database)
            != (primary.host, primary.port or 5432, primary.database)
        ):
            raise ValueError()
        return url
    except Exception:
        raise HTTPException(503, "vpn_catalog_database_unavailable") from None


def catalog_sessions():
    global _engine, _sessions
    if _sessions is None:
        _engine = create_async_engine(
            catalog_url(),
            pool_size=2,
            max_overflow=0,
            pool_timeout=3,
            pool_pre_ping=True,
            echo=False,
            hide_parameters=True,
            connect_args={
                "command_timeout": 10,
                "server_settings": {
                    "application_name": "sphere-vpn-catalog",
                    "statement_timeout": "10000",
                    "lock_timeout": "3000",
                },
            },
        )
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessions


async def get_vpn_catalog_db(user=Depends(get_current_user)):
    """Validate the actual login/transaction each request, not a cached flag."""
    try:
        sessions = catalog_sessions()
    except (SQLAlchemyError, ValueError):
        raise HTTPException(503, "vpn_catalog_database_unavailable") from None
    async with sessions() as db:
        try:
            await bind_tenant_context(db, str(user.org_id))
            result = (await db.execute(_ROLE_CHECK, {"org_id": str(user.org_id)})).mappings().one()
            if set(result) != _POLICY_KEYS or not all(value is True for value in result.values()):
                raise HTTPException(503, "vpn_catalog_database_policy_unavailable")
        except (SQLAlchemyError, ValueError):
            raise HTTPException(503, "vpn_catalog_database_unavailable") from None
        yield db


async def close_catalog_database():
    global _engine, _sessions
    engine, _engine, _sessions = _engine, None, None
    if engine is not None:
        await engine.dispose()


register_shutdown("vpn_catalog_database", close_catalog_database)
