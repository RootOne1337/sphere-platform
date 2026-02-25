#!/usr/bin/env python3
"""
seed_enrollment_key.py — Создание enrollment API-ключа для zero-touch регистрации.

Использование:
    python -m scripts.seed_enrollment_key

Скрипт:
1. Загружает конфиг из agent-config/environments/{AGENT_CONFIG_ENV}.json
2. Создаёт организацию "Default Org" если её нет
3. Создаёт APIKey с raw_key = enrollment_api_key из конфига, permission = device:register
4. Идемпотентен: повторный запуск не создаёт дублей

Для dev-окружения:
    AGENT_CONFIG_ENV=development python -m scripts.seed_enrollment_key
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    from backend.core.config import settings
    from backend.database.engine import Base, async_engine, async_session_maker
    import backend.models  # noqa: F401 — регистрация mappers

    # Загружаем agent-config
    env = settings.AGENT_CONFIG_ENV or settings.ENVIRONMENT
    config_file = PROJECT_ROOT / settings.AGENT_CONFIG_DIR / "environments" / f"{env}.json"

    if not config_file.exists():
        print(f"❌ Конфиг файл не найден: {config_file}")
        sys.exit(1)

    config = json.loads(config_file.read_text(encoding="utf-8"))
    raw_key = config.get("enrollment_api_key")

    if not raw_key:
        print(f"⚠️  enrollment_api_key не задан в {config_file.name}")
        sys.exit(0)

    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:14]

    print(f"📋 Окружение: {env}")
    print(f"🔑 Enrollment key: {raw_key[:20]}...")
    print(f"🔒 Key hash: {key_hash[:16]}...")

    # Импортируем модели
    from sqlalchemy import select

    from backend.models.api_key import APIKey
    from backend.models.organization import Organization

    # Создаём таблицы (для dev с SQLite / первый запуск)
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        # Находим или создаём организацию
        result = await session.execute(
            select(Organization).where(Organization.slug == "default-org")
        )
        org = result.scalar_one_or_none()

        if not org:
            org = Organization(name="Default Organization", slug="default-org")
            session.add(org)
            await session.flush()
            print(f"✅ Создана организация: {org.name} (id={org.id})")
        else:
            print(f"📌 Организация существует: {org.name} (id={org.id})")

        # Проверяем, есть ли уже такой ключ
        result = await session.execute(
            select(APIKey).where(APIKey.key_hash == key_hash)
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(
                f"📌 Enrollment ключ уже существует"
                f" (id={existing.id}, active={existing.is_active})"
            )
            if not existing.is_active:
                existing.is_active = True
                print("   → Реактивирован")
        else:
            api_key = APIKey(
                org_id=org.id,
                user_id=None,
                name=f"Enrollment Key ({env})",
                key_prefix=key_prefix,
                key_hash=key_hash,
                type="agent",
                permissions=["device:register"],
                is_active=True,
                expires_at=None,
            )
            session.add(api_key)
            print(f"✅ Создан enrollment API-ключ: {key_prefix}... (permissions: device:register)")

        await session.commit()

    print("🎉 Seed завершён успешно!")


if __name__ == "__main__":
    asyncio.run(main())
