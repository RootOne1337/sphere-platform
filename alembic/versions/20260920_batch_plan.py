"""Persist batch wave plans and atomic admission progress."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260920_batch_plan"
down_revision = "20260920_pipeline_lease"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_batches", sa.Column("wave_plan", postgresql.JSONB(), nullable=True))
    op.add_column("task_batches", sa.Column("script_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_batch_script_version", "task_batches", "script_versions", ["script_version_id"], ["id"])
    op.add_column("task_batches", sa.Column("next_wave_index", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("task_batches", sa.Column("next_wave_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("task_batches", sa.Column("admission_state", sa.String(24), nullable=False, server_default="legacy_unknown"))
    op.add_column("task_batches", sa.Column("admission_receipts", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.create_index("ix_task_batches_admission", "task_batches", ["admission_state", "next_wave_at"])
    op.execute("""
        CREATE FUNCTION sphere_auth.due_batch_admissions() RETURNS TABLE(batch_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
            SELECT id, org_id FROM public.task_batches
            WHERE admission_state = 'pending' AND status IN ('pending', 'running')
              AND (next_wave_at IS NULL OR next_wave_at <= pg_catalog.statement_timestamp())
            ORDER BY next_wave_at ASC NULLS FIRST, created_at, id LIMIT 32
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.due_batch_admissions() FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION sphere_auth.due_batch_admissions()")
    op.drop_index("ix_task_batches_admission", table_name="task_batches")
    op.drop_constraint("fk_batch_script_version", "task_batches", type_="foreignkey")
    for column in ("admission_receipts", "admission_state", "next_wave_at", "next_wave_index", "script_version_id", "wave_plan"):
        op.drop_column("task_batches", column)
