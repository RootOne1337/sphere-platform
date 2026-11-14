"""Persist tenant application bindings, policies, and durable automation receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_automation_profiles"
down_revision = "20261114_application_profiles"
branch_labels = None
depends_on = None

ORG_TABLES = ("application_automation_policies",)
IDENTITY_TABLES = ()
ASSOCIATIONS = {}


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_unique_constraint("uq_application_profile_org_id", "application_profiles", ["org_id", "id"])
    op.create_unique_constraint("uq_script_org_id", "scripts", ["org_id", "id"])

    op.add_column("devices", sa.Column("application_profile_id", sa.Uuid(), nullable=True))
    op.add_column("devices", sa.Column("application_server_key", sa.String(64), nullable=True))
    op.add_column("devices", sa.Column("application_binding_revision", sa.Integer(), server_default="0", nullable=False))
    op.create_foreign_key("fk_device_application_profile", "devices", "application_profiles",
                          ["org_id", "application_profile_id"], ["org_id", "id"])
    op.create_check_constraint("ck_device_application_binding", "devices",
                               "(application_profile_id IS NULL) = (application_server_key IS NULL) "
                               "AND application_binding_revision >= 0")
    op.create_index("ix_devices_org_application_profile", "devices", ["org_id", "application_profile_id"],
                    postgresql_where=sa.text("application_profile_id IS NOT NULL"))

    table = "application_automation_policies"
    op.create_table(
        table,
        sa.Column("org_id", sa.Uuid(), primary_key=True),
        sa.Column("application_profile_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("registration_enabled", sa.Boolean(), nullable=False),
        sa.Column("registration_script_id", sa.Uuid(), nullable=True),
        sa.Column("max_concurrent_registrations", sa.Integer(), nullable=False),
        sa.Column("registration_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("farming_enabled", sa.Boolean(), nullable=False),
        sa.Column("farming_script_id", sa.Uuid(), nullable=True),
        sa.Column("max_concurrent_farming", sa.Integer(), nullable=False),
        sa.Column("farming_session_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("default_target_level", sa.Integer(), nullable=False),
        sa.Column("cooldown_between_sessions_minutes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["org_id", "application_profile_id"], ["application_profiles.org_id", "application_profiles.id"],
                                name="fk_automation_policy_profile"),
        sa.ForeignKeyConstraint(["org_id", "registration_script_id"], ["scripts.org_id", "scripts.id"],
                                name="fk_automation_policy_registration_script"),
        sa.ForeignKeyConstraint(["org_id", "farming_script_id"], ["scripts.org_id", "scripts.id"],
                                name="fk_automation_policy_farming_script"),
        sa.CheckConstraint("revision >= 1", name="ck_automation_policy_revision"),
        sa.CheckConstraint("(NOT registration_enabled OR registration_script_id IS NOT NULL) "
                           "AND (NOT farming_enabled OR farming_script_id IS NOT NULL)",
                           name="ck_automation_policy_enabled_script"),
        sa.CheckConstraint("max_concurrent_registrations BETWEEN 1 AND 100 "
                           "AND registration_timeout_seconds BETWEEN 60 AND 7200 "
                           "AND max_concurrent_farming BETWEEN 1 AND 500 "
                           "AND farming_session_duration_seconds BETWEEN 300 AND 86400 "
                           "AND default_target_level BETWEEN 1 AND 100 "
                           "AND cooldown_between_sessions_minutes BETWEEN 0 AND 1440",
                           name="ck_automation_policy_limits"),
    )
    predicate = "org_id = NULLIF(pg_catalog.current_setting('app.current_org_id', true), '')::uuid"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute(f"CREATE POLICY sphere_tenant_boundary ON {table} AS RESTRICTIVE FOR ALL USING ({predicate}) WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY sphere_automation_read ON {table} FOR SELECT USING ({predicate})")
    op.execute(f"CREATE POLICY sphere_automation_create ON {table} FOR INSERT WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY sphere_automation_update ON {table} FOR UPDATE USING ({predicate}) WITH CHECK ({predicate})")

    op.add_column("tasks", sa.Column("orchestration_kind", sa.String(12), nullable=True))
    op.add_column("tasks", sa.Column("orchestration_profile_id", sa.Uuid(), nullable=True))
    op.add_column("tasks", sa.Column("orchestration_cooldown_minutes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_task_orchestration_receipt", "tasks",
        "(orchestration_kind IS NULL AND orchestration_profile_id IS NULL AND orchestration_cooldown_minutes IS NULL) OR "
        "(orchestration_kind IS NOT NULL AND ((orchestration_kind = 'register' AND orchestration_cooldown_minutes IS NULL) OR "
        "(orchestration_kind = 'farm' AND orchestration_cooldown_minutes IS NOT NULL AND orchestration_cooldown_minutes BETWEEN 0 AND 1440)))",
    )
    op.create_index("ix_tasks_unprocessed_orchestration", "tasks", ["org_id", "id"],
                    postgresql_where=sa.text("orchestration_kind IS NOT NULL AND orchestration_processed_at IS NULL "
                                            "AND status IN ('completed', 'failed', 'timeout', 'cancelled')"))
    op.execute("""
        CREATE FUNCTION sphere_auth.orchestration_work(after_org uuid)
        RETURNS TABLE(tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
            SELECT work.org_id FROM (
                SELECT org_id FROM public.pipeline_settings WHERE orchestration_enabled
                UNION
                SELECT org_id FROM public.application_automation_policies WHERE registration_enabled OR farming_enabled
                UNION
                SELECT org_id FROM public.tasks
                WHERE orchestration_kind IS NOT NULL AND orchestration_processed_at IS NULL
                  AND status IN ('completed', 'failed', 'timeout', 'cancelled')
            ) work
            WHERE after_org IS NULL OR work.org_id > after_org
            ORDER BY work.org_id LIMIT 64
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.orchestration_work(uuid) FROM PUBLIC")


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("DROP FUNCTION sphere_auth.orchestration_work(uuid)")
    op.drop_index("ix_tasks_unprocessed_orchestration", table_name="tasks")
    op.drop_constraint("ck_task_orchestration_receipt", "tasks", type_="check")
    for column in ("orchestration_cooldown_minutes", "orchestration_profile_id", "orchestration_kind"):
        op.drop_column("tasks", column)
    op.drop_table("application_automation_policies")
    op.drop_index("ix_devices_org_application_profile", table_name="devices")
    op.drop_constraint("ck_device_application_binding", "devices", type_="check")
    op.drop_constraint("fk_device_application_profile", "devices", type_="foreignkey")
    for column in ("application_binding_revision", "application_server_key", "application_profile_id"):
        op.drop_column("devices", column)
    op.drop_constraint("uq_script_org_id", "scripts", type_="unique")
    op.drop_constraint("uq_application_profile_org_id", "application_profiles", type_="unique")
