"""Durable timeout stop intent and bounded watchdog discovery under RLS."""

import sqlalchemy as sa
from alembic import op

revision = "20260921_watchdog_stop"
down_revision = "20260921_schedule_work"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("timeout_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        CREATE FUNCTION sphere_auth.watchdog_work(stale_seconds integer, queued_minutes integer, after_task uuid)
        RETURNS TABLE(task_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
            SELECT id, org_id FROM public.tasks
            WHERE stale_seconds >= 0 AND queued_minutes >= 0 AND cancel_requested_at IS NULL
              AND (after_task IS NULL OR id > after_task)
              AND ((status='running' AND started_at IS NOT NULL
                    AND started_at + (timeout_seconds + stale_seconds)*interval '1 second'
                        <= pg_catalog.statement_timestamp())
                OR ((status IN ('queued','assigned') OR (status='running' AND started_at IS NULL))
                    AND created_at < pg_catalog.statement_timestamp() - queued_minutes*interval '1 minute'))
            ORDER BY id LIMIT 64
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.watchdog_work(integer,integer,uuid) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION sphere_auth.watchdog_work(integer,integer,uuid)")
    op.drop_column("tasks", "timeout_requested_at")
