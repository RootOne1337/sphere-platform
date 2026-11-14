"""Durable tenant webhook delivery receipts and bounded worker discovery."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261114_webhook_outbox"
down_revision = "20261114_trigger_causality"
branch_labels = None
depends_on = None

ORG_TABLES = ("webhook_deliveries",)
IDENTITY_TABLES = ()
ASSOCIATIONS = {}


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("webhook_id", sa.Uuid()),
        sa.Column("subject_id", sa.Uuid()),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("destination", sa.Text()),
        sa.Column("body", sa.LargeBinary()),
        sa.Column("body_bytes", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(71)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("replay_count", sa.Integer(), nullable=False),
        sa.Column("attempts", JSONB(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("claim_token", sa.Uuid()),
        sa.Column("last_http_status", sa.Integer()),
        sa.Column("last_error", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'sending', 'delivered', 'dead')", name="ck_webhook_delivery_status"),
        sa.CheckConstraint("source IN ('task_callback', 'subscription')", name="ck_webhook_delivery_source"),
        sa.CheckConstraint(
            "replay_count BETWEEN 0 AND 1 AND attempts_count BETWEEN 0 AND max_attempts "
            "AND max_attempts BETWEEN 4 AND 8", name="ck_webhook_delivery_budget",
        ),
        sa.CheckConstraint("body_bytes BETWEEN 0 AND 262144", name="ck_webhook_delivery_body_size"),
    )
    op.create_index("ix_webhook_deliveries_org_history", "webhook_deliveries", ["org_id", "created_at", "id"])
    op.create_index("ix_webhook_deliveries_due", "webhook_deliveries", ["status", "next_attempt_at", "id"])
    op.create_index("ix_webhook_deliveries_expiry", "webhook_deliveries", ["status", "updated_at", "id"])
    predicate = "org_id = NULLIF(pg_catalog.current_setting('app.current_org_id', true), '')::uuid"
    op.execute("ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE webhook_deliveries FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE webhook_deliveries FROM PUBLIC")
    op.execute(
        "CREATE POLICY sphere_tenant_boundary ON webhook_deliveries AS RESTRICTIVE "
        f"FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(
        "CREATE POLICY sphere_webhook_delivery_access ON webhook_deliveries "
        f"FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute("""
        CREATE FUNCTION sphere_auth.webhook_work(expired boolean)
        RETURNS TABLE(delivery_id uuid, tenant_id uuid)
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp SET row_security = off
        AS $function$
        BEGIN
            IF expired THEN
                RETURN QUERY SELECT d.id, d.org_id FROM public.webhook_deliveries d
                WHERE d.status IN ('delivered', 'dead')
                  AND d.updated_at <= pg_catalog.statement_timestamp() - interval '30 days'
                ORDER BY d.updated_at, d.id LIMIT 32;
            ELSE
                RETURN QUERY SELECT d.id, d.org_id FROM public.webhook_deliveries d
                WHERE d.status IN ('pending', 'sending')
                  AND d.next_attempt_at <= pg_catalog.statement_timestamp()
                ORDER BY d.next_attempt_at, d.id LIMIT 32;
            END IF;
        END
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.webhook_work(boolean) FROM PUBLIC")


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP FUNCTION sphere_auth.webhook_work(boolean)")
    op.drop_table("webhook_deliveries")
