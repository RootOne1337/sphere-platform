"""Add nullable, paired metadata for source-free script catalog reads."""

import sqlalchemy as sa
from alembic import op

revision = "20261006_script_catalog_metadata"
down_revision = "20260921_watchdog_stop"
branch_labels = None
depends_on = None


def upgrade():
    # No source rewrite/backfill: older writers may still insert a NULL pair.
    op.add_column("script_versions", sa.Column("dag_hash", sa.String(64), nullable=True))
    op.add_column("script_versions", sa.Column("node_count", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_script_versions_dag_metadata_pair", "script_versions",
        "(dag_hash IS NULL) = (node_count IS NULL)",
    )
    op.create_check_constraint(
        "ck_script_versions_dag_hash", "script_versions",
        "dag_hash IS NULL OR dag_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_script_versions_node_count", "script_versions", "node_count >= 0",
    )


def downgrade():
    op.drop_constraint("ck_script_versions_node_count", "script_versions", type_="check")
    op.drop_constraint("ck_script_versions_dag_hash", "script_versions", type_="check")
    op.drop_constraint("ck_script_versions_dag_metadata_pair", "script_versions", type_="check")
    op.drop_column("script_versions", "node_count")
    op.drop_column("script_versions", "dag_hash")
