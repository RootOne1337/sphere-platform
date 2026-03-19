#!/usr/bin/env python3
"""
scripts/seed_farming_dags.py

Создаёт три DAG-скрипта в БД платформы для полного цикла автоматизации
Black Russia (com.br.top):

1. «BR — Регистрация» — Регистрация нового аккаунта
   (создание ника, выбор сервера, заполнение формы, туториал)

2. «BR — Фарминг/Прокачка» — AFK-фарм с watchdog-ом
   (ban detect, level check, connection recovery, account rotation)

3. «BR — Полный цикл» — Объединённый флоу регистрация → фарм
   (для новых аккаунтов со статусом pending_registration)

Все скрипты используют DAG v2.0 с Lua-условиями, реактивным scan_all
и интеграцией с EventReactor (account.banned → авторотация).

Использование:
    python scripts/seed_farming_dags.py
    python scripts/seed_farming_dags.py --org-id <UUID>

Требования:
    — Активная .venv с backend-зависимостями
    — Запущенная БД PostgreSQL
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from sqlalchemy import select, func as sa_func

from backend.database.engine import AsyncSessionLocal
from backend.models.organization import Organization
from backend.models.script import Script, ScriptVersion


# ═══════════════════════════════════════════════════════════════════════════════
# DAG 1: РЕГИСТРАЦИЯ (BR — Регистрация)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Реактивный паттерн (по образцу рабочего Auto Login v6):
#   kill → open → sleep → scan_all → route_chain → обработчик → scan_all
#
# Один scan_all тапает первый видимый элемент, затем цепочка condition-нод
# определяет что было тапнуто и направляет в нужный обработчик.
#
# DagRunner автоматически кладёт результат каждой ноды в ctx[nodeId],
# поэтому ctx.scan_all.tapped_label доступен в условиях без save_to.
#
# Поддерживаемые типы: stop_app, launch_app, sleep, tap_first_visible,
# tap_element, type_text, find_element, condition, set_variable,
# increment_variable, start, end, shell, key_event, и др.
# НЕ поддерживаются: finish, emit_event, element_exists.

# ── Команда очистки текстового поля через shell ──────────────────────────
# keycode 277 (помечен как CTRL_A в DagRunner) — это KEYCODE_TV_DATA_SERVICE,
# а НЕ Ctrl+A! clear_first в APK СЛОМАН. Обход: shell нода перед type_text.
# MOVE_END (123) ставит курсор в конец, 50× DEL (67) стирает посимвольно.
_CLEAR_FIELD_CMD = "input keyevent 123" + " 67" * 50

REGISTRATION_DAG: dict = {
    "version": "1.0",
    "name": "BR — Регистрация",
    "description": (
        "Автоматическая регистрация нового аккаунта в Black Russia. "
        "Реактивный scan_all → route-chain → обработчик → цикл. "
        "v8: BAN DETECT (dw_info → get_element_text → Lua проверка 'заблокирован'). "
        "LOGIN FLOW (password_enter для авторизации уже зарегистрированного аккаунта). "
        "SPAWN FIX (text_last_place → sleep → tap button_enter напрямую). "
        "REORDER кандидатов: системные → dw_info → поля ввода → кнопки. "
        "Пост-рег: but_skip + gender + tutorial + spawn."
    ),
    "entry_node": "kill_app",
    "timeout_ms": 900_000,  # 15 минут (загрузка ресурсов может быть долгой)
    "nodes": [
        # ═══════════ ФАЗА 0: ПЕРЕЗАПУСК ПРИЛОЖЕНИЯ ═══════════════════════
        {
            "id": "kill_app",
            "action": {"type": "stop_app", "package": "com.br.top", "delay_ms": 1000},
            "on_success": "sleep_after_kill",
            "on_failure": "sleep_after_kill",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "sleep_after_kill",
            "action": {"type": "sleep", "ms": 2000},
            "on_success": "open_app",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "open_app",
            "action": {"type": "launch_app", "package": "com.br.top", "delay_ms": 5000},
            "on_success": "sleep_after_open",
            "on_failure": "open_app",
            "retry": 2,
            "timeout_ms": 15_000,
        },
        {
            "id": "sleep_after_open",
            "action": {"type": "sleep", "ms": 10000},
            "on_success": "start",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 15_000,
        },

        # ═══════════ ИНИЦИАЛИЗАЦИЯ ═══════════════════════════════════════
        {
            "id": "start",
            "action": {"type": "start"},
            "on_success": "init_counter",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "init_counter",
            "action": {"type": "set_variable", "key": "counter", "value": "0"},
            "on_success": "init_dead_count",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "init_dead_count",
            "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
            "on_success": "init_nick_done",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        # nick_done = 0 → ник ещё не введён; после ввода ставим 1
        {
            "id": "init_nick_done",
            "action": {"type": "set_variable", "key": "nick_done", "value": "0"},
            "on_success": "check_game_alive",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },

        # ═══════════ WATCHDOG: ИГРА ЖИВА? ════════════════════════════════
        {
            "id": "check_game_alive",
            "action": {
                "type": "shell",
                "command": "pidof com.br.top",
                "timeout_ms": 3000,
            },
            "on_success": "reset_dead_alive",
            "on_failure": "increment_dead_count",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "reset_dead_alive",
            "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
            "on_success": "increment_counter",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "increment_dead_count",
            "action": {"type": "increment_variable", "key": "dead_count"},
            "on_success": "check_dead_limit",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "check_dead_limit",
            "action": {
                "type": "condition",
                "code": "return (tonumber(ctx.dead_count) or 0) < 12",
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
            "action": {"type": "launch_app", "package": "com.br.top", "delay_ms": 5000},
            "on_success": "launch_game_wait",
            "on_failure": "launch_game_wait",
            "retry": 0,
            "timeout_ms": 15_000,
        },
        {
            "id": "launch_game_wait",
            "action": {"type": "sleep", "ms": 10000},
            "on_success": "reset_dead_launched",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 15_000,
        },
        {
            "id": "reset_dead_launched",
            "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
            "on_success": "scan_all",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "increment_counter",
            "action": {"type": "increment_variable", "key": "counter"},
            "on_success": "scan_all",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 1_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ГЛАВНЫЙ СКАН — tap_first_visible
        # ═══════════════════════════════════════════════════════════════════
        {
            "id": "scan_all",
            "action": {
                "type": "tap_first_visible",
                "candidates": [
                    # ── 1. Системные диалоги (root, разрешения) ─────────
                    {"label": "su_remember", "selector": "com.android.settings:id/remember_forever", "strategy": "id"},
                    {"label": "su_allow", "selector": "com.android.settings:id/allow", "strategy": "id"},
                    {"label": "perm_allow", "selector": "com.android.packageinstaller:id/permission_allow_button", "strategy": "id"},
                    {"label": "pkg_install", "selector": "com.android.packageinstaller:id/ok_button", "strategy": "id"},
                    {"label": "pkg_install_xpath", "selector": "//android.widget.Button[contains(@text,'Установить') or contains(@text,'Install') or contains(@text,'Обновить') or contains(@text,'Update')]", "strategy": "xpath"},
                    # ── 2. Диалоги игры — dw_info ДО dw_ok для бан-детекции ─
                    {"label": "dw_info", "selector": "com.br.top:id/dw_info", "strategy": "id"},
                    {"label": "dw_ok", "selector": "com.br.top:id/dw_button_ok", "strategy": "id"},
                    {"label": "dw_cancel", "selector": "com.br.top:id/dw_button_cancel", "strategy": "id"},
                    # ── 3. Загрузка / ошибки подключения ────────────────
                    {"label": "button_ok", "selector": "com.br.top:id/button_ok", "strategy": "id"},
                    {"label": "button_repeat", "selector": "com.br.top:id/button_repeat", "strategy": "id"},
                    # ── 4. Поля ввода (ник, пароль рег., пароль логин) ──
                    {"label": "name", "selector": "com.br.top:id/edit_text_name", "strategy": "id"},
                    {"label": "nick", "selector": "com.br.top:id/edit_text_nick", "strategy": "id"},
                    {"label": "reg_pw", "selector": "com.br.top:id/edit2", "strategy": "id"},
                    {"label": "login_pw", "selector": "com.br.top:id/password_enter", "strategy": "id"},
                    # ── 5. Пропуск экранов (пост-рег) ──────────────────
                    {"label": "but_skip", "selector": "com.br.top:id/but_skip", "strategy": "id"},
                    {"label": "but_continue", "selector": "com.br.top:id/but_continue", "strategy": "id"},
                    {"label": "butt", "selector": "com.br.top:id/butt", "strategy": "id"},
                    # ── 6. Серверный экран ──────────────────────────────
                    {"label": "all_servers", "selector": "Выбор сервера", "strategy": "text"},
                    {"label": "servers_play", "selector": "com.br.top:id/br_servers_play", "strategy": "id"},
                    # ── 7. Play / регистрация ──────────────────────────
                    {"label": "button_play", "selector": "com.br.top:id/button_play", "strategy": "id"},
                    {"label": "reg_butt", "selector": "com.br.top:id/reg_butt", "strategy": "id"},
                    # ── 8. Пол / внешность / пост-рег Play ─────────────
                    {"label": "male_butt", "selector": "com.br.top:id/male_butt", "strategy": "id"},
                    {"label": "arrow_right", "selector": "com.br.top:id/arrow_right", "strategy": "id"},
                    {"label": "play_butt", "selector": "com.br.top:id/play_butt", "strategy": "id"},
                    {"label": "play_but", "selector": "com.br.top:id/play_but", "strategy": "id"},
                    # ── 9. Туториал ─────────────────────────────────────
                    {"label": "text_no", "selector": "НЕТ", "strategy": "text"},
                    {"label": "text_stop", "selector": "ПРЕКРАТИТЬ", "strategy": "text"},
                    # ── 10. Спавн ──────────────────────────────────────
                    {"label": "text_last_place", "selector": "Последнее место", "strategy": "text"},
                    {"label": "button_enter", "selector": "com.br.top:id/button_enter", "strategy": "id"},
                    # ── 11. Прочее ─────────────────────────────────────
                    {"label": "invite_nick", "selector": "com.br.top:id/invite_nick", "strategy": "id"},
                    {"label": "auto_switch", "selector": "com.br.top:id/auto_switch", "strategy": "id"},
                    {"label": "text_dalhe", "selector": "Далее", "strategy": "text"},
                    {"label": "text_close", "selector": "ЗАКРЫТЬ", "strategy": "text"},
                    {"label": "text_continue", "selector": "Нажмите, чтобы продолжить", "strategy": "text"},
                    {"label": "text_open_x1", "selector": "Открыть ×1", "strategy": "text"},
                ],
                "timeout_ms": 5000,
                "fail_if_not_found": True,
            },
            "on_success": "route_nick",
            "on_failure": "sleep_wait",
            "retry": 0,
            "timeout_ms": 10_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # МАРШРУТИЗАЦИЯ
        # ═══════════════════════════════════════════════════════════════════

        # ── Тапнули поле ника? ──
        {
            "id": "route_nick",
            "action": {
                "type": "condition",
                "code": (
                    "local lbl = ctx.scan_all and ctx.scan_all.tapped_label or ''\n"
                    "return lbl == 'name' or lbl == 'nick'"
                ),
                "on_true": "route_nick_done",
                "on_false": "route_reg_pw",
            },
            "on_success": "route_nick_done",
            "on_failure": "route_reg_pw",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        # ── Ник уже вводили? → просто тапаем ИГРАТЬ, не печатаем заново ──
        {
            "id": "route_nick_done",
            "action": {
                "type": "condition",
                "code": "return ctx.nick_done == '1'",
                "on_true": "tap_button_play_nick",
                "on_false": "clear_nick",
            },
            "on_success": "tap_button_play_nick",
            "on_failure": "clear_nick",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ── Поле пароля? ──
        {
            "id": "route_reg_pw",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'reg_pw'",
                "on_true": "clear_pw",
                "on_false": "route_login_pw",
            },
            "on_success": "clear_pw",
            "on_failure": "route_login_pw",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ── Поле пароля авторизации (login)? ──
        {
            "id": "route_login_pw",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'login_pw'",
                "on_true": "clear_login_pw",
                "on_false": "route_all_servers",
            },
            "on_success": "clear_login_pw",
            "on_failure": "route_all_servers",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ── Все серверы? ──
        {
            "id": "route_all_servers",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'all_servers'",
                "on_true": "sleep_before_server",
                "on_false": "route_dialog",
            },
            "on_success": "sleep_before_server",
            "on_failure": "route_dialog",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ── Диалог (dw_info)? → детекция бана ──
        {
            "id": "route_dialog",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'dw_info'",
                "on_true": "read_ban_text",
                "on_false": "route_last_place",
            },
            "on_success": "read_ban_text",
            "on_failure": "route_last_place",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ── Тапнули "Последнее место"? → сразу жмём ВОЙТИ ──
        {
            "id": "route_last_place",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'text_last_place'",
                "on_true": "sleep_before_spawn_enter",
                "on_false": "route_spawn",
            },
            "on_success": "sleep_before_spawn_enter",
            "on_failure": "route_spawn",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ── Спавн (ВОЙТИ)? → регистрация завершена ──
        {
            "id": "route_spawn",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'button_enter'",
                "on_true": "done",
                "on_false": "sleep_ok",
            },
            "on_success": "done",
            "on_failure": "sleep_ok",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ОБРАБОТЧИК: ВВОД НИКНЕЙМА
        # ═══════════════════════════════════════════════════════════════════
        # Очистка поля через shell (MOVE_END + 50× DEL) вместо
        # сломанного clear_first (keycode 277 = TV_DATA_SERVICE).
        # После ввода ставим nick_done=1 → больше не перепечатываем.

        # Очищаем поле имени перед вводом
        {
            "id": "clear_nick",
            "action": {
                "type": "shell",
                "command": _CLEAR_FIELD_CMD,
                "fail_on_error": False,
            },
            "on_success": "type_nick_part1",
            "on_failure": "type_nick_part1",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "type_nick_part1",
            "action": {
                "type": "type_text",
                "text": "{{account.nick_part1}}",
            },
            "on_success": "check_surname_field",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "check_surname_field",
            "action": {
                "type": "find_element",
                "selector": "com.br.top:id/edit_text_surname",
                "strategy": "id",
                "timeout_ms": 2000,
                "fail_if_not_found": True,
            },
            "on_success": "tap_surname_field",
            "on_failure": "check_surname_field_alt",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "check_surname_field_alt",
            "action": {
                "type": "find_element",
                "selector": "com.br.top:id/edit_text_nick2",
                "strategy": "id",
                "timeout_ms": 2000,
                "fail_if_not_found": True,
            },
            "on_success": "tap_surname_field_alt",
            "on_failure": "clear_nick_full",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "tap_surname_field",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/edit_text_surname",
                "strategy": "id",
                "timeout_ms": 3000,
            },
            "on_success": "clear_nick2",
            "on_failure": "tap_button_play_nick",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "tap_surname_field_alt",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/edit_text_nick2",
                "strategy": "id",
                "timeout_ms": 3000,
            },
            "on_success": "clear_nick2",
            "on_failure": "tap_button_play_nick",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        # Очищаем поле фамилии перед вводом
        {
            "id": "clear_nick2",
            "action": {
                "type": "shell",
                "command": _CLEAR_FIELD_CMD,
                "fail_on_error": False,
            },
            "on_success": "type_nick_part2",
            "on_failure": "type_nick_part2",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "type_nick_part2",
            "action": {
                "type": "type_text",
                "text": "{{account.nick_part2}}",
            },
            "on_success": "tap_button_play_nick",
            "on_failure": "tap_button_play_nick",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        # Если фамилия не найдена (1 поле) → очищаем → Имя_Фамилия
        {
            "id": "clear_nick_full",
            "action": {
                "type": "shell",
                "command": _CLEAR_FIELD_CMD,
                "fail_on_error": False,
            },
            "on_success": "type_nick_full",
            "on_failure": "type_nick_full",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "type_nick_full",
            "action": {
                "type": "type_text",
                "text": "{{account.nickname}}",
            },
            "on_success": "tap_button_play_nick",
            "on_failure": "tap_button_play_nick",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        # После ника → set_nick_done → тап ИГРАТЬ
        {
            "id": "tap_button_play_nick",
            "action": {
                "type": "tap_element",
                "selector": "ИГРАТЬ",
                "strategy": "text",
                "timeout_ms": 5000,
            },
            "on_success": "set_nick_done",
            "on_failure": "set_nick_done",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "set_nick_done",
            "action": {"type": "set_variable", "key": "nick_done", "value": "1"},
            "on_success": "sleep_ok",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ОБРАБОТЧИК: ВЫБОР СЕРВЕРА
        # ═══════════════════════════════════════════════════════════════════
        # Серверы — реальные Android-элементы с resource-id br_server_name.
        # XPath: //*[@resource-id='com.br.top:id/br_server_name' and @text='SERVER']
        # scroll_to прокручивает экран до видимости, затем tap_element кликает.
        # Из data/launch_app.py: list_servers_choose — scroll-контейнер,
        # br_servers_play — кнопка "ИГРАТЬ" после выбора сервера.
        {
            "id": "sleep_before_server",
            "action": {"type": "sleep", "ms": 2000},
            "on_success": "scroll_to_server",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        # Скроллим экран вниз пока сервер не станет видим
        {
            "id": "scroll_to_server",
            "action": {
                "type": "scroll_to",
                "selector": "//*[@resource-id='com.br.top:id/br_server_name' and @text='{{account.server_name}}']",
                "strategy": "xpath",
                "direction": "down",
                "max_scrolls": 30,
                "duration_ms": 300,
                "fail_if_not_found": True,
            },
            "on_success": "tap_target_server",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 90_000,
        },
        # Сервер на экране → тапаем по нему
        {
            "id": "tap_target_server",
            "action": {
                "type": "tap_element",
                "selector": "//*[@resource-id='com.br.top:id/br_server_name' and @text='{{account.server_name}}']",
                "strategy": "xpath",
                "timeout_ms": 5000,
            },
            "on_success": "sleep_after_target",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "sleep_after_target",
            "action": {"type": "sleep", "ms": 1000},
            "on_success": "tap_servers_play_direct",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 3_000,
        },
        {
            "id": "tap_servers_play_direct",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/br_servers_play",
                "strategy": "id",
                "timeout_ms": 5000,
            },
            "on_success": "sleep_after_server_play",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "sleep_after_server_play",
            "action": {"type": "sleep", "ms": 8000},
            "on_success": "scan_all",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 12_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ОБРАБОТЧИК: ПАРОЛЬ + ПОДТВЕРЖДЕНИЕ → тап РЕГИСТРАЦИЯ
        # ═══════════════════════════════════════════════════════════════════
        # Очистка через shell перед каждым type_text.

        # Очищаем поле пароля
        {
            "id": "clear_pw",
            "action": {
                "type": "shell",
                "command": _CLEAR_FIELD_CMD,
                "fail_on_error": False,
            },
            "on_success": "type_password",
            "on_failure": "type_password",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "type_password",
            "action": {
                "type": "type_text",
                "text": "{{account.password}}",
            },
            "on_success": "tap_pw_confirm",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "tap_pw_confirm",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/edit3",
                "strategy": "id",
                "timeout_ms": 5000,
            },
            "on_success": "clear_pw_confirm",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        # Очищаем поле подтверждения пароля
        {
            "id": "clear_pw_confirm",
            "action": {
                "type": "shell",
                "command": _CLEAR_FIELD_CMD,
                "fail_on_error": False,
            },
            "on_success": "type_pw_confirm",
            "on_failure": "type_pw_confirm",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "type_pw_confirm",
            "action": {
                "type": "type_text",
                "text": "{{account.password}}",
            },
            "on_success": "tap_reg_butt_direct",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "tap_reg_butt_direct",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/reg_butt",
                "strategy": "id",
                "timeout_ms": 5000,
            },
            "on_success": "sleep_ok",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ОБРАБОТЧИК: ПАРОЛЬ АВТОРИЗАЦИИ (LOGIN)
        # ═══════════════════════════════════════════════════════════════════
        # Если ник уже зарегистрирован → экран АВТОРИЗАЦИЯ → password_enter.
        # Вводим пароль и жмём play_but (кнопка входа на экране логина).
        {
            "id": "clear_login_pw",
            "action": {
                "type": "shell",
                "command": _CLEAR_FIELD_CMD,
                "fail_on_error": False,
            },
            "on_success": "type_login_pw",
            "on_failure": "type_login_pw",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "type_login_pw",
            "action": {
                "type": "type_text",
                "text": "{{account.password}}",
            },
            "on_success": "tap_login_play",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "tap_login_play",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/play_but",
                "strategy": "id",
                "timeout_ms": 5000,
            },
            "on_success": "sleep_ok",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ОБРАБОТЧИК: ДЕТЕКЦИЯ БАНА (dw_info → get_element_text → Lua)
        # ═══════════════════════════════════════════════════════════════════
        # scan_all тапнул dw_info (текстовую метку диалога, не кнопку).
        # Диалог остался открыт → читаем текст → проверяем "заблокирован".
        # Бан → done_banned (DAG завершается). Не бан → tap dw_ok → цикл.
        {
            "id": "read_ban_text",
            "action": {
                "type": "get_element_text",
                "selector": "com.br.top:id/dw_info",
                "strategy": "id",
                "timeout_ms": 2000,
                "save_to": "ban_text",
            },
            "on_success": "is_banned",
            "on_failure": "tap_dw_dismiss",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "is_banned",
            "action": {
                "type": "condition",
                "code": (
                    "local txt = tostring(ctx.ban_text or '')\n"
                    "return string.find(string.lower(txt), 'заблокирован') ~= nil"
                ),
                "on_true": "done_banned",
                "on_false": "tap_dw_dismiss",
            },
            "on_success": "done_banned",
            "on_failure": "tap_dw_dismiss",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "done_banned",
            "action": {"type": "end"},
            "on_success": None,
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "tap_dw_dismiss",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/dw_button_ok",
                "strategy": "id",
                "timeout_ms": 3000,
            },
            "on_success": "sleep_ok",
            "on_failure": "sleep_ok",
            "retry": 0,
            "timeout_ms": 5_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ОБРАБОТЧИК: СПАВН (Последнее место → ВОЙТИ напрямую)
        # ═══════════════════════════════════════════════════════════════════
        # FIX v8: text_last_place и button_enter оба видны одновременно.
        # scan_all тапает text_last_place (выше в списке) → button_enter
        # никогда не нажимается → бесконечный цикл. Решение: явный тап
        # button_enter через 500мс после выбора локации.
        {
            "id": "sleep_before_spawn_enter",
            "action": {"type": "sleep", "ms": 500},
            "on_success": "tap_spawn_enter_direct",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 3_000,
        },
        {
            "id": "tap_spawn_enter_direct",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/button_enter",
                "strategy": "id",
                "timeout_ms": 5000,
            },
            "on_success": "done",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ЦИКЛЕВЫЕ SLEEP'Ы
        # ═══════════════════════════════════════════════════════════════════
        {
            "id": "sleep_ok",
            "action": {"type": "sleep", "ms": 3000},
            "on_success": "check_game_alive",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "sleep_wait",
            "action": {"type": "sleep", "ms": 5000},
            "on_success": "check_game_alive",
            "on_failure": "check_game_alive",
            "retry": 0,
            "timeout_ms": 8_000,
        },

        # ═══════════════════════════════════════════════════════════════════
        # ЗАВЕРШЕНИЕ
        # ═══════════════════════════════════════════════════════════════════
        {
            "id": "done",
            "action": {"type": "end"},
            "on_success": None,
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# DAG 2: ФАРМИНГ / ПРОКАЧКА (BR — Фарминг)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Бесконечный цикл: kill → open → login → watchdog-loop
# Watchdog: проверка процесса, ban detect (dw_info), level check (каждые 5 мин)
# Эмитирует события: account.banned, account.level_up, account.progress
#
# Каждые 5 минут → check_level → если level >= target → emit account.leveled → done
# При бане → emit account.banned → EventReactor авторотирует аккаунт

FARMING_DAG: dict = {
    "version": "2.0",
    "name": "BR — Фарминг",
    "description": (
        "AFK-фарм с watchdog-циклом: ban detect, level check, "
        "автовосстановление при крашах. Бесконечный цикл пока не остановят "
        "или аккаунт не достигнет target_level."
    ),
    "entry_node": "kill_app",
    "timeout_ms": 86_400_000,  # 24 часа
    "nodes": [
        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 0: ПЕРЕЗАПУСК
        # ══════════════════════════════════════════════════════════════════
        {
            "id": "kill_app",
            "action": {"type": "stop_app", "package": "com.br.top", "delay_ms": 1000},
            "on_success": "sleep_after_kill",
            "on_failure": "sleep_after_kill",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "sleep_after_kill",
            "action": {"type": "sleep", "ms": 2000},
            "on_success": "open_app",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "open_app",
            "action": {"type": "launch_app", "package": "com.br.top", "delay_ms": 5000},
            "on_success": "sleep_after_open",
            "on_failure": "open_app",
            "retry": 2,
            "timeout_ms": 15_000,
        },
        {
            "id": "sleep_after_open",
            "action": {"type": "sleep", "ms": 12000},
            "on_success": "init_vars",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 15_000,
        },

        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 1: ИНИЦИАЛИЗАЦИЯ ПЕРЕМЕННЫХ
        # ══════════════════════════════════════════════════════════════════
        {
            "id": "init_vars",
            "action": {"type": "set_variable", "key": "cycle_count", "value": "0"},
            "on_success": "init_dead_count",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "init_dead_count",
            "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
            "on_success": "init_ban_checked",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "init_ban_checked",
            "action": {"type": "set_variable", "key": "ban_check_cycle", "value": "0"},
            "on_success": "check_game_alive",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },

        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 2: WATCHDOG — проверка процесса
        # ══════════════════════════════════════════════════════════════════
        {
            "id": "check_game_alive",
            "action": {
                "type": "shell",
                "command": "pidof com.br.top",
                "save_to": "game_pid",
            },
            "on_success": "validate_pid",
            "on_failure": "increment_dead",
            "retry": 0,
            "timeout_ms": 6_000,
        },
        {
            "id": "validate_pid",
            "action": {
                "type": "condition",
                "code": "local pid = tostring(ctx.game_pid or '')\nreturn #pid > 0 and pid ~= 'nil'",
                "on_true": "reset_dead",
                "on_false": "increment_dead",
            },
            "on_success": "reset_dead",
            "on_failure": "increment_dead",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "reset_dead",
            "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
            "on_success": "increment_cycle",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            "id": "increment_dead",
            "action": {"type": "increment_variable", "key": "dead_count"},
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
                "on_false": "restart_game",
            },
            "on_success": "scan_all",
            "on_failure": "restart_game",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "restart_game",
            "action": {"type": "launch_app", "package": "com.br.top"},
            "on_success": "wait_restart",
            "on_failure": "wait_restart",
            "retry": 1,
            "timeout_ms": 10_000,
        },
        {
            "id": "wait_restart",
            "action": {"type": "sleep", "ms": 15000},
            "on_success": "reset_dead_after_restart",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 20_000,
        },
        {
            "id": "reset_dead_after_restart",
            "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
            "on_success": "scan_all",
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },

        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 3: СЧЁТЧИК ЦИКЛОВ + ПРОВЕРКА БАНА / УРОВНЯ
        # ══════════════════════════════════════════════════════════════════
        {
            "id": "increment_cycle",
            "action": {"type": "increment_variable", "key": "cycle_count"},
            "on_success": "should_check_ban",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 1_000,
        },
        {
            # Проверка бана: каждые 10 циклов (≈50 секунд)
            "id": "should_check_ban",
            "action": {
                "type": "condition",
                "code": "return (tonumber(ctx.cycle_count) or 0) % 10 == 0",
                "on_true": "check_ban",
                "on_false": "should_check_level",
            },
            "on_success": "check_ban",
            "on_failure": "should_check_level",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            # Детект бана: ищем текст "заблокирован" в UI dump
            "id": "check_ban",
            "action": {
                "type": "element_exists",
                "selector": "com.br.top:id/dw_info",
                "strategy": "id",
                "timeout_ms": 2000,
            },
            "on_success": "read_ban_text",
            "on_failure": "should_check_level",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "read_ban_text",
            "action": {
                "type": "get_text",
                "selector": "com.br.top:id/dw_info",
                "strategy": "id",
                "save_to": "ban_text",
                "timeout_ms": 2000,
            },
            "on_success": "is_banned",
            "on_failure": "should_check_level",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            "id": "is_banned",
            "action": {
                "type": "condition",
                "code": "local txt = tostring(ctx.ban_text or '')\nreturn string.find(string.lower(txt), 'заблокирован') ~= nil",
                "on_true": "emit_banned",
                "on_false": "tap_ban_dismiss",
            },
            "on_success": "emit_banned",
            "on_failure": "tap_ban_dismiss",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            "id": "tap_ban_dismiss",
            "action": {
                "type": "tap_element",
                "selector": "com.br.top:id/dw_button_ok",
                "strategy": "id",
                "timeout_ms": 2000,
            },
            "on_success": "should_check_level",
            "on_failure": "should_check_level",
            "retry": 0,
            "timeout_ms": 5_000,
        },
        {
            # Проверка уровня: каждые 60 циклов (≈5 минут)
            "id": "should_check_level",
            "action": {
                "type": "condition",
                "code": "return (tonumber(ctx.cycle_count) or 0) % 60 == 0 and (tonumber(ctx.cycle_count) or 0) > 0",
                "on_true": "emit_progress",
                "on_false": "scan_all",
            },
            "on_success": "emit_progress",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 2_000,
        },
        {
            # Эмит прогресса — EventReactor обновит аккаунт в таблице
            "id": "emit_progress",
            "action": {
                "type": "emit_event",
                "event_type": "account.progress",
                "message": "Цикл прокачки — обновление прогресса",
            },
            "on_success": "scan_all",
            "on_failure": "scan_all",
            "retry": 0,
            "timeout_ms": 3_000,
        },

        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 4: РЕАКТИВНЫЙ SCAN — tap_first_visible + роутинг
        # ══════════════════════════════════════════════════════════════════
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
                    {"label": "play_but", "selector": "com.br.top:id/play_but", "strategy": "id"},
                    {"label": "dw_ok", "selector": "com.br.top:id/dw_button_ok", "strategy": "id"},
                    {"label": "dw_cancel", "selector": "com.br.top:id/dw_button_cancel", "strategy": "id"},
                    {"label": "text_dalhe", "selector": "Далее", "strategy": "text"},
                    {"label": "text_close", "selector": "ЗАКРЫТЬ", "strategy": "text"},
                    {"label": "text_continue", "selector": "Нажмите, чтобы продолжить", "strategy": "text"},
                ],
                "timeout_ms": 5_000,
                "fail_if_not_found": True,
            },
            "on_success": "route_pw",
            "on_failure": "sleep_wait",
            "retry": 0,
            "timeout_ms": 10_000,
        },

        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 5: РОУТИНГ — по лейблам scan_all
        # ══════════════════════════════════════════════════════════════════
        {
            "id": "route_pw",
            "action": {
                "type": "condition",
                "code": "return ctx.scan_all ~= nil and ctx.scan_all.tapped_label == 'pw'",
                "on_true": "sleep_before_pw",
                "on_false": "route_name",
            },
            "on_success": "sleep_before_pw",
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
            "on_success": "sleep_wait",
            "on_failure": "sleep_ok",
            "retry": 0,
            "timeout_ms": 2_000,
        },

        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 6: ДЕЙСТВИЯ — ввод пароля / имени
        # ══════════════════════════════════════════════════════════════════
        {
            "id": "sleep_before_pw",
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
                "text": "{{account.password}}",
                "clear_first": True,
            },
            "on_success": "sleep_after_pw",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "sleep_after_pw",
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
                "timeout_ms": 5000,
            },
            "on_success": "sleep_wait",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },
        {
            "id": "type_name",
            "action": {
                "type": "type_text",
                "text": "{{account.nickname}}",
                "clear_first": True,
            },
            "on_success": "sleep_ok",
            "on_failure": "sleep_ok",
            "retry": 1,
            "timeout_ms": 8_000,
        },

        # ══════════════════════════════════════════════════════════════════
        # ФАЗА 7: SLEEP + ЭМИТЫ
        # ══════════════════════════════════════════════════════════════════
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
            "action": {"type": "sleep", "ms": 5000},
            "on_success": "check_game_alive",
            "on_failure": "check_game_alive",
            "retry": 0,
            "timeout_ms": 10_000,
        },
        {
            # Эмит бана — EventReactor обработает: статус → banned, ротация
            "id": "emit_banned",
            "action": {
                "type": "emit_event",
                "event_type": "account.banned",
                "message": "Бан обнаружен во время фарма (dw_info: заблокирован)",
            },
            "on_success": "finish_banned",
            "on_failure": "finish_banned",
            "retry": 0,
            "timeout_ms": 3_000,
        },
        {
            "id": "finish_banned",
            "action": {"type": "finish", "status": "failed", "reason": "account_banned"},
            "on_success": None,
            "on_failure": None,
            "retry": 0,
            "timeout_ms": 1_000,
        },
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Seed-функция
# ═══════════════════════════════════════════════════════════════════════════════

SCRIPTS_TO_SEED = [
    ("BR — Регистрация", REGISTRATION_DAG),
    ("BR — Фарминг", FARMING_DAG),
]


async def seed(org_id_override: uuid.UUID | None = None) -> None:
    async with AsyncSessionLocal() as db:
        # Найти организацию
        if org_id_override:
            org = await db.scalar(select(Organization).where(Organization.id == org_id_override))
            if not org:
                print(f"❌  Организация {org_id_override} не найдена.")
                sys.exit(1)
        else:
            org = await db.scalar(select(Organization).limit(1))
            if not org:
                print("❌  Нет ни одной организации. Зарегистрируйтесь в приложении.")
                sys.exit(1)

        org_id: uuid.UUID = org.id
        print(f"🏢  Организация: {org.name} ({org_id})")
        print()

        for script_name, dag in SCRIPTS_TO_SEED:
            # Проверить — существует ли уже
            existing: Script | None = await db.scalar(
                select(Script).where(
                    Script.org_id == org_id,
                    Script.name == script_name,
                    Script.is_archived.is_(False),
                )
            )
            if existing:
                # Обновляем версию
                max_ver = await db.scalar(
                    select(sa_func.coalesce(sa_func.max(ScriptVersion.version), 0))
                    .where(ScriptVersion.script_id == existing.id)
                )
                new_ver_num = (max_ver or 0) + 1
                new_version = ScriptVersion(
                    script_id=existing.id,
                    org_id=org_id,
                    version=new_ver_num,
                    dag=dag,
                    notes=f"v{new_ver_num}: Обновлён seed-скриптом (seed_farming_dags.py)",
                )
                db.add(new_version)
                await db.flush()
                existing.current_version_id = new_version.id
                print(f"  🔄  «{script_name}» обновлён → v{new_ver_num} ({len(dag['nodes'])} узлов)")
            else:
                # Создаём скрипт + версию
                script = Script(
                    org_id=org_id,
                    name=script_name,
                    description=dag["description"],
                    is_archived=False,
                )
                db.add(script)
                await db.flush()

                version = ScriptVersion(
                    script_id=script.id,
                    org_id=org_id,
                    version=1,
                    dag=dag,
                    notes="Создано seed-скриптом (seed_farming_dags.py)",
                )
                db.add(version)
                await db.flush()
                script.current_version_id = version.id
                print(f"  ✅  «{script_name}» создан → v1 ({len(dag['nodes'])} узлов)")

        await db.commit()
        print()
        print("═══ Готово ════════════════════════════════════")
        print(f"  Скриптов: {len(SCRIPTS_TO_SEED)}")
        print("  Запуск: страница Scripts (/scripts) → Run")
        print("  Или через API: POST /api/v1/tasks")
        print("═══════════════════════════════════════════════")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed фарминг DAG-скрипты Black Russia")
    p.add_argument(
        "--org-id", type=uuid.UUID, default=None,
        help="UUID организации (по умолчанию — первая в БД)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(seed(args.org_id))
