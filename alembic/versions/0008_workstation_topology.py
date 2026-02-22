"""TZ-08 SPLIT-5: workstation topology — add missing columns

Revision ID: 0008_workstation_topology
Revises: 0001_baseline
Create Date: 2026-02-22

Добавляет к уже существующим таблицам workstations / ldplayer_instances
поля, необходимые PC Agent для регистрации топологии.

workstations:
  + ip_address   TEXT         — IP воркстанции
  + last_seen    TIMESTAMPTZ  — время последнего heartbeat/регистрации

ldplayer_instances:
  + instance_name  TEXT    — человекочитаемое имя (из ldconsole list2)
  + adb_port       INTEGER — 5554 + index * 2
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_workstation_topology"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- workstations: добавить ip_address, last_seen --------------------
    op.add_column(
        "workstations",
        sa.Column("ip_address", sa.String(64), nullable=True),
    )
    op.add_column(
        "workstations",
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )

    # --- ldplayer_instances: добавить instance_name, adb_port ------------
    op.add_column(
        "ldplayer_instances",
        sa.Column("instance_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "ldplayer_instances",
        sa.Column("adb_port", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ldplayer_instances", "adb_port")
    op.drop_column("ldplayer_instances", "instance_name")
    op.drop_column("workstations", "last_seen")
    op.drop_column("workstations", "ip_address")
