"""Persist trigger causality and replay keys for device event ingress."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261114_trigger_causality"
down_revision = "20261114_trigger_run_limits"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column("tasks", sa.Column("pipeline_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_pipeline_run", "tasks", "pipeline_runs", ["pipeline_run_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_tasks_pipeline_run_id", "tasks", ["pipeline_run_id"])
    op.add_column("device_events", sa.Column("source_event_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_device_events_source", "device_events", ["org_id", "device_id", "source_event_id"],
        unique=True, postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    for table in ("device_events", "pipeline_runs"):
        op.add_column(table, sa.Column("trigger_root_event_id", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("trigger_path", JSONB(), nullable=True))
    op.create_index(
        "ix_pipeline_runs_trigger_root", "pipeline_runs", ["org_id", "trigger_root_event_id"],
        postgresql_where=sa.text("event_trigger_id IS NOT NULL"),
    )
    op.create_index(
        "ix_pipeline_runs_legacy_trigger_root", "pipeline_runs", ["org_id", "trigger_event_id"],
        postgresql_where=sa.text("event_trigger_id IS NOT NULL AND trigger_root_event_id IS NULL"),
    )
    op.create_index(
        "ix_pipeline_runs_current_task", "pipeline_runs", ["current_task_id"],
        postgresql_where=sa.text("current_task_id IS NOT NULL"),
    )


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_index("ix_pipeline_runs_current_task", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_legacy_trigger_root", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_trigger_root", table_name="pipeline_runs")
    for table in ("device_events", "pipeline_runs"):
        op.drop_column(table, "trigger_path")
        op.drop_column(table, "trigger_root_event_id")
    op.drop_index("uq_device_events_source", table_name="device_events")
    op.drop_column("device_events", "source_event_id")
    op.drop_index("ix_tasks_pipeline_run_id", table_name="tasks")
    op.drop_constraint("fk_tasks_pipeline_run", "tasks", type_="foreignkey")
    op.drop_column("tasks", "pipeline_run_id")
