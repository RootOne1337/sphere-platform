"""TZ-00 baseline: initial schema

Revision ID: 0001_baseline
Revises: 
Create Date: 2025-01-01 00:00:00.000000

Это первая миграция-baseline проекта.
Все последующие миграции от TZ-01 до TZ-11 добавляют свои head-ы и
сливаются командой `make alembic-merge-heads` перед релизом.

Порядок создания таблиц важен из-за FK:
  1. organizations (нет FK)
  2. users (→ organizations)
  3. api_keys (→ organizations, users)
  4. refresh_tokens (→ organizations, users)
  5. audit_logs (→ organizations, users)
  6. workstations (→ organizations)
  7. device_groups (→ organizations)
  8. devices (→ organizations)
  9. device_group_members (→ devices, device_groups)
  10. ldplayer_instances (→ organizations, workstations, devices)
  11. scripts (→ organizations)
  12. script_versions (→ organizations, scripts, users)
  13. scripts.current_version_id FK (ALTER TABLE — circular FK)
  14. task_batches (→ organizations, scripts, users)
  15. tasks (→ organizations, devices, scripts, task_batches, script_versions)
  16. vpn_peers (→ organizations, devices)
  17. webhooks (→ organizations)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = "main"
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === ENUMs ===
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE device_status_enum AS ENUM ('online', 'offline', 'busy', 'error', 'maintenance');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE task_status_enum AS ENUM ('queued', 'assigned', 'running', 'completed', 'failed', 'timeout', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE task_batch_status_enum AS ENUM ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # === organizations ===
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("meta", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # === users ===
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mfa_secret", sa.String(32), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # === api_keys ===
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="user"),
        sa.Column("permissions", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    # === refresh_tokens ===
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_revoked", "refresh_tokens", ["revoked"])

    # === audit_logs ===
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("meta", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
    op.create_index("ix_audit_logs_resource_id", "audit_logs", ["resource_id"])

    # === workstations ===
    op.create_table(
        "workstations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("os_version", sa.String(255), nullable=True),
        sa.Column("agent_version", sa.String(50), nullable=True),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_heartbeat_at", sa.String(50), nullable=True),
        sa.Column("meta", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workstations_org_id", "workstations", ["org_id"])

    # === device_groups ===
    op.create_table(
        "device_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filter_criteria", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_groups_org_id", "device_groups", ["org_id"])

    # === devices ===
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("serial", sa.String(100), nullable=True),
        sa.Column("android_version", sa.String(50), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_status", postgresql.ENUM("online", "offline", "busy", "error", "maintenance", name="device_status_enum", create_type=False), nullable=False, server_default="offline"),
        sa.Column("meta", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_devices_org_id", "devices", ["org_id"])
    op.create_index("ix_devices_serial", "devices", ["serial"])

    # === device_group_members (M2M) ===
    op.create_table(
        "device_group_members",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["device_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "group_id"),
    )

    # === ldplayer_instances ===
    op.create_table(
        "ldplayer_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workstation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("instance_index", sa.Integer(), nullable=False),
        sa.Column("android_serial", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="stopped"),
        sa.Column("meta", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["workstation_id"], ["workstations.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ldplayer_instances_workstation_id", "ldplayer_instances", ["workstation_id"])
    op.create_index("ix_ldplayer_instances_device_id", "ldplayer_instances", ["device_id"])

    # === scripts (без current_version_id — circular FK добавляется после script_versions) ===
    op.create_table(
        "scripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scripts_org_id", "scripts", ["org_id"])

    # === script_versions ===
    op.create_table(
        "script_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("script_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dag", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_script_versions_script_id", "script_versions", ["script_id"])

    # Circular FK: scripts.current_version_id → script_versions.id
    op.create_foreign_key(
        "fk_script_current_version",
        "scripts",
        "script_versions",
        ["current_version_id"],
        ["id"],
        use_alter=True,
    )

    # === task_batches ===
    op.create_table(
        "task_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("script_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", postgresql.ENUM("pending", "running", "completed", "partial", "failed", "cancelled", name="task_batch_status_enum", create_type=False), nullable=False, server_default="pending"),
        sa.Column("wave_config", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_batches_org_id", "task_batches", ["org_id"])
    op.create_index("ix_task_batches_status", "task_batches", ["status"])

    # === tasks ===
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("script_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("script_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", postgresql.ENUM("queued", "assigned", "running", "completed", "failed", "timeout", "cancelled", name="task_status_enum", create_type=False), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("input_params", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.String(2048), nullable=True),
        sa.Column("wave_index", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["task_batches.id"]),
        sa.ForeignKeyConstraint(["script_version_id"], ["script_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_org_id", "tasks", ["org_id"])
    op.create_index("ix_tasks_device_id", "tasks", ["device_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_batch_id", "tasks", ["batch_id"])

    # === vpn_peers ===
    op.create_table(
        "vpn_peers",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_key", sa.String(44), nullable=False),
        sa.Column("private_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column("preshared_key_enc", sa.LargeBinary(), nullable=True),
        sa.Column("awg_jc", sa.Integer(), nullable=True),
        sa.Column("awg_jmin", sa.Integer(), nullable=True),
        sa.Column("awg_jmax", sa.Integer(), nullable=True),
        sa.Column("awg_s1", sa.Integer(), nullable=True),
        sa.Column("awg_s2", sa.Integer(), nullable=True),
        sa.Column("awg_h1", sa.Integer(), nullable=True),
        sa.Column("awg_h2", sa.Integer(), nullable=True),
        sa.Column("awg_h3", sa.Integer(), nullable=True),
        sa.Column("awg_h4", sa.Integer(), nullable=True),
        sa.Column("tunnel_ip", sa.String(45), nullable=True),
        sa.Column("allowed_ips", sa.String(255), nullable=False, server_default="0.0.0.0/0"),
        sa.Column("endpoint", sa.String(255), nullable=True),
        sa.Column("listen_port", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ASSIGNED"),
        sa.Column("last_handshake_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )
    op.create_index("ix_vpn_peers_org_id", "vpn_peers", ["org_id"])

    # === webhooks ===
    op.create_table(
        "webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=True),
        sa.Column("events", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("tags", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhooks_org_id", "webhooks", ["org_id"])

    # === RLS activation (выполняется после init.sql, но здесь для Alembic-complete) ===
    # RLS-политики применяются отдельно через infrastructure/postgres/rls_policies.sql
    # Здесь только включаем RLS на уровне таблиц
    for table in [
        "organizations", "users", "api_keys", "refresh_tokens",
        "workstations", "device_groups", "devices", "ldplayer_instances",
        "scripts", "script_versions", "task_batches", "tasks",
        "vpn_peers", "webhooks",
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # audit_logs — только INSERT разрешён (политики в audit_log_policies.sql)
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Снимаем RLS
    for table in [
        "webhooks", "vpn_peers", "tasks", "task_batches",
        "script_versions", "scripts", "ldplayer_instances", "devices",
        "device_groups", "workstations", "audit_logs", "refresh_tokens",
        "api_keys", "users", "organizations",
    ]:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Circular FK сначала
    op.drop_constraint("fk_script_current_version", "scripts", type_="foreignkey")

    op.drop_table("webhooks")
    op.drop_table("vpn_peers")
    op.drop_table("tasks")
    op.drop_table("task_batches")
    op.drop_table("script_versions")
    op.drop_table("scripts")
    op.drop_table("ldplayer_instances")
    op.drop_table("device_group_members")
    op.drop_table("devices")
    op.drop_table("device_groups")
    op.drop_table("workstations")
    op.drop_table("audit_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("organizations")

    op.execute("DROP TYPE IF EXISTS task_batch_status_enum")
    op.execute("DROP TYPE IF EXISTS task_status_enum")
    op.execute("DROP TYPE IF EXISTS device_status_enum")
