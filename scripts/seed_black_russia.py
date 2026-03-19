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
# РЕАКТИВНЫЙ WATCHDOG-DAG для Black Russia (com.br.top).
# Android Agent (TZ-07) выполняет DAG ИЗНУТРИ устройства через root shell.
#
# Архитектура: бесконечный цикл «scan → route → action → sleep → scan»
#   kill_app → sleep → open_app → sleep →
#   → start → init_counter → init_phase → init_dead_count
#   → check_game_alive → validate_pid → scan_all → route_*.
#
# scan_all — tap_first_visible с ~32 кандидатами (один UI dump на итерацию).
# Что нашёл — то нажал. Потом route_pw / route_name / route_play по лейблам.
# Watchdog: если pidof com.br.top не найден 4 раза → launch_game.
# timeout_ms = 86400000 (24ч) — DAG крутится пока не остановят.
#
# Разрешение: не зависит — все тапы через element resource-id из UI dump.
#
# ─────────────────────────────────────────────────────────────────────────────

BLACK_RUSSIA_DAG: dict = {
    "version": "2.0",
    "name": "Black Russia — Auto Login",
    "description": (
        "Реактивный watchdog-DAG для Black Russia (com.br.top). "
        "Выполняется Android Agent-ом изнутри устройства. "
        "Полный цикл: kill_app → open_app → watchdog-loop "
        "(scan_all → route → action → sleep → scan). "
        "Все тапы через tap_first_visible / tap_element (resource-id из UI dump). "
        "Resolution-independent."
    ),
    "entry_node": "kill_app",
    "timeout_ms": 86_400_000,  # 24 часа — DAG крутится пока не остановят
    "nodes": [
        # ══════════════════════════════════════════════════════════════════════
        # ▶ ФАЗА 0: ПЕРЕЗАПУСК ПРИЛОЖЕНИЯ (новое — добавлено к v4)
        # ══════════════════════════════════════════════════════════════════════
        {
            "id": "kill_app",
            "action": {
                "type": "stop_app",
                "package": "com.br.top",
                "delay_ms": 1_000,
            },
            "on_success": "sleep_after_kill",
            "on_failure": "sleep_after_kill",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "sleep_after_kill",
            "action": {"type": "sleep", "ms": 2_000},
            "on_success": "open_app",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "open_app",
            "action": {
                "type": "launch_app",
                "package": "com.br.top",
                "delay_ms": 5_000,
            },
            "on_success": "sleep_after_open",
            "on_failure": "start",
            "retry": 1,
            "timeout_ms": 10_000,
        },
        {
            "id": "sleep_after_open",
            "action": {"type": "sleep", "ms": 10_000},
            "on_success": "start",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 15_000,
        },

        # ══════════════════════════════════════════════════════════════════════
        # ▶ ФАЗА 1: ИНИЦИАЛИЗАЦИЯ (из рабочего v4)
        # ══════════════════════════════════════════════════════════════════════
        {
            "id": "start",
            "action": {"type": "start"},
            "on_success": "init_counter",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "init_counter",
            "action": {
                "type": "set_variable",
                "key": "cycle_count",
                "value": "0",
            },
            "on_success": "init_phase",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "init_phase",
            "action": {
                "type": "set_variable",
                "key": "phase",
                "value": "login",
            },
            "on_success": "init_dead_count",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "init_dead_count",
            "action": {
                "type": "set_variable",
                "key": "dead_count",
                "value": "3",
            },
            "on_success": "check_game_alive",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },

        # ══════════════════════════════════════════════════════════════════════
        # ▶ ФАЗА 2: WATCHDOG — проверка процесса игры
        # ══════════════════════════════════════════════════════════════════════
        {
            "id": "check_game_alive",
            "action": {
                "type": "shell",
                "command": "pidof com.br.top",
                "save_to": "game_pid",
            },
            "on_success": "validate_game_pid",
            "on_failure": "increment_dead_count",
            "retry": 0,
            "timeout_ms": 6_000,
        },
        {
            "id": "validate_game_pid",
            "action": {
                "type": "condition",
                "code": "local pid = tostring(ctx.game_pid or '')\nreturn #pid > 0 and pid ~= 'nil'",
                "on_true": "reset_dead_alive",
                "on_false": "increment_dead_count",
            },
            "on_success": "reset_dead_alive",
            "on_failure": "increment_dead_count",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "reset_dead_alive",
            "action": {
                "type": "set_variable",
                "key": "dead_count",
                "value": "0",
            },
            "on_success": "increment_counter",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "increment_dead_count",
            "action": {
                "type": "increment_variable",
                "key": "dead_count",
            },
            "on_success": "check_dead_limit",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "check_dead_limit",
            "action": {
                "type": "condition",
                "code": "return (tonumber(ctx.dead_count) or 0) < 4",
                "on_true": "scan_all",
                "on_false": "launch_game",
            },
            "on_success": "scan_all",
            "on_failure": "launch_game",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "launch_game",
            "action": {
                "type": "launch_app",
                "package": "com.br.top",
            },
            "on_success": "launch_game_wait",
            "on_failure": "launch_game_wait",
            "retry": 1,
            "timeout_ms": 10_000,
        },
        {
            "id": "launch_game_wait",
            "action": {"type": "sleep", "ms": 15_000},
            "on_success": "reset_dead_launched",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 20_000,
        },
        {
            "id": "reset_dead_launched",
            "action": {
                "type": "set_variable",
                "key": "dead_count",
                "value": "0",
            },
            "on_success": "scan_all",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "increment_counter",
            "action": {
                "type": "increment_variable",
                "key": "cycle_count",
            },
            "on_success": "check_watchdog",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "check_watchdog",
            "action": {
                "type": "condition",
                "code": "return true",
                "on_true": "scan_all",
                "on_false": "scan_all",
            },
            "on_success": "scan_all",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ══════════════════════════════════════════════════════════════════════
        # ▶ ФАЗА 3: РЕАКТИВНЫЙ SCAN — tap_first_visible + роутинг
        # ══════════════════════════════════════════════════════════════════════
        {
            "id": "scan_all",
            "action": {
                "type": "tap_first_visible",
                "candidates": [
                    {"label": "pw", "selector": "com.br.top:id/password_enter", "strategy": "id"},
                    {"label": "name", "selector": "com.br.top:id/edit_text_name", "strategy": "id"},
                    {"label": "su_remember", "selector": "com.android.settings:id/remember_forever", "strategy": "id"},
                    {"label": "su_allow", "selector": "com.android.settings:id/allow", "strategy": "id"},
                    {"label": "perm_allow", "selector": "com.android.packageinstaller:id/permission_allow_button", "strategy": "id"},
                    {"label": "button_ok", "selector": "com.br.top:id/button_ok", "strategy": "id"},
                    {"label": "button_repeat", "selector": "com.br.top:id/button_repeat", "strategy": "id"},
                    {"label": "but_skip", "selector": "com.br.top:id/but_skip", "strategy": "id"},
                    {"label": "but_continue", "selector": "com.br.top:id/but_continue", "strategy": "id"},
                    {"label": "butt", "selector": "com.br.top:id/butt", "strategy": "id"},
                    {"label": "servers_play", "selector": "com.br.top:id/br_servers_play", "strategy": "id"},
                    {"label": "button_play", "selector": "com.br.top:id/button_play", "strategy": "id"},
                    {"label": "play_butt", "selector": "com.br.top:id/play_butt", "strategy": "id"},
                    {"label": "male_butt", "selector": "com.br.top:id/male_butt", "strategy": "id"},
                    {"label": "arrow_right", "selector": "com.br.top:id/arrow_right", "strategy": "id"},
                    {"label": "dw_ok", "selector": "com.br.top:id/dw_button_ok", "strategy": "id"},
                    {"label": "dw_cancel", "selector": "com.br.top:id/dw_button_cancel", "strategy": "id"},
                    {"label": "all_servers", "selector": "com.br.top:id/all_servers_button", "strategy": "id"},
                    {"label": "reg_butt", "selector": "com.br.top:id/reg_butt", "strategy": "id"},
                    {"label": "invite_nick", "selector": "com.br.top:id/invite_nick", "strategy": "id"},
                    {"label": "servers_list", "selector": "com.br.top:id/list_servers_choose", "strategy": "id"},
                    {"label": "reg_pw", "selector": "com.br.top:id/edit2", "strategy": "id"},
                    {"label": "reg_pw_repeat", "selector": "com.br.top:id/edit3", "strategy": "id"},
                    {"label": "play_but", "selector": "com.br.top:id/play_but", "strategy": "id"},
                    {"label": "auto_switch", "selector": "com.br.top:id/auto_switch", "strategy": "id"},
                    {"label": "text_dalhe", "selector": "\u0414\u0430\u043b\u0435\u0435", "strategy": "text"},
                    {"label": "text_close", "selector": "\u0417\u0410\u041a\u0420\u042b\u0422\u042c", "strategy": "text"},
                    {"label": "text_continue", "selector": "\u041d\u0430\u0436\u043c\u0438\u0442\u0435, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c", "strategy": "text"},
                    {"label": "text_open_x1", "selector": "\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u00d71", "strategy": "text"},
                    {"label": "pkg_install_id", "selector": "com.android.packageinstaller:id/ok_button", "strategy": "id"},
                    {
                        "label": "pkg_install_xpath",
                        "selector": "//android.widget.Button[contains(@text,'\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c') or contains(@text,'Install') or contains(@text,'\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c') or contains(@text,'Update')]",
                        "strategy": "xpath",
                    },
                ],
                "timeout_ms": 5_000,
                "fail_if_not_found": True,
            },
            "on_success": "route_pw",
            "on_failure": "sleep_wait",
            "retry": 0,
            "timeout_ms": 10_000,
        },

        # ══════════════════════════════════════════════════════════════════════
        # ▶ ФАЗА 4: РОУТИНГ ПО ЛЕЙБЛАМИ (Lua-условия)
        # ══════════════════════════════════════════════════════════════════════
        {
            "id": "route_pw",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'pw'",
                "on_true": "reset_counter_pw",
                "on_false": "route_name",
            },
            "on_success": "reset_counter_pw",
            "on_failure": "sleep_ok",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "route_name",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'name'",
                "on_true": "type_name",
                "on_false": "route_play",
            },
            "on_success": "type_name",
            "on_failure": "sleep_ok",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "route_play",
            "action": {
                "type": "condition",
                "code": "local label = ctx.scan_all and ctx.scan_all.tapped_label or ''\nreturn string.find(label, 'play') ~= nil",
                "on_true": "sleep_wait",
                "on_false": "sleep_ok",
            },
            "on_success": "set_phase_playing",
            "on_failure": "sleep_ok",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ══════════════════════════════════════════════════════════════════════
        # ▶ ФАЗА 5: ДЕЙСТВИЯ — ввод пароля, имени, фамилии
        # ══════════════════════════════════════════════════════════════════════
        {
            "id": "reset_counter_pw",
            "action": {
                "type": "set_variable",
                "key": "cycle_count",
                "value": "0",
            },
            "on_success": "sleep_before_type",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "sleep_before_type",
            "action": {"type": "sleep", "ms": 150},
            "on_success": "type_pw",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "type_pw",
            "action": {
                "type": "type_text",
                "text": "NaftaliN1337228",
                "clear_first": True,
            },
            "on_success": "sleep_after_type",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "sleep_after_type",
            "action": {"type": "sleep", "ms": 150},
            "on_success": "tap_play_login",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "tap_play_login",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/play_but",
                "strategy": "id",
                "timeout_ms": 5_000,
            },
            "on_success": "set_phase_playing",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "type_name",
            "action": {
                "type": "type_text",
                "text": "Naftali",
                "clear_first": True,
            },
            "on_success": "tap_surname",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "tap_surname",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/edit_text_surname",
                "strategy": "id",
                "timeout_ms": 5_000,
            },
            "on_success": "type_surname",
            "on_failure": "sleep_ok",
            "retry": 0,
            "timeout_ms": 8_000,
        },
        {
            "id": "type_surname",
            "action": {
                "type": "type_text",
                "text": "Nthree",
                "clear_first": True,
            },
            "on_success": "sleep_ok",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },

        # ══════════════════════════════════════════════════════════════════════
        # ▶ ФАЗЫ SLEEP + PHASE TRACKING
        # ══════════════════════════════════════════════════════════════════════
        {
            "id": "set_phase_playing",
            "action": {
                "type": "set_variable",
                "key": "phase",
                "value": "playing",
            },
            "on_success": "sleep_ok",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "sleep_ok",
            "action": {"type": "sleep", "ms": 500},
            "on_success": "check_game_alive",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "sleep_wait",
            "action": {"type": "sleep", "ms": 5_000},
            "on_success": "check_game_alive",
            "on_failure": "check_game_alive",
            "retry": 0,
            "timeout_ms": 10_000,
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

        # Проверить — существует ли уже
        existing: Script | None = await db.scalar(
            select(Script).where(
                Script.org_id == org_id,
                Script.name == SCRIPT_NAME,
                Script.is_archived.is_(False),
            )
        )
        if existing:
            # Скрипт уже есть — создаём новую версию с обновлённым DAG
            # (stop_app → launch_app → основной флоу)
            from sqlalchemy import func as sa_func
            max_ver = await db.scalar(
                select(sa_func.coalesce(sa_func.max(ScriptVersion.version), 0))
                .where(ScriptVersion.script_id == existing.id)
            )
            new_ver_num = (max_ver or 0) + 1
            new_version = ScriptVersion(
                script_id=existing.id,
                org_id=org_id,
                version=new_ver_num,
                dag=BLACK_RUSSIA_DAG,
                notes=f"v{new_ver_num}: Восстановлен рабочий реактивный watchdog-DAG (v4) + добавлен kill_app → open_app перед стартом.",
            )
            db.add(new_version)
            await db.flush()
            existing.current_version_id = new_version.id
            await db.commit()
            print(f"🔄  Скрипт обновлён: {existing.id}")
            print(f"   Новая версия: {new_version.id} (v{new_ver_num})")
            print(f"   DAG-узлов: {len(BLACK_RUSSIA_DAG['nodes'])}")
            print(f"   Изменение: добавлен stop_app → sleep → launch_app перед логин-флоу")
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
        print("   3. Запусти со страницы Scripts (/scripts) — кнопка Run.")


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
