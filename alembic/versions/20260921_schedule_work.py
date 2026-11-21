"""Bounded due schedule discovery for explicitly authorized RLS workers."""

from alembic import op

revision = "20260921_schedule_work"
down_revision = "20260921_task_dispatch"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION sphere_auth.schedule_work(after_schedule uuid)
        RETURNS TABLE(schedule_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
            SELECT id, org_id FROM public.schedules
            WHERE is_active AND next_fire_at <= pg_catalog.statement_timestamp()
              AND (after_schedule IS NULL OR id > after_schedule)
            ORDER BY id LIMIT 50
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.schedule_work(uuid) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION sphere_auth.schedule_work(uuid)")
