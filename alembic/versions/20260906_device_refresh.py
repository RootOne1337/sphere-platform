"""Persist revocable, rotating device refresh tokens separately from user tokens."""

import sqlalchemy as sa

from alembic import op

revision = "20260906_device_refresh"
down_revision = "20260309_pipeline_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("devices", sa.Column("refresh_token_hash", sa.String(64), nullable=True))
    op.add_column(
        "devices", sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint("uq_devices_refresh_token_hash", "devices", ["refresh_token_hash"])


def downgrade():
    op.drop_constraint("uq_devices_refresh_token_hash", "devices", type_="unique")
    op.drop_column("devices", "refresh_token_expires_at")
    op.drop_column("devices", "refresh_token_hash")
