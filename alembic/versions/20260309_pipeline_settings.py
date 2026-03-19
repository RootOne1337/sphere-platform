"""Добавление таблицы pipeline_settings (персистентные настройки оркестрации) и колонки server_name в devices.

Revision ID: 20260309_pipeline_settings
Revises: 20260308_game_accounts_v2
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# Идентификаторы ревизий
revision = "20260309_pipeline_settings"
down_revision = "20260308_game_accounts_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Таблица pipeline_settings (singleton per org) ---
    op.create_table(
        "pipeline_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        # Главные переключатели
        sa.Column("orchestration_enabled", sa.Boolean(), server_default="false", nullable=False,
                   comment="Глобальный переключатель оркестрации"),
        sa.Column("scheduler_enabled", sa.Boolean(), server_default="false", nullable=False,
                   comment="Глобальный переключатель планировщика задач"),

        # Регистрация
        sa.Column("registration_enabled", sa.Boolean(), server_default="false", nullable=False,
                   comment="Автоматическая регистрация новых аккаунтов"),
        sa.Column("max_concurrent_registrations", sa.Integer(), server_default="3", nullable=False,
                   comment="Максимум одновременных регистраций"),
        sa.Column("registration_script_id", sa.Uuid(), sa.ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True,
                   comment="ID скрипта регистрации (DAG)"),
        sa.Column("registration_timeout_seconds", sa.Integer(), server_default="600", nullable=False,
                   comment="Таймаут одной регистрации (секунды)"),

        # Фарм
        sa.Column("farming_enabled", sa.Boolean(), server_default="false", nullable=False,
                   comment="Автоматический фарм"),
        sa.Column("max_concurrent_farming", sa.Integer(), server_default="10", nullable=False,
                   comment="Максимум одновременных фарм-сессий"),
        sa.Column("farming_script_id", sa.Uuid(), sa.ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True,
                   comment="ID скрипта фарма (DAG)"),
        sa.Column("farming_session_duration_seconds", sa.Integer(), server_default="3600", nullable=False,
                   comment="Длительность одной фарм-сессии (секунды)"),

        # Уровни
        sa.Column("default_target_level", sa.Integer(), server_default="3", nullable=False,
                   comment="Целевой уровень по умолчанию"),
        sa.Column("cooldown_between_sessions_minutes", sa.Integer(), server_default="30", nullable=False,
                   comment="Пауза между фарм-сессиями (минуты)"),

        # Ники
        sa.Column("nick_generation_enabled", sa.Boolean(), server_default="true", nullable=False,
                   comment="Автогенерация никнеймов"),
        sa.Column("nick_pattern", sa.String(100), server_default="{first_name}_{last_name}", nullable=False,
                   comment="Шаблон ника: {first_name}_{last_name}"),

        # Мониторинг
        sa.Column("ban_detection_enabled", sa.Boolean(), server_default="true", nullable=False,
                   comment="Обнаружение банов"),
        sa.Column("auto_replace_banned", sa.Boolean(), server_default="false", nullable=False,
                   comment="Авто-замена забаненных аккаунтов"),

        # Мета
        sa.Column("notes", sa.Text(), nullable=True, comment="Заметки администратора"),
        sa.Column("meta", JSONB, server_default="{}", nullable=False, comment="Произвольные метаданные"),
    )
    op.create_index("ix_pipeline_settings_org_id", "pipeline_settings", ["org_id"], unique=True)

    # --- Колонка server_name в devices ---
    op.add_column(
        "devices",
        sa.Column(
            "server_name", sa.String(50), nullable=True,
            comment="Игровой сервер, привязанный к устройству",
        ),
    )
    op.create_index("ix_devices_server_name", "devices", ["server_name"], postgresql_where=sa.text("server_name IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_devices_server_name", table_name="devices")
    op.drop_column("devices", "server_name")
    op.drop_index("ix_pipeline_settings_org_id", table_name="pipeline_settings")
    op.drop_table("pipeline_settings")
