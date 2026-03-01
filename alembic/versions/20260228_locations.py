"""TZ-02: locations + device_location_members (M2M)

Revision ID: 20260228_locations
Revises: 20260224_tz12_orchestrator
Create Date: 2026-02-28 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260228_locations"
down_revision: Union[str, None] = "20260224_tz12_orchestrator"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Таблица locations ────────────────────────────────────────────────────
    op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("parent_location_id", sa.Uuid(), nullable=True),
        sa.Column("meta", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["parent_location_id"],
            ["locations.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("org_id", "name", name="uq_location_name"),
    )
    op.create_index("ix_locations_org_id", "locations", ["org_id"])

    # ── M2M junction: device <-> location ────────────────────────────────────
    op.create_table(
        "device_location_members",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("device_id", "location_id"),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["locations.id"], ondelete="CASCADE"
        ),
    )

    # ── RLS политики (если включён RLS на уровне org_id) ─────────────────────
    op.execute("""
        ALTER TABLE locations ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY locations_org_isolation ON locations
        USING (org_id = current_setting('app.current_org_id')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS locations_org_isolation ON locations;")
    op.execute("ALTER TABLE locations DISABLE ROW LEVEL SECURITY;")
    op.drop_table("device_location_members")
    op.drop_index("ix_locations_org_id", table_name="locations")
    op.drop_table("locations")
