# alembic/env.py
# Асинхронный env для SQLAlchemy 2.0 + asyncpg.
# Импортирует все модели через backend.models для autogenerate.
# Поддерживает multi-head стратегию (несколько baseline-голов per TZ-этап).
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# -- Импорт всех моделей для autogenerate --
# КРИТИЧНО: без этих импортов Alembic не «видит» модели
from backend.database.engine import Base  # noqa: F401
import backend.models  # noqa: F401 — side-effect import, регистрирует все mapper-ы

from backend.core.config import get_settings

settings = get_settings()

# Alembic config object (alembic.ini)
config = context.config

# Логирование из alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные для autogenerate
target_metadata = Base.metadata

# Переопределяем URL из settings (игнорируем placeholder в alembic.ini)
config.set_main_option(
    "sqlalchemy.url",
    # asyncpg не поддерживает sync-режим, для Alembic нужен postgresql+asyncpg
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
)


def run_migrations_offline() -> None:
    """
    Offline-режим: генерирует SQL без реального подключения.
    Используется для ревью SQL перед применением в prod.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Включить поддержку multi-head: merge производится вручную (alembic merge heads)
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Online-режим с asynchronous engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool — Alembic не должен держать соединения
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
