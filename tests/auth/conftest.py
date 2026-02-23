# tests/auth/conftest.py
# Переопределяет async_engine для SQLite-совместимости:
# заменяет PostgreSQL-специфичные типы (JSONB, INET, ARRAY) на их SQLite-аналоги.
# Также добавляет недостающие SQLAlchemy relationships (TZ-02 stub).
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from backend.database.engine import Base
from backend.models import *  # noqa: F401,F403 — side-effect: registers all mappers


def _patch_missing_relationships() -> None:
    """
    Organization.devices ссылается на Device.org через back_populates,
    но TZ-02 ещё не определил Device.org. Добавляем relationship чтобы
    SQLAlchemy смог сконфигурировать все маперы.
    Без этого pytest падает с InvalidRequestError при первом создании ORM-объекта.
    """
    from sqlalchemy import inspect as sa_inspect

    from backend.models.device import Device

    try:
        sa_inspect(Device).get_property("org")
    except Exception:
        from sqlalchemy.orm import relationship
        # Добавляем отсутствующую обратную ссылку
        Device.org = relationship(  # type: ignore[attr-defined]
            "Organization",
            foreign_keys=[Device.__table__.c.org_id],
            back_populates="devices",
        )


# Применяем патч немедленно при импорте conftest, чтобы mapper не падал
# даже в unit-тестах, которые не используют БД-фикстуры.
_patch_missing_relationships()


def _patch_pg_types_for_sqlite() -> None:
    """
    Заменить PostgreSQL-специфичные типы в метаданных на SQLite-совместимые.
    Вызывается однажды перед create_all на SQLite.
    JSONB  → JSON
    INET   → String(45)
    ARRAY  → JSON  (хранится как JSON-массив)
    """
    from sqlalchemy import JSON, String
    from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB

    for table in Base.metadata.tables.values():
        for column in table.columns:
            col_type = type(column.type)
            if col_type is JSONB or col_type.__name__ == "JSONB":
                column.type = JSON()
            elif col_type is INET or col_type.__name__ == "INET":
                column.type = String(45)
            elif col_type is ARRAY or col_type.__name__ == "ARRAY":
                column.type = JSON()


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    """
    Переопределение базового async_engine из tests/conftest.py.
    Патчит missing relationships и PG-типы перед созданием SQLite схемы.
    """
    _patch_missing_relationships()
    _patch_pg_types_for_sqlite()

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
