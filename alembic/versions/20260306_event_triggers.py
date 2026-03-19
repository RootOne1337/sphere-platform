"""TZ-11+: event_triggers таблица + pending_registration статус аккаунта

Revision ID: 20260306_event_triggers
Revises: 20260306_events_sessions
Create Date: 2026-03-06 19:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260306_event_triggers"
down_revision: Union[str, None] = "20260306_events_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ══════════════════════════════════════════════════════════════════════
    # 1. Добавляем pending_registration в enum account_status
    # ══════════════════════════════════════════════════════════════════════
    op.execute("ALTER TYPE account_status ADD VALUE IF NOT EXISTS 'pending_registration'")

    # ══════════════════════════════════════════════════════════════════════
    # 2. Таблица event_triggers — автоматический запуск pipeline по событиям
    # ══════════════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_triggers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            event_type_pattern VARCHAR(200) NOT NULL,
            pipeline_id UUID NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
            input_params_template JSONB NOT NULL DEFAULT '{}',
            is_active BOOLEAN NOT NULL DEFAULT true,
            cooldown_seconds INTEGER NOT NULL DEFAULT 60,
            max_triggers_per_hour INTEGER NOT NULL DEFAULT 100,
            last_triggered_at TIMESTAMPTZ,
            total_triggers INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Индексы
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_triggers_org_id ON event_triggers(org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_triggers_event_type_pattern ON event_triggers(event_type_pattern)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_triggers_pipeline_id ON event_triggers(pipeline_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_triggers_org_active ON event_triggers(org_id, is_active) WHERE is_active = true")

    # RLS — изоляция по организации
    op.execute("ALTER TABLE event_triggers ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'event_triggers' AND policyname = 'event_triggers_org_isolation'
            ) THEN
                CREATE POLICY event_triggers_org_isolation ON event_triggers
                    USING (org_id = current_setting('app.current_org_id', true)::uuid);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS event_triggers CASCADE;")
    # Удаление значения из enum невозможно в PostgreSQL напрямую.
    # pending_registration останется в enum при downgrade.
