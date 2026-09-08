"""Install complete tenant RLS policies, including associations and append-only audit.

Requires a separate non-owner runtime role and transaction-local tenant context.
This revision does not provision roles or make unscoped auth/background jobs safe.
"""

from alembic import op

revision = "20260908_tenant_policies"
down_revision = "20260906_account_ciphertext"
branch_labels = None
depends_on = None

# Frozen migration inventory. scripts/check_rls.py compares this with all models,
# including Table() associations, without importing the application or its secrets.
ORG_TABLES = (
    "account_sessions", "api_keys", "audit_logs", "device_events", "device_groups",
    "devices", "event_triggers", "game_accounts", "ldplayer_instances", "locations",
    "pipeline_batches", "pipeline_runs", "pipeline_settings", "pipelines",
    "refresh_tokens", "schedule_executions", "schedules", "script_versions", "scripts",
    "task_batches", "tasks", "users", "vpn_peers", "webhooks", "workstations",
)
ASSOCIATIONS = {
    "device_group_members": ("device_groups", "group_id"),
    "device_location_members": ("locations", "location_id"),
}
IDENTITY_TABLES = ("organizations",)

# Cast the setting, not the indexed org_id column. Missing/empty context denies
# access; a malformed UUID raises before any write, also failing closed.
TENANT = "NULLIF(pg_catalog.current_setting('app.current_org_id', true), '')::uuid"


def upgrade():
    predicates = {table: f"org_id = {TENANT}" for table in ORG_TABLES}
    predicates["organizations"] = f"id = {TENANT}"
    for table, (parent, key) in ASSOCIATIONS.items():
        # Foreign-key checks bypass RLS: protect BOTH association endpoints directly.
        # PostgreSQL binds these table references when CREATE POLICY executes.
        predicates[table] = (
            f"EXISTS (SELECT 1 FROM devices d WHERE d.id = {table}.device_id AND d.org_id = {TENANT}) "
            f"AND EXISTS (SELECT 1 FROM {parent} p WHERE p.id = {table}.{key} AND p.org_id = {TENANT})"
        )

    for table, predicate in predicates.items():
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        # Replace only repository-owned legacy policies. Preserve operator policies.
        # A restrictive boundary prevents any permissive policy from OR-ing away
        # tenant checks; pre-existing restrictive operator rules remain effective.
        legacy = [f"{table}_org_isolation", f"{table}_tenant_isolation", f"{table}_insert"]
        if table == "audit_logs":
            legacy += ["audit_insert_only", "audit_no_update", "audit_no_delete"]
        for name in legacy:
            op.execute(f'DROP POLICY IF EXISTS "{name}" ON "{table}"')
        op.execute(
            f'CREATE POLICY sphere_tenant_boundary ON "{table}" AS RESTRICTIVE '
            f'FOR ALL USING ({predicate}) WITH CHECK ({predicate})'
        )
        if table == "audit_logs":
            op.execute(f'CREATE POLICY sphere_audit_read ON "{table}" FOR SELECT USING ({predicate})')
            op.execute(f'CREATE POLICY sphere_audit_insert ON "{table}" FOR INSERT WITH CHECK ({predicate})')
            op.execute(f'CREATE POLICY sphere_audit_no_update ON "{table}" AS RESTRICTIVE FOR UPDATE USING (false)')
            op.execute(f'CREATE POLICY sphere_audit_no_delete ON "{table}" AS RESTRICTIVE FOR DELETE USING (false)')
        else:
            op.execute(
                f'CREATE POLICY sphere_tenant_access ON "{table}" '
                f'FOR ALL USING ({predicate}) WITH CHECK ({predicate})'
            )


def downgrade():
    # Never silently restore unprotected associations/settings or discard tenant
    # policies. A rollback needs an explicitly reviewed forward security migration.
    raise RuntimeError("Tenant policy downgrade is blocked; use a reviewed forward migration")
