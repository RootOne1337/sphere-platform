"""Add account-scoped appearance preferences with an independent revision."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261114_user_preferences"
down_revision = "20261114_audit_cursor_idx"
branch_labels = None
depends_on = None

ORG_TABLES = ("user_preferences",)
IDENTITY_TABLES = ()
ASSOCIATIONS = {}
TENANT = "NULLIF(pg_catalog.current_setting('app.current_org_id', true), '')::uuid"


def upgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '15s'")
    op.create_table(
        "user_preferences",
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("appearance", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_user_preferences_revision"),
    )
    op.execute("ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_preferences FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE user_preferences FROM PUBLIC")
    predicate = f"org_id = {TENANT}"
    op.execute(
        "CREATE POLICY sphere_tenant_boundary ON user_preferences AS RESTRICTIVE FOR ALL "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(f"CREATE POLICY sphere_preferences_read ON user_preferences FOR SELECT USING ({predicate})")
    op.execute(f"CREATE POLICY sphere_preferences_create ON user_preferences FOR INSERT WITH CHECK ({predicate})")
    op.execute(f"CREATE POLICY sphere_preferences_update ON user_preferences FOR UPDATE USING ({predicate}) WITH CHECK ({predicate})")


def downgrade():
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table("user_preferences")
