"""Index tenant audit rows in the order used by the chronological cursor."""

from alembic import op

revision = "20261114_audit_cursor_idx"
down_revision = "20261114_webhook_outbox"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '20s'")
    op.create_index("ix_audit_logs_org_created_id", "audit_logs", ["org_id", "created_at", "id"])


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index("ix_audit_logs_org_created_id", table_name="audit_logs")
