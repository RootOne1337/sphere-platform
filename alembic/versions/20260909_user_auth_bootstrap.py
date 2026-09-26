"""Tenant-only user login/refresh discovery; protect functions with explicit grants."""

from alembic import op

revision = "20260909_user_auth_bootstrap"
down_revision = "20260909_credential_lookup"
branch_labels = None
depends_on = None


def upgrade():
    # CREATE (not OR REPLACE) deliberately refuses an operator name collision.
    for name, argument, query in (
        ("user_login_org", "login_email", """
            SELECT org_id FROM public.users
            WHERE email = login_email AND is_active
              AND pg_catalog.length(login_email) BETWEEN 1 AND 255
        """),
        ("user_refresh_org", "credential_hash", """
            SELECT org_id FROM public.refresh_tokens
            WHERE token_hash = credential_hash
              AND pg_catalog.length(credential_hash) = 64
              AND NOT revoked AND expires_at > pg_catalog.statement_timestamp()
        """),
    ):
        op.execute(f"""
            CREATE FUNCTION sphere_auth.{name}({argument} text) RETURNS uuid
            LANGUAGE sql STABLE STRICT SECURITY DEFINER
            SET search_path = pg_catalog, pg_temp
            SET row_security = off
            AS $function$ {query} $function$
        """)
        op.execute(f"REVOKE ALL ON FUNCTION sphere_auth.{name}(text) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION sphere_auth.user_refresh_org(text)")
    op.execute("DROP FUNCTION sphere_auth.user_login_org(text)")
