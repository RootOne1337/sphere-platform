"""Keep pipeline cancellation pending while its child task still executes."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_pipeline_cancel"
down_revision = "20260920_task_cancel_intent"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pipeline_runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("pipeline_runs", "cancel_requested_at")
