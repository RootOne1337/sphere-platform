"""Narrow opaque-credential tenant discovery; runtime tables remain under RLS.

Run as the trusted migration/table owner. Runtime credentials require explicit
USAGE/EXECUTE grants on these two functions, never membership in their owner role.
"""

from alembic import op

revision = "20260909_credential_lookup"
down_revision = "20260908_tenant_policies"
branch_labels = None
depends_on = None


def upgrade():
    # Fail on name collisions instead of adopting an operator-controlled schema.
    op.execute("CREATE SCHEMA sphere_auth")
    op.execute("REVOKE ALL ON SCHEMA sphere_auth FROM PUBLIC")
    for name, table, column, expiry in (
        ("api_key_org", "api_keys", "key_hash", "(expires_at IS NULL OR expires_at > pg_catalog.statement_timestamp())"),
        ("device_refresh_org", "devices", "refresh_token_hash", "refresh_token_expires_at > pg_catalog.statement_timestamp()"),
    ):
        # All identifiers are migration constants; the only input is a full hash.
        # No dynamic SQL, key prefix matching, row payload or tenant enumeration.
        op.execute(f"""
            CREATE FUNCTION sphere_auth.{name}(credential_hash text) RETURNS uuid
            LANGUAGE sql STABLE STRICT SECURITY DEFINER
            SET search_path = pg_catalog, pg_temp
            SET row_security = off
            AS $function$
                SELECT org_id FROM public.{table}
                WHERE {column} = credential_hash
                  AND pg_catalog.length(credential_hash) = 64
                  AND is_active AND {expiry}
            $function$
        """)
        op.execute(f"REVOKE ALL ON FUNCTION sphere_auth.{name}(text) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION sphere_auth.device_refresh_org(text)")
    op.execute("DROP FUNCTION sphere_auth.api_key_org(text)")
    op.execute("DROP SCHEMA sphere_auth")  # No CASCADE: never remove unrelated objects.
