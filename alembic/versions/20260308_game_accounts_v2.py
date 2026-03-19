"""Добавление игровой специфики в game_accounts: сервер, никнейм, двойной баланс, VIP, законопослушность, регистрационные данные.

Revision ID: 20260308_game_accounts_v2
Revises: 20260306_event_triggers
Create Date: 2026-03-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM

# Идентификаторы ревизий
revision = "20260308_game_accounts_v2"
down_revision = "20260306_event_triggers"
branch_labels = None
depends_on = None

# Создаём enum-типы на уровне модуля, чтобы переиспользовать в upgrade/downgrade
gender_enum = ENUM("male", "female", name="gender_enum", create_type=False)
vip_type_enum = ENUM("none", "silver", "gold", "platinum", "diamond", name="vip_type_enum", create_type=False)


def upgrade() -> None:
    # --- Создаём новые enum-типы ---
    gender_enum_type = sa.Enum("male", "female", name="gender_enum")
    gender_enum_type.create(op.get_bind(), checkfirst=True)

    vip_enum_type = sa.Enum("none", "silver", "gold", "platinum", "diamond", name="vip_type_enum")
    vip_enum_type.create(op.get_bind(), checkfirst=True)

    # --- pending_registration уже добавлен в 20260306_event_triggers ---

    # --- Переименовываем balance → balance_rub ---
    op.alter_column("game_accounts", "balance", new_column_name="balance_rub")

    # --- Добавляем новые колонки ---
    op.add_column("game_accounts", sa.Column("server_name", sa.String(50), nullable=True, comment="Название сервера (RED, MOSCOW, KAZAN)"))
    op.add_column("game_accounts", sa.Column("nickname", sa.String(100), nullable=True, comment="Игровой никнейм персонажа (Имя_Фамилия)"))
    op.add_column("game_accounts", sa.Column("gender", gender_enum, nullable=True, comment="Пол персонажа при регистрации"))
    op.add_column("game_accounts", sa.Column("target_level", sa.Integer(), nullable=True, comment="Целевой уровень прокачки"))
    op.add_column("game_accounts", sa.Column("experience", sa.BigInteger(), nullable=True, comment="Текущий опыт персонажа (EXP)"))
    op.add_column("game_accounts", sa.Column("balance_bc", sa.Float(), nullable=True, comment="Баланс BC (донат-валюта)"))
    op.add_column("game_accounts", sa.Column("vip_type", vip_type_enum, nullable=True, comment="Тип VIP-подписки"))
    op.add_column("game_accounts", sa.Column("vip_expires_at", sa.DateTime(timezone=True), nullable=True, comment="Дата окончания VIP-подписки"))
    op.add_column("game_accounts", sa.Column("lawfulness", sa.Integer(), nullable=True, comment="Уровень законопослушности (0–100)"))
    op.add_column("game_accounts", sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True, comment="Дата регистрации аккаунта в игре"))
    op.add_column("game_accounts", sa.Column("registration_ip", sa.String(45), nullable=True, comment="IP-адрес регистрации"))
    op.add_column("game_accounts", sa.Column("registration_location", sa.String(200), nullable=True, comment="Локация спавна при регистрации"))
    op.add_column("game_accounts", sa.Column("registration_provider", sa.String(50), nullable=True, comment="Провайдер регистрации (manual / auto / guest)"))

    # --- Создаём новые индексы ---
    op.create_index(
        "ix_game_accounts_org_server",
        "game_accounts",
        ["org_id", "server_name"],
        postgresql_where=sa.text("server_name IS NOT NULL"),
    )
    op.create_index(
        "ix_game_accounts_level_target",
        "game_accounts",
        ["org_id", "level", "target_level"],
        postgresql_where=sa.text("target_level IS NOT NULL"),
    )


def downgrade() -> None:
    # --- Удаляем индексы ---
    op.drop_index("ix_game_accounts_level_target", table_name="game_accounts")
    op.drop_index("ix_game_accounts_org_server", table_name="game_accounts")

    # --- Удаляем колонки ---
    op.drop_column("game_accounts", "registration_provider")
    op.drop_column("game_accounts", "registration_location")
    op.drop_column("game_accounts", "registration_ip")
    op.drop_column("game_accounts", "registered_at")
    op.drop_column("game_accounts", "lawfulness")
    op.drop_column("game_accounts", "vip_expires_at")
    op.drop_column("game_accounts", "vip_type")
    op.drop_column("game_accounts", "balance_bc")
    op.drop_column("game_accounts", "experience")
    op.drop_column("game_accounts", "target_level")
    op.drop_column("game_accounts", "gender")
    op.drop_column("game_accounts", "nickname")
    op.drop_column("game_accounts", "server_name")

    # --- Переименовываем balance_rub обратно → balance ---
    op.alter_column("game_accounts", "balance_rub", new_column_name="balance")

    # --- Удаляем enum-типы ---
    sa.Enum(name="vip_type_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="gender_enum").drop(op.get_bind(), checkfirst=True)

    # Примечание: удаление значения из account_status невозможно в PostgreSQL.
    # pending_registration останется, но не будет использоваться.
