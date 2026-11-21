"""Persist replay keys for explicitly requested schedule firings."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_schedule_fire_keys"
down_revision = "20261114_automation_profiles"
branch_labels = None
depends_on = None

ORG_TABLES = ("schedule_fire_requests",)
IDENTITY_TABLES = ()
ASSOCIATIONS = {}


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_unique_constraint("uq_schedule_org_id", "schedules", ["org_id", "id"])
    op.create_table(
        "schedule_fire_requests",
        sa.Column("org_id", sa.Uuid(), primary_key=True),
        sa.Column("schedule_id", sa.Uuid(), primary_key=True),
        sa.Column("request_key", sa.Uuid(), primary_key=True),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id", "schedule_id"], ["schedules.org_id", "schedules.id"],
            ondelete="CASCADE", name="fk_schedule_fire_request_owner",
        ),
    )
    op.create_index("ix_schedule_fire_requests_expiry", "schedule_fire_requests", ["org_id", "schedule_id", "expires_at"])
    predicate = "org_id = NULLIF(pg_catalog.current_setting('app.current_org_id', true), '')::uuid"
    op.execute("ALTER TABLE schedule_fire_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE schedule_fire_requests FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE schedule_fire_requests FROM PUBLIC")
    op.execute(f"CREATE POLICY sphere_tenant_boundary ON schedule_fire_requests AS RESTRICTIVE FOR ALL USING ({predicate}) WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY sphere_schedule_fire_read ON schedule_fire_requests FOR SELECT USING ({predicate})")
    op.execute(f"CREATE POLICY sphere_schedule_fire_create ON schedule_fire_requests FOR INSERT WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY sphere_schedule_fire_prune ON schedule_fire_requests FOR DELETE USING ({predicate})")


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table("schedule_fire_requests")
    op.drop_constraint("uq_schedule_org_id", "schedules", type_="unique")
