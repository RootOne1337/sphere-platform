"""TZ-02 SPLIT-2: device_groups — add missing columns (color, parent_group_id)

Revision ID: 0009_device_groups_missing_columns
Revises: 0008_workstation_topology
Create Date: 2026-02-23

Добавляет в таблицу device_groups колонки, присутствующие в модели, но
отсутствующие в baseline миграции:
  - color        VARCHAR(7)  nullable  # hex цвет группы #RRGGBB
  - parent_group_id  UUID    nullable  self-referencing FK (CASCADE SET NULL)
  - UniqueConstraint uq_device_group_name (org_id, name)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0009_dg_add_color_parent"
down_revision = "0008_workstation_topology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. color column
    op.add_column(
        "device_groups",
        sa.Column("color", sa.String(7), nullable=True),
    )

    # 2. parent_group_id column + FK
    op.add_column(
        "device_groups",
        sa.Column(
            "parent_group_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_device_groups_parent_group_id",
        "device_groups",
        "device_groups",
        ["parent_group_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Unique constraint (org_id, name)
    op.create_unique_constraint(
        "uq_device_group_name",
        "device_groups",
        ["org_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_device_group_name", "device_groups", type_="unique")
    op.drop_constraint(
        "fk_device_groups_parent_group_id", "device_groups", type_="foreignkey"
    )
    op.drop_column("device_groups", "parent_group_id")
    op.drop_column("device_groups", "color")
