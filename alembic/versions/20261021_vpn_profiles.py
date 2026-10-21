"""Encrypted VPN catalog with owned, append-only revisions. No live VPN effects."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261021_vpn_profiles"
down_revision = "20261006_script_catalog_metadata"
branch_labels = None
depends_on = None

# Separate inventory: never edit the already-applied historical RLS migration.
ORG_TABLES = ("vpn_profiles", "vpn_profile_revisions")
IDENTITY_TABLES = ()
ASSOCIATIONS = {}
TENANT = "NULLIF(pg_catalog.current_setting('app.current_org_id', true), '')::uuid"


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '15s'")
    op.create_table(
        "vpn_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_vpn_profile_org_id"),
        sa.CheckConstraint("current_revision >= 1", name="ck_vpn_profile_revision"),
    )
    op.create_index("ix_vpn_profiles_org_id", "vpn_profiles", ["org_id"])
    op.create_table(
        "vpn_profile_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("provider_id", sa.String(40), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("protocol_version", sa.String(12), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("traffic_policy", postgresql.JSONB(), nullable=False),
        sa.Column("endpoint", sa.String(300), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.Column("config_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id", "profile_id"], ["vpn_profiles.org_id", "vpn_profiles.id"], name="fk_vpn_revision_owned_profile"),
        sa.UniqueConstraint("org_id", "profile_id", "revision", name="uq_vpn_profile_revision"),
        sa.UniqueConstraint("org_id", "request_id", name="uq_vpn_profile_request"),
        sa.CheckConstraint("revision >= 1", name="ck_vpn_revision_number"),
    )
    op.create_index("ix_vpn_profile_revisions_org_id", "vpn_profile_revisions", ["org_id"])
    op.create_index("ix_vpn_profile_revisions_profile_id", "vpn_profile_revisions", ["profile_id"])
    for table in ORG_TABLES:
        predicate = f"org_id = {TENANT}"
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY sphere_tenant_boundary ON "{table}" AS RESTRICTIVE FOR ALL USING ({predicate}) WITH CHECK ({predicate})')
        if table == "vpn_profiles":
            op.execute(f'CREATE POLICY sphere_tenant_access ON "{table}" FOR ALL USING ({predicate}) WITH CHECK ({predicate})')
        else:
            op.execute(f'CREATE POLICY sphere_vpn_revision_read ON "{table}" FOR SELECT USING ({predicate})')
            op.execute(f'CREATE POLICY sphere_vpn_revision_insert ON "{table}" FOR INSERT WITH CHECK ({predicate})')
            op.execute(f'CREATE POLICY sphere_vpn_revision_no_update ON "{table}" AS RESTRICTIVE FOR UPDATE USING (false)')
            op.execute(f'CREATE POLICY sphere_vpn_revision_no_delete ON "{table}" AS RESTRICTIVE FOR DELETE USING (false)')


def downgrade():
    # No automatic destruction of encrypted operator profiles/audit history.
    raise RuntimeError("VPN profile downgrade blocked; use a reviewed forward migration")
