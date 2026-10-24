"""Bounded task dispatch discovery for explicitly authorized RLS workers."""

from alembic import op

revision = "20260921_task_dispatch"
down_revision = "20260921_pipeline_wait"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION sphere_auth.task_dispatch_work(work_kind text, after_device uuid)
        RETURNS TABLE(device_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
            SELECT DISTINCT t.device_id, t.org_id
            FROM public.tasks t JOIN public.devices d ON d.id=t.device_id AND d.org_id=t.org_id
            WHERE (after_device IS NULL OR t.device_id > after_device)
              AND ((work_kind='assign' AND d.is_active AND t.cancel_requested_at IS NULL
                    AND (t.status='queued' OR (t.status='assigned'
                         AND t.updated_at <= pg_catalog.statement_timestamp() - interval '30 seconds')))
                OR (work_kind='cancel' AND t.cancel_requested_at IS NOT NULL
                    AND t.status IN ('assigned','running')
                    AND (t.cancel_last_sent_at IS NULL
                         OR t.cancel_last_sent_at < pg_catalog.statement_timestamp() - interval '5 seconds')))
            ORDER BY t.device_id LIMIT 64
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.task_dispatch_work(text,uuid) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION sphere_auth.task_dispatch_work(text,uuid)")
