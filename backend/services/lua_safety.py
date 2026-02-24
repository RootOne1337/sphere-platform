# backend/services/lua_safety.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-1. Статический анализ Lua-кода на опасные конструкции.
#
# Блокируемые паттерны:
#   os.execute()      — shell-команды (RCE)
#   io.open()         — файловый ввод-вывод
#   loadfile()        — загрузка произвольных Lua-файлов
#   dofile()          — выполнение произвольных Lua-файлов
#   require()         — импорт модулей (доступ к os/io через них)
#   load()            — динамическая компиляция кода (obfuscation bypass)
#   luajava.*         — JNI-доступ к Java классам (sandbox escape)
#   coroutine.*       — Lua корутины (не прерываются withTimeout)
#   while true do end — бесконечный цикл (CPU DoS)
#   repeat until false — бесконечный цикл (CPU DoS)
from __future__ import annotations

import re

# Паттерны regex для блокировки опасных Lua конструкций
BLOCKED_LUA_PATTERNS: list[str] = [
    # Прямой доступ к shell
    r'\bos\s*\.\s*execute\b',
    r'\bos\s*\.\s*exit\b',
    r'\bos\s*\.\s*getenv\b',
    r'\bos\s*\.\s*remove\b',
    r'\bos\s*\.\s*rename\b',
    # Файловый ввод-вывод
    r'\bio\s*\.\s*open\b',
    r'\bio\s*\.\s*lines\b',
    r'\bio\s*\.\s*read\b',
    # Динамическая загрузка кода
    r'\bloadfile\b',
    r'\bdofile\b',
    r'\brequire\s*\(',
    r'\bload\s*\(',
    r'\bloadstring\s*\(',
    # JNI sandbox escape
    r'\bluajava\b',
    # Lua coroutines — не прерываются withTimeout в JVM
    r'\bcoroutine\s*\.',
    # Метатаблицы (sandbox escape через __index)
    r'\bsetmetatable\s*\(',
    r'\bgetmetatable\s*\(',
    r'\brawset\s*\(',
    r'\brawget\s*\(',
    # Бесконечные циклы (CPU DoS)
    r'\bwhile\s+true\s+do\b',
    r'\brepeat\b.{0,200}\buntil\s+false\b',
    # Debug library
    r'\bdebug\s*\.',
]

LUA_SIZE_LIMIT = 50_000  # байт
# Maximum number of loop iterations heuristic (approximate, not enforced at runtime)
LUA_MAX_INSTRUCTIONS_HINT = 1_000_000


def check_lua_safety(code: str) -> list[str]:
    """
    Проверить Lua-код на опасные конструкции.

    Возвращает список нарушений (пустой список = код безопасен).
    Проверка case-insensitive для защиты от os.Execute(), OS.EXECUTE() и т.д.
    """
    violations: list[str] = []

    for pattern in BLOCKED_LUA_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE | re.DOTALL):
            violations.append(f"Blocked pattern: {pattern}")

    if len(code.encode("utf-8")) > LUA_SIZE_LIMIT:
        violations.append(f"Lua code exceeds {LUA_SIZE_LIMIT} bytes limit")

    return violations
