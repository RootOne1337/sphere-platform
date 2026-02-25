#!/usr/bin/env python3
"""
scripts/seed_black_russia.py

Создаёт скрипт автоматизации "Black Russia — Auto Login" в БД платформы.
Скрипт запускается через Script Engine (TZ-04) → WebSocket → Android Agent (TZ-07).
Никаких ADB с сервера — агент выполняет DAG прямо на устройстве.

Использование:
    python scripts/seed_black_russia.py
    python scripts/seed_black_russia.py --org-id <UUID>  # несколько организаций

Требования:
    — Активная виртуальная среда (.venv) с зависимостями backend
    — Переменные окружения из .env (POSTGRES_URL и т.д.)
    — Запущенная БД PostgreSQL
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # python-dotenv не установлен — читаем из окружения

from sqlalchemy import select

from backend.database.engine import AsyncSessionLocal
from backend.models.organization import Organization  # noqa: E402
from backend.models.script import Script, ScriptVersion

# ─── Black Russia DAG ────────────────────────────────────────────────────────
#
# DAG описывает линейный флоу входа в игру Black Russia (com.br.top).
# Android Agent (TZ-07) выполняет этот DAG ИЗНУТРИ устройства через
# Accessibility API / UIAutomator — без внешнего ADB.
#
# Координаты под LDPlayer 720×1280 (портретный режим).
# При другом разрешении скорректируй через Visual Builder (/scripts/builder).
#
# Узлы:
#  start → sleep_init → cond_perm → [tap_perm → sleep_perm] → cond_ok_1
#    → [tap_ok_1 → sleep_ok_1] → cond_servers → [tap_server → sleep_server
#    → cond_ok_2 → [tap_ok_2 → sleep_ok_2]] → wait_login
#    → tap_pass_field → sleep_tap → type_pass → sleep_type → tap_play
#    → wait_game → end_success / end_fail
#
# ─────────────────────────────────────────────────────────────────────────────

BLACK_RUSSIA_DAG: dict = {
    "version": "1.0",
    "name": "Black Russia — Auto Login",
    "description": (
        "Автоматический вход в Black Russia (com.br.top). "
        "Выполняется Android Agent-ом изнутри устройства. "
        "Обрабатывает: диалоги разрешений, OK-диалоги, выбор сервера, "
        "ввод пароля, ожидание загрузки игры. "
        "Координаты под LDPlayer 720×1280."
    ),
    "entry_node": "start",
    "nodes": [
        # ── 1. Start ────────────────────────────────────────────────────────
        {
            "id": "start",
            "action": {"type": "start"},
            "on_success": "sleep_init",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        # ── 2. Ждём загрузки приложения ─────────────────────────────────────
        {
            "id": "sleep_init",
            "action": {"type": "sleep", "ms": 5_000},
            "on_success": "cond_perm",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 8_000,
        },
        # ── 3. Проверяем диалог разрешений ──────────────────────────────────
        {
            "id": "cond_perm",
            "action": {
                "type": "condition",
                "check": "element_exists",
                "params": {
                    "selector": "com.br.top:id/permission_allow_button",
                    "strategy": "id",
                },
                "on_true": "tap_perm",
                "on_false": "cond_ok_1",
            },
            "on_success": None,
            "on_failure": "cond_ok_1",
            "retry": 0,
            "timeout_ms": 8_000,
        },
        # ── 4. Нажимаем "Разрешить" ─────────────────────────────────────────
        {
            "id": "tap_perm",
            "action": {"type": "tap", "x": 540, "y": 1080},
            "on_success": "sleep_perm",
            "on_failure": "cond_ok_1",
            "retry": 1,
            "timeout_ms": 5_000,
        },
        # ── 5. Пауза после разрешения ───────────────────────────────────────
        {
            "id": "sleep_perm",
            "action": {"type": "sleep", "ms": 1_000},
            "on_success": "cond_ok_1",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 3_000,
        },
        # ── 6. Проверяем OK-диалог (загрузка, обновление и т.д.) ────────────
        {
            "id": "cond_ok_1",
            "action": {
                "type": "condition",
                "check": "element_exists",
                "params": {
                    "selector": "com.br.top:id/button_ok",
                    "strategy": "id",
                },
                "on_true": "tap_ok_1",
                "on_false": "cond_servers",
            },
            "on_success": None,
            "on_failure": "cond_servers",
            "retry": 0,
            "timeout_ms": 8_000,
        },
        # ── 7. Нажимаем OK ──────────────────────────────────────────────────
        {
            "id": "tap_ok_1",
            "action": {"type": "tap", "x": 360, "y": 750},
            "on_success": "sleep_ok_1",
            "on_failure": "cond_servers",
            "retry": 1,
            "timeout_ms": 5_000,
        },
        # ── 8. Пауза после OK ───────────────────────────────────────────────
        {
            "id": "sleep_ok_1",
            "action": {"type": "sleep", "ms": 500},
            "on_success": "cond_servers",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 3_000,
        },
        # ── 9. Проверяем список серверов ────────────────────────────────────
        {
            "id": "cond_servers",
            "action": {
                "type": "condition",
                "check": "element_exists",
                "params": {
                    "selector": "com.br.top:id/list_servers_choose",
                    "strategy": "id",
                },
                "on_true": "tap_server",
                "on_false": "wait_login",
            },
            "on_success": None,
            "on_failure": "wait_login",
            "retry": 0,
            "timeout_ms": 8_000,
        },
        # ── 10. Тапаем первый сервер ────────────────────────────────────────
        {
            "id": "tap_server",
            "action": {"type": "tap", "x": 360, "y": 480},
            "on_success": "sleep_server",
            "on_failure": "wait_login",
            "retry": 1,
            "timeout_ms": 5_000,
        },
        # ── 11. Ждём после выбора сервера ───────────────────────────────────
        {
            "id": "sleep_server",
            "action": {"type": "sleep", "ms": 2_000},
            "on_success": "cond_ok_2",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        # ── 12. OK-диалог после выбора сервера ──────────────────────────────
        {
            "id": "cond_ok_2",
            "action": {
                "type": "condition",
                "check": "element_exists",
                "params": {
                    "selector": "com.br.top:id/button_ok",
                    "strategy": "id",
                },
                "on_true": "tap_ok_2",
                "on_false": "wait_login",
            },
            "on_success": None,
            "on_failure": "wait_login",
            "retry": 0,
            "timeout_ms": 8_000,
        },
        # ── 13. Нажимаем OK (после сервера) ─────────────────────────────────
        {
            "id": "tap_ok_2",
            "action": {"type": "tap", "x": 360, "y": 750},
            "on_success": "sleep_ok_2",
            "on_failure": "wait_login",
            "retry": 1,
            "timeout_ms": 5_000,
        },
        # ── 14. Пауза после OK ──────────────────────────────────────────────
        {
            "id": "sleep_ok_2",
            "action": {"type": "sleep", "ms": 500},
            "on_success": "wait_login",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 3_000,
        },
        # ── 15. Ждём экран входа (поле пароля) ──────────────────────────────
        {
            "id": "wait_login",
            "action": {
                "type": "find_element",
                "selector": "com.br.top:id/password_enter",
                "strategy": "id",
                "timeout_ms": 30_000,
                "fail_if_not_found": True,
            },
            "on_success": "tap_pass_field",
            "on_failure": "end_fail",
            "retry": 0,
            "timeout_ms": 35_000,
        },
        # ── 16. Тапаем поле пароля ──────────────────────────────────────────
        {
            "id": "tap_pass_field",
            "action": {"type": "tap", "x": 360, "y": 620},
            "on_success": "sleep_tap",
            "on_failure": "end_fail",
            "retry": 1,
            "timeout_ms": 5_000,
        },
        # ── 17. Пауза (клавиатура) ──────────────────────────────────────────
        {
            "id": "sleep_tap",
            "action": {"type": "sleep", "ms": 500},
            "on_success": "type_pass",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 3_000,
        },
        # ── 18. Вводим пароль ───────────────────────────────────────────────
        {
            "id": "type_pass",
            "action": {
                "type": "type_text",
                "text": "NaftaliN1337228",
                "clear_first": True,
            },
            "on_success": "sleep_type",
            "on_failure": "end_fail",
            "retry": 1,
            "timeout_ms": 10_000,
        },
        # ── 19. Пауза после ввода ────────────────────────────────────────────
        {
            "id": "sleep_type",
            "action": {"type": "sleep", "ms": 500},
            "on_success": "tap_play",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 3_000,
        },
        # ── 20. Нажимаем кнопку Play/Войти ──────────────────────────────────
        {
            "id": "tap_play",
            "action": {"type": "tap", "x": 360, "y": 890},
            "on_success": "wait_game",
            "on_failure": "end_fail",
            "retry": 2,
            "timeout_ms": 5_000,
        },
        # ── 21. Ждём загрузки игры (donate_header появляется в главном меню) ─
        {
            "id": "wait_game",
            "action": {
                "type": "find_element",
                "selector": "com.br.top:id/donate_header_value_rub",
                "strategy": "id",
                "timeout_ms": 90_000,
                "fail_if_not_found": True,
            },
            "on_success": "end_success",
            "on_failure": "end_fail",
            "retry": 0,
            "timeout_ms": 95_000,
        },
        # ── 22. Успех ────────────────────────────────────────────────────────
        {
            "id": "end_success",
            "action": {"type": "end", "status": "success"},
            "on_success": None,
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        # ── 23. Провал (экран входа не появился / игра не загрузилась) ───────
        {
            "id": "end_fail",
            "action": {"type": "end", "status": "failure"},
            "on_success": None,
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
    ],
}

SCRIPT_NAME = "Black Russia — Auto Login"


async def seed(org_id_override: uuid.UUID | None = None) -> None:
    async with AsyncSessionLocal() as db:
        # Найти организацию
        if org_id_override:
            org = await db.scalar(
                select(Organization).where(Organization.id == org_id_override)
            )
            if not org:
                print(f"❌  Организация {org_id_override} не найдена.")
                sys.exit(1)
        else:
            org = await db.scalar(select(Organization).limit(1))
            if not org:
                print("❌  Нет ни одной организации. Запусти приложение и зарегистрируйся.")
                sys.exit(1)

        org_id: uuid.UUID = org.id
        print(f"🏢  Организация: {org.name} ({org_id})")

        # Проверить — не существует ли уже
        existing: Script | None = await db.scalar(
            select(Script).where(
                Script.org_id == org_id,
                Script.name == SCRIPT_NAME,
                Script.is_archived.is_(False),
            )
        )
        if existing:
            print(f"✅  Скрипт уже существует: {existing.id}")
            print(f"   Открой в Visual Builder: /scripts/builder?id={existing.id}")
            return

        # Создать Script
        script = Script(
            org_id=org_id,
            name=SCRIPT_NAME,
            description=BLACK_RUSSIA_DAG["description"],
            is_archived=False,
        )
        db.add(script)
        await db.flush()

        # Создать ScriptVersion c DAG
        version = ScriptVersion(
            script_id=script.id,
            org_id=org_id,
            version=1,
            dag=BLACK_RUSSIA_DAG,
            notes="Создано seed-скриптом. Скорректируй координаты под своё разрешение.",
        )
        db.add(version)
        await db.flush()

        # Установить текущую версию
        script.current_version_id = version.id

        await db.commit()

        print(f"✅  Скрипт создан: {script.id}")
        print(f"   Версия:    {version.id} (v1)")
        print(f"   DAG-узлов: {len(BLACK_RUSSIA_DAG['nodes'])}")
        print()
        print("   Дальше:")
        print(f"   1. Открой в Visual Builder: /scripts/builder?id={script.id}")
        print("   2. Проверь и скорректируй координаты tap-узлов.")
        print(f"   3. Запусти со страницы Scripts (/scripts) — кнопка Run.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Black Russia DAG script")
    p.add_argument(
        "--org-id",
        type=uuid.UUID,
        default=None,
        help="UUID организации (если несколько; по умолчанию — первая в БД)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(seed(args.org_id))
