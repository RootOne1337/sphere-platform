"""TZ-10: game_accounts — игровые аккаунты для фарминг-платформы

Revision ID: 20260301_game_accounts
Revises: 20260228_locations
Create Date: 2026-03-01 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260301_game_accounts"
down_revision: Union[str, None] = "20260228_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enum тип для статуса аккаунта ────────────────────────────────────────
    account_status = postgresql.ENUM(
        "free", "in_use", "cooldown",
        "banned", "captcha", "phone_verify",
        "disabled", "archived",
        name="account_status",
        create_type=False,
    )
    account_status.create(op.get_bind(), checkfirst=True)

    # ── Таблица game_accounts ────────────────────────────────────────────────
    op.create_table(
        "game_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),

        # Организация
        sa.Column("org_id", sa.Uuid(), nullable=False),

        # Идентификация
        sa.Column("game", sa.String(length=100), nullable=False),
        sa.Column("login", sa.String(length=255), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),

        # Статус
        sa.Column(
            "status",
            account_status,
            nullable=False,
            server_default="free",
        ),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),

        # Привязка к устройству
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),

        # Игровая статистика
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("balance", sa.Float(), nullable=True),
        sa.Column("last_balance_update", sa.DateTime(timezone=True), nullable=True),

        # Баны
        sa.Column("total_bans", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_ban_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ban_reason", sa.Text(), nullable=True),

        # Сессии
        sa.Column("total_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_session_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),

        # Метаданные
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),

        # Timestamps
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

        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
    )

    # ── Индексы ──────────────────────────────────────────────────────────────
    op.create_index("ix_game_accounts_org_id", "game_accounts", ["org_id"])
    op.create_index("ix_game_accounts_game", "game_accounts", ["game"])
    op.create_index("ix_game_accounts_status", "game_accounts", ["status"])
    op.create_index(
        "ix_game_accounts_org_game_login",
        "game_accounts",
        ["org_id", "game", "login"],
        unique=True,
    )
    op.create_index(
        "ix_game_accounts_org_game_status",
        "game_accounts",
        ["org_id", "game", "status"],
    )
    op.create_index(
        "ix_game_accounts_device_id",
        "game_accounts",
        ["device_id"],
        postgresql_where=sa.text("device_id IS NOT NULL"),
    )

    # ── RLS политика ─────────────────────────────────────────────────────────
    op.execute("ALTER TABLE game_accounts ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY game_accounts_org_isolation ON game_accounts
        USING (org_id = current_setting('app.current_org_id')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS game_accounts_org_isolation ON game_accounts;")
    op.execute("ALTER TABLE game_accounts DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_game_accounts_device_id", table_name="game_accounts")
    op.drop_index("ix_game_accounts_org_game_status", table_name="game_accounts")
    op.drop_index("ix_game_accounts_org_game_login", table_name="game_accounts")
    op.drop_index("ix_game_accounts_status", table_name="game_accounts")
    op.drop_index("ix_game_accounts_game", table_name="game_accounts")
    op.drop_index("ix_game_accounts_org_id", table_name="game_accounts")

    op.drop_table("game_accounts")

    # Удалить enum тип
    sa.Enum(name="account_status").drop(op.get_bind(), checkfirst=True)
