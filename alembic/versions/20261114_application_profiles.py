"""Add a tenant-owned catalog without updating account or device records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261114_application_profiles"
down_revision = "20261021_vpn_profiles"
branch_labels = None
depends_on = None

ORG_TABLES = ("application_profiles",)
IDENTITY_TABLES = ()
ASSOCIATIONS = {}
TENANT = "NULLIF(pg_catalog.current_setting('app.current_org_id', true), '')::uuid"


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '15s'")
    op.create_table(
        "application_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("android_package", sa.String(255), nullable=True),
        sa.Column("servers", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "key", name="uq_application_profile_org_key"),
    )
    table = "application_profiles"
    predicate = f"org_id = {TENANT}"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute(f"CREATE POLICY sphere_tenant_boundary ON {table} AS RESTRICTIVE FOR ALL USING ({predicate}) WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY sphere_profile_read ON {table} FOR SELECT USING ({predicate})")
    op.execute(f"CREATE POLICY sphere_profile_create ON {table} FOR INSERT WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY sphere_profile_update ON {table} FOR UPDATE USING ({predicate}) WITH CHECK ({predicate})")


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '15s'")
    op.drop_table("application_profiles")
