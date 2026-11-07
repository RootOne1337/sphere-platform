"""Track orchestration accounting separately from the immutable task outcome."""
import sqlalchemy as sa

from alembic import op

revision = "20260906_task_accounting"
down_revision = "20260906_device_refresh"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("orchestration_processed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("tasks", "orchestration_processed_at")
