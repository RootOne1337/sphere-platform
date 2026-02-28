"""TZ-12: pipelines, pipeline_runs, pipeline_batches, schedules, schedule_executions

Revision ID: 20260224_tz12_orchestrator
Revises: ac22b0d428d0
Create Date: 2026-02-24 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260224_tz12_orchestrator"
down_revision: Union[str, None] = "ac22b0d428d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enum типы ────────────────────────────────────────────────────────────
    pipeline_run_status_enum = postgresql.ENUM(
        "queued", "running", "paused", "waiting",
        "completed", "failed", "cancelled", "timed_out",
        name="pipeline_run_status_enum",
        create_type=False,
    )
    pipeline_run_status_enum.create(op.get_bind(), checkfirst=True)

    schedule_target_type_enum = postgresql.ENUM(
        "script", "pipeline",
        name="schedule_target_type_enum",
        create_type=False,
    )
    schedule_target_type_enum.create(op.get_bind(), checkfirst=True)

    schedule_conflict_policy_enum = postgresql.ENUM(
        "skip", "queue", "cancel",
        name="schedule_conflict_policy_enum",
        create_type=False,
    )
    schedule_conflict_policy_enum.create(op.get_bind(), checkfirst=True)

    schedule_execution_status_enum = postgresql.ENUM(
        "triggered", "skipped", "completed", "partial", "failed",
        name="schedule_execution_status_enum",
        create_type=False,
    )
    schedule_execution_status_enum.create(op.get_bind(), checkfirst=True)

    # ── pipelines ────────────────────────────────────────────────────────────
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("input_schema", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("global_timeout_ms", sa.Integer(), nullable=False, server_default="86400000"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipelines_org_id", "pipelines", ["org_id"])
    op.create_index("ix_pipelines_is_active", "pipelines", ["is_active"])
    op.create_index("ix_pipelines_org_active", "pipelines", ["org_id", "is_active"])

    # ── pipeline_runs ────────────────────────────────────────────────────────
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            pipeline_run_status_enum,
            nullable=False,
            server_default="queued",
        ),
        sa.Column("current_step_id", sa.String(length=128), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("input_params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("steps_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("step_logs", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("current_task_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["current_task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_runs_org_id", "pipeline_runs", ["org_id"])
    op.create_index("ix_pipeline_runs_pipeline_id", "pipeline_runs", ["pipeline_id"])
    op.create_index("ix_pipeline_runs_device_id", "pipeline_runs", ["device_id"])
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])
    op.create_index("ix_pipeline_runs_device_status", "pipeline_runs", ["device_id", "status"])
    op.create_index("ix_pipeline_runs_org_status", "pipeline_runs", ["org_id", "status"])

    # ── pipeline_batches ─────────────────────────────────────────────────────
    op.create_table(
        "pipeline_batches",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wave_config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_batches_org_id", "pipeline_batches", ["org_id"])
    op.create_index("ix_pipeline_batches_pipeline_id", "pipeline_batches", ["pipeline_id"])
    op.create_index("ix_pipeline_batches_status", "pipeline_batches", ["status"])

    # ── schedules ────────────────────────────────────────────────────────────
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cron_expression", sa.String(length=128), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("one_shot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("target_type", schedule_target_type_enum, nullable=False),
        sa.Column("script_id", sa.Uuid(), nullable=True),
        sa.Column("pipeline_id", sa.Uuid(), nullable=True),
        sa.Column("input_params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("device_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("device_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("only_online", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("conflict_policy", schedule_conflict_policy_enum, nullable=False, server_default="skip"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_runs", sa.Integer(), nullable=True),
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"]),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["device_groups.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(cron_expression IS NOT NULL) OR (interval_seconds IS NOT NULL) OR (one_shot_at IS NOT NULL)",
            name="ck_schedules_has_trigger",
        ),
    )
    op.create_index("ix_schedules_org_id", "schedules", ["org_id"])
    op.create_index("ix_schedules_is_active", "schedules", ["is_active"])
    op.create_index("ix_schedules_next_fire_at", "schedules", ["next_fire_at"])
    op.create_index("ix_schedules_next_fire", "schedules", ["is_active", "next_fire_at"])
    op.create_index("ix_schedules_org_active", "schedules", ["org_id", "is_active"])

    # ── schedule_executions ──────────────────────────────────────────────────
    op.create_table(
        "schedule_executions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("status", schedule_execution_status_enum, nullable=False, server_default="triggered"),
        sa.Column("fire_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("devices_targeted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("pipeline_batch_id", sa.Uuid(), nullable=True),
        sa.Column("skip_reason", sa.String(length=512), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_executions_schedule_id", "schedule_executions", ["schedule_id"])
    op.create_index("ix_schedule_executions_schedule_fire", "schedule_executions", ["schedule_id", "fire_time"])

    # ── RLS политики ─────────────────────────────────────────────────────────
    for table in ("pipelines", "pipeline_runs", "pipeline_batches", "schedules", "schedule_executions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} "
            f"USING (org_id::text = current_setting('app.current_org_id', true))"
        )


def downgrade() -> None:
    # Удалить RLS
    for table in ("schedule_executions", "schedules", "pipeline_batches", "pipeline_runs", "pipelines"):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Удалить таблицы
    op.drop_table("schedule_executions")
    op.drop_table("schedules")
    op.drop_table("pipeline_batches")
    op.drop_table("pipeline_runs")
    op.drop_table("pipelines")

    # Удалить enum типы
    op.execute("DROP TYPE IF EXISTS schedule_execution_status_enum")
    op.execute("DROP TYPE IF EXISTS schedule_conflict_policy_enum")
    op.execute("DROP TYPE IF EXISTS schedule_target_type_enum")
    op.execute("DROP TYPE IF EXISTS pipeline_run_status_enum")
