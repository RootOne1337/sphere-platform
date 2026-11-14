"""Record trigger admission provenance on existing tenant-scoped runs."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_trigger_run_limits"
down_revision = "20261114_schedule_fire_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column("pipeline_runs", sa.Column("event_trigger_id", sa.Uuid(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trigger_event_id", sa.Uuid(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trigger_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_pipeline_runs_trigger_hour", "pipeline_runs",
        ["org_id", "event_trigger_id", "trigger_accepted_at"],
        postgresql_where=sa.text("event_trigger_id IS NOT NULL"),
    )
    op.create_index(
        "uq_pipeline_runs_trigger_event", "pipeline_runs",
        ["org_id", "event_trigger_id", "trigger_event_id"],
        unique=True, postgresql_where=sa.text("event_trigger_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_pipeline_runs_trigger_provenance", "pipeline_runs",
        "(event_trigger_id IS NULL AND trigger_event_id IS NULL AND trigger_accepted_at IS NULL) OR "
        "(event_trigger_id IS NOT NULL AND trigger_event_id IS NOT NULL AND trigger_accepted_at IS NOT NULL)",
    )


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_constraint("ck_pipeline_runs_trigger_provenance", "pipeline_runs", type_="check")
    op.drop_index("uq_pipeline_runs_trigger_event", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_trigger_hour", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "trigger_accepted_at")
    op.drop_column("pipeline_runs", "trigger_event_id")
    op.drop_column("pipeline_runs", "event_trigger_id")
