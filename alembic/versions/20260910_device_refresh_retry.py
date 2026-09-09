"""Retain one recoverable device refresh operation without storing bearer tokens."""

import sqlalchemy as sa
from alembic import op

revision = "20260910_device_refresh_retry"
down_revision = "20260909_user_auth_bootstrap"
branch_labels = None
depends_on = None


def _lookup(include_previous):
    match = "refresh_token_hash = credential_hash"
    if include_previous:
        match += " OR refresh_previous_token_hash = credential_hash"
    # CREATE OR REPLACE retains owner and explicit runtime EXECUTE grants.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION sphere_auth.device_refresh_org(credential_hash text) RETURNS uuid
        LANGUAGE sql STABLE STRICT SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        SET row_security = off
        AS $function$
            SELECT org_id FROM public.devices
            WHERE ({match}) AND pg_catalog.length(credential_hash) = 64
              AND is_active AND refresh_token_expires_at > pg_catalog.statement_timestamp()
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION sphere_auth.device_refresh_org(text) FROM PUBLIC")


def upgrade():
    op.add_column("devices", sa.Column("refresh_previous_token_hash", sa.String(64), nullable=True))
    op.add_column("devices", sa.Column("refresh_rotation_key_hash", sa.String(64), nullable=True))
    op.create_unique_constraint("devices_refresh_previous_token_hash_key", "devices", ["refresh_previous_token_hash"])
    _lookup(True)


def downgrade():
    _lookup(False)
    op.drop_constraint("devices_refresh_previous_token_hash_key", "devices", type_="unique")
    op.drop_column("devices", "refresh_rotation_key_hash")
    op.drop_column("devices", "refresh_previous_token_hash")
