"""Persist nested wait deadlines and discover only actionable waiting parents."""

import sqlalchemy as sa
from alembic import op

revision = "20260921_pipeline_wait"
down_revision = "20260921_pipeline_discovery"
branch_labels = None
depends_on = None


def _lookup(waiting_predicate):
    # CREATE OR REPLACE retains the explicitly granted ACL of AUD-133.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION sphere_auth.pipeline_work(work_kind text)
        RETURNS TABLE(run_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE STRICT SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
            SELECT r.id, r.org_id FROM public.pipeline_runs r
            WHERE (work_kind = 'queued' AND r.status = 'queued' AND r.cancel_requested_at IS NULL)
               OR (work_kind = 'cancel' AND r.cancel_requested_at IS NOT NULL
                   AND r.status IN ('queued','running','waiting','paused'))
               OR (work_kind = 'recovery' AND r.cancel_requested_at IS NULL
                   AND (r.status = 'running' OR (r.status='paused' AND r.execution_owner IS NOT NULL)
                        OR (r.status='waiting' AND ({waiting_predicate})))
                   AND (r.execution_owner IS NULL OR r.execution_lease_until IS NULL
                        OR r.execution_lease_until <= pg_catalog.statement_timestamp()))
            ORDER BY CASE WHEN work_kind='queued' THEN r.created_at ELSE r.updated_at END, r.id
            LIMIT 64
        $function$
    """)


def upgrade():
    op.add_column("pipeline_runs", sa.Column("wait_deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_pipeline_runs_wait_deadline", "pipeline_runs", ["status", "wait_deadline_at"])
    _lookup("""
        r.wait_deadline_at IS NULL OR r.wait_deadline_at <= pg_catalog.statement_timestamp()
        OR NOT EXISTS (
            SELECT 1 FROM public.pipeline_runs c WHERE c.id = r.current_child_run_id
            AND c.org_id = r.org_id AND c.device_id = r.device_id
            AND c.context->>'parent_run_id' = r.id::text
            AND c.status IN ('queued','running','waiting','paused')
        )
    """)


def downgrade():
    _lookup("TRUE")
    op.drop_index("ix_pipeline_runs_wait_deadline", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "wait_deadline_at")
