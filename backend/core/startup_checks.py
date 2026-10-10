# Production database-role prerequisites. These checks do not certify policy semantics.
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_ROLE_SQL = """
SELECT rolname, rolsuper, rolbypassrls
FROM pg_roles WHERE rolname = current_user
"""
_MEMBERSHIP_SQL = """
SELECT rolname FROM pg_roles
WHERE (rolsuper OR rolbypassrls) AND pg_has_role(current_user, oid, 'MEMBER')
"""
_TABLE_SQL = """
SELECT n.nspname AS schema_name, c.relname AS table_name,
       pg_has_role(current_user, c.relowner, 'MEMBER') AS owns_table,
       row_security_active(c.oid) AS rls_active,
       has_table_privilege(current_user, c.oid, 'TRUNCATE') AS can_truncate,
       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policy_count
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND pg_table_is_visible(c.oid)
  AND c.relname = ANY(:tables)
ORDER BY n.nspname, c.relname
"""


def _reject_unsafe(message: str) -> None:
    from backend.core.config import settings

    if settings.ENVIRONMENT == "production":
        raise RuntimeError(message)
    logger.warning("startup_check (non-production): %s", message)


async def check_db_role_not_superuser() -> None:
    """Reject owner/membership/TRUNCATE escapes and absent RLS prerequisites in production.

    The name is retained for existing lifespan callers. Development warns instead.
    Actual policy predicates, authentication bootstrap and tenant transaction
    propagation require their own runtime tests; a role-attribute check is not proof.
    """
    import backend.models  # noqa: F401 -- load the complete mapped table inventory
    from backend.database.engine import Base, engine

    async with engine.connect() as conn:
        row = (await conn.execute(text(_ROLE_SQL))).fetchone()
        if row is None:
            _reject_unsafe("SECURITY: cannot determine the current database role")
            return
        rolname, rolsuper, rolbypassrls = row
        if rolsuper or rolbypassrls:
            _reject_unsafe(
                f"SECURITY: DB role '{rolname}' has SUPERUSER or BYPASSRLS; "
                "use a separate non-owner runtime role with tenant policies."
            )
            return

        privileged = (await conn.execute(text(_MEMBERSHIP_SQL))).scalars().all()
        rows = (await conn.execute(text(_TABLE_SQL), {
            "tables": sorted(table.name for table in Base.metadata.tables.values()),
        })).mappings().all()

    problems = []
    if privileged:
        problems.append("membership in privileged roles: " + ", ".join(privileged))
    if not rows:
        problems.append("no mapped application tables are visible in search_path")
    for table in rows:
        reasons = []
        if table["owns_table"]:
            # FORCE cannot make ownership safe: an owner can disable it or change policies.
            reasons.append("table owner or owner-role member")
        if not table["rls_active"]:
            reasons.append("RLS not active for this role")
        if not table["policy_count"]:
            reasons.append("no RLS policies installed")
        if table["can_truncate"]:
            # TRUNCATE is outside PostgreSQL row-security checks.
            reasons.append("TRUNCATE privilege")
        if reasons:
            problems.append(f"{table['schema_name']}.{table['table_name']}: " + ", ".join(reasons))
    if problems:
        _reject_unsafe(
            f"SECURITY: DB role '{rolname}' is unsafe for runtime: " + "; ".join(problems)
            + ". Separate migration ownership from runtime CRUD grants and apply the RLS migration."
        )
        return
    logger.info("startup_check: DB role '%s' passed runtime role/RLS prerequisites", rolname)
