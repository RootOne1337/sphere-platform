"""Narrow, explicitly granted pipeline work discovery for RLS runtime workers."""

from alembic import op

revision = "20260921_pipeline_discovery"
down_revision = "20260920_batch_plan"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION sphere_auth.pipeline_work(work_kind text)
        RETURNS TABLE(run_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE STRICT SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
            SELECT id, org_id FROM public.pipeline_runs
            WHERE (work_kind = 'queued' AND status = 'queued' AND cancel_requested_at IS NULL)
               OR (work_kind = 'cancel' AND cancel_requested_at IS NOT NULL
                   AND status IN ('queued','running','waiting','paused'))
               OR (work_kind = 'recovery' AND cancel_requested_at IS NULL
                   AND (status IN ('running','waiting') OR (status='paused' AND execution_owner IS NOT NULL))
                   AND (execution_owner IS NULL OR execution_lease_until IS NULL
                        OR execution_lease_until <= pg_catalog.statement_timestamp()))
            ORDER BY CASE WHEN work_kind='queued' THEN created_at ELSE updated_at END, id
            LIMIT 64
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.pipeline_work(text) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION sphere_auth.pipeline_work(text)")
