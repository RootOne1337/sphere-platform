"""Persist pipeline ownership and step/child recovery checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_pipeline_lease"
down_revision = "20260920_pipeline_cancel"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pipeline_runs", sa.Column("current_child_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_pipeline_run_current_child", "pipeline_runs", "pipeline_runs",
                          ["current_child_run_id"], ["id"])
    op.add_column("pipeline_runs", sa.Column("execution_owner", sa.Uuid(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("execution_generation", sa.Integer(), server_default="0", nullable=False))
    op.add_column("pipeline_runs", sa.Column("execution_lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pipeline_runs", sa.Column("execution_phase", sa.String(16), server_default="ready", nullable=False))
    op.add_column("pipeline_runs", sa.Column("step_started_at", sa.DateTime(timezone=True), nullable=True))
    # Old current_step_id is not a checkpoint: an effect may have finished before
    # the worker disappeared. Preserve legacy work for review, not automatic replay.
    op.execute("UPDATE pipeline_runs SET execution_phase = 'unknown' "
               "WHERE status IN ('running', 'paused', 'waiting') "
               "OR (status = 'queued' AND started_at IS NOT NULL)")
    op.create_index("ix_pipeline_runs_recovery", "pipeline_runs", ["status", "execution_lease_until"])


def downgrade():
    op.drop_index("ix_pipeline_runs_recovery", table_name="pipeline_runs")
    op.drop_constraint("fk_pipeline_run_current_child", "pipeline_runs", type_="foreignkey")
    for column in ("step_started_at", "execution_phase", "execution_lease_until",
                   "execution_generation", "execution_owner", "current_child_run_id"):
        op.drop_column("pipeline_runs", column)
