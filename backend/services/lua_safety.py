# backend/services/lua_safety.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-1. Статический анализ Lua-кода на опасные конструкции.
#
# Блокируемые паттерны:
#   os.execute()  — shell-команды (RCE)
#   io.open()     — файловый ввод-вывод
#   loadfile()    — загрузка произвольных Lua-файлов
#   dofile()      — выполнение произвольных Lua-файлов
#   require()     — импорт модулей (доступ к os/io через них)
#   load()        — динамическая компиляция кода (obfuscation bypass)
from __future__ import annotations

import re

# Паттерны regex для блокировки опасных Lua конструкций
BLOCKED_LUA_PATTERNS: list[str] = [
    r'\bos\s*\.\s*execute\b',
    r'\bio\s*\.\s*open\b',
    r'\bloadfile\b',
    r'\bdofile\b',
    r'\brequire\s*\(',
    r'\bload\s*\(',
]

LUA_SIZE_LIMIT = 50_000  # байт


def check_lua_safety(code: str) -> list[str]:
    """
    Проверить Lua-код на опасные конструкции.

    Возвращает список нарушений (пустой список = код безопасен).
    Проверка case-insensitive для защиты от os.Execute(), OS.EXECUTE() и т.д.
    """
    violations: list[str] = []

    for pattern in BLOCKED_LUA_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            violations.append(f"Blocked pattern: {pattern}")

    if len(code.encode("utf-8")) > LUA_SIZE_LIMIT:
        violations.append(f"Lua code exceeds {LUA_SIZE_LIMIT} bytes limit")

    return violations
