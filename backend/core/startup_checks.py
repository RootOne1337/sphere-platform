# backend/core/startup_checks.py
# F-02: Startup security invariant checks.
# Fail fast if the DB user running the backend is a PostgreSQL superuser or has BYPASSRLS.
# A superuser bypasses ALL Row Level Security policies → complete tenant boundary collapse.
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_SUPERUSER_CHECK_SQL = """
SELECT rolname, rolsuper, rolbypassrls
FROM pg_roles
WHERE rolname = current_user
"""


async def check_db_role_not_superuser() -> None:
    """
    Verify the current PostgreSQL session user is NOT a superuser and does NOT
    have BYPASSRLS. Either attribute disables Row Level Security completely.

    Raises RuntimeError on non-production environments (logged as warning).
    In ENVIRONMENT=production raises RuntimeError to block startup.
    """
    from backend.core.config import settings
    from backend.database.engine import engine

    async with engine.connect() as conn:
        result = await conn.execute(text(_SUPERUSER_CHECK_SQL))
        row = result.fetchone()

    if row is None:
        logger.warning("startup_check: could not determine DB role attributes")
        return

    rolname, rolsuper, rolbypassrls = row

    if rolsuper or rolbypassrls:
        msg = (
            f"SECURITY: DB user '{rolname}' has "
            f"{'SUPERUSER ' if rolsuper else ''}"
            f"{'BYPASSRLS' if rolbypassrls else ''}. "
            "Row Level Security policies will be BYPASSED — multi-tenant isolation is broken. "
            "Create a non-superuser app role. See infrastructure/postgres/rls_policies.sql."
        )
        if settings.ENVIRONMENT == "production":
            raise RuntimeError(msg)
        else:
            logger.warning("startup_check (non-production): %s", msg)
    else:
        logger.info("startup_check: DB role '%s' — RLS active (superuser=False, bypassrls=False)", rolname)
