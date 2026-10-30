# tests/auth/conftest.py
# Переопределяет async_engine для SQLite-совместимости:
# использует SQLite-варианты типов из tests/conftest.py.
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


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    """
    Переопределение базового async_engine из tests/conftest.py.
    Проверяет relationships перед созданием SQLite схемы.
    """
    _patch_missing_relationships()

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
