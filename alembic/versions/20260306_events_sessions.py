"""TZ-11: device_events + account_sessions — события устройств и история сессий аккаунтов

Revision ID: 20260306_events_sessions
Revises: 20260301_game_accounts
Create Date: 2026-03-06 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260306_events_sessions"
down_revision: Union[str, None] = "20260301_game_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ══════════════════════════════════════════════════════════════════════
    # Чистый SQL — обход конфликта asyncpg + SQLAlchemy metadata auto-create
    # ══════════════════════════════════════════════════════════════════════

    # ── Enum-типы ─────────────────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_severity') THEN
                CREATE TYPE event_severity AS ENUM ('debug', 'info', 'warning', 'error', 'critical');
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'session_end_reason') THEN
                CREATE TYPE session_end_reason AS ENUM (
                    'completed', 'banned', 'captcha', 'error', 'manual',
                    'rotation', 'timeout', 'device_offline'
                );
            END IF;
        END $$;
    """)

    # ── Таблица: device_events ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE device_events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            device_id       UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            event_type      VARCHAR(100) NOT NULL,
            severity        event_severity NOT NULL DEFAULT 'info',
            message         TEXT,
            account_id      UUID REFERENCES game_accounts(id) ON DELETE SET NULL,
            task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
            pipeline_run_id UUID REFERENCES pipeline_runs(id) ON DELETE SET NULL,
            data            JSONB NOT NULL DEFAULT '{}',
            occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed       BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("COMMENT ON TABLE device_events IS 'Персистентное хранилище событий от агентов'")
    op.execute("COMMENT ON COLUMN device_events.event_type IS 'Тип: account.banned, account.captcha, game.crashed итд'")
    op.execute("COMMENT ON COLUMN device_events.severity IS 'Уровень серьёзности: debug, info, warning, error, critical'")

    # Индексы device_events
    op.execute("CREATE INDEX ix_device_events_org_id ON device_events (org_id);")
    op.execute("CREATE INDEX ix_device_events_device_id ON device_events (device_id);")
    op.execute("CREATE INDEX ix_device_events_event_type ON device_events (event_type);")
    op.execute("CREATE INDEX ix_device_events_severity ON device_events (severity);")
    op.execute("CREATE INDEX ix_device_events_account_id ON device_events (account_id);")
    op.execute("CREATE INDEX ix_device_events_task_id ON device_events (task_id);")
    op.execute("CREATE INDEX ix_device_events_pipeline_run_id ON device_events (pipeline_run_id);")
    op.execute("CREATE INDEX ix_device_events_unprocessed ON device_events (org_id, processed) WHERE processed = false;")
    op.execute("CREATE INDEX ix_device_events_device_occurred ON device_events (device_id, occurred_at);")
    op.execute("CREATE INDEX ix_device_events_org_type ON device_events (org_id, event_type, occurred_at);")
    op.execute("CREATE INDEX ix_device_events_account ON device_events (account_id) WHERE account_id IS NOT NULL;")

    # RLS device_events
    op.execute("ALTER TABLE device_events ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY device_events_org_isolation ON device_events
        USING (org_id::text = current_setting('app.current_org_id', true));
    """)

    # ── Таблица: account_sessions ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE account_sessions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            account_id      UUID NOT NULL REFERENCES game_accounts(id) ON DELETE CASCADE,
            device_id       UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            started_at      TIMESTAMPTZ NOT NULL,
            ended_at        TIMESTAMPTZ,
            end_reason      session_end_reason,
            error_message   TEXT,
            script_id       UUID REFERENCES scripts(id) ON DELETE SET NULL,
            task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
            pipeline_run_id UUID REFERENCES pipeline_runs(id) ON DELETE SET NULL,
            nodes_executed  INTEGER NOT NULL DEFAULT 0,
            errors_count    INTEGER NOT NULL DEFAULT 0,
            level_before    INTEGER,
            level_after     INTEGER,
            balance_before  DOUBLE PRECISION,
            balance_after   DOUBLE PRECISION,
            meta            JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("COMMENT ON TABLE account_sessions IS 'История использования аккаунтов на устройствах'")
    op.execute("COMMENT ON COLUMN account_sessions.end_reason IS 'Причина завершения сессии'")

    # Индексы account_sessions
    op.execute("CREATE INDEX ix_account_sessions_org_id ON account_sessions (org_id);")
    op.execute("CREATE INDEX ix_account_sessions_account_id ON account_sessions (account_id);")
    op.execute("CREATE INDEX ix_account_sessions_device_id ON account_sessions (device_id);")
    op.execute("CREATE INDEX ix_account_sessions_account_started ON account_sessions (account_id, started_at);")
    op.execute("CREATE INDEX ix_account_sessions_active ON account_sessions (org_id, ended_at) WHERE ended_at IS NULL;")
    op.execute("CREATE INDEX ix_account_sessions_device_started ON account_sessions (device_id, started_at);")
    op.execute("CREATE INDEX ix_account_sessions_org_reason ON account_sessions (org_id, end_reason);")

    # RLS account_sessions
    op.execute("ALTER TABLE account_sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY account_sessions_org_isolation ON account_sessions
        USING (org_id::text = current_setting('app.current_org_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS account_sessions_org_isolation ON account_sessions;")
    op.execute("DROP POLICY IF EXISTS device_events_org_isolation ON device_events;")
    op.execute("DROP TABLE IF EXISTS account_sessions;")
    op.execute("DROP TABLE IF EXISTS device_events;")
    op.execute("DROP TYPE IF EXISTS session_end_reason;")
    op.execute("DROP TYPE IF EXISTS event_severity;")
