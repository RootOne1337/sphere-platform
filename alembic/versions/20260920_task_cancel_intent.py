"""Durable task cancellation without conflating publication with completion."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_task_cancel_intent"
down_revision = "20260910_device_refresh_retry"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("cancel_last_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_cancel_requested_at", "tasks", ["cancel_requested_at"])


def downgrade():
    op.drop_index("ix_tasks_cancel_requested_at", table_name="tasks")
    op.drop_column("tasks", "cancel_last_sent_at")
    op.drop_column("tasks", "cancel_requested_at")
