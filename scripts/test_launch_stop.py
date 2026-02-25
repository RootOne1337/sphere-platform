#!/usr/bin/env python3
"""
Тест-скрипт: запуск com.br.top → ожидание 25 секунд → принудительная остановка.

Использует ADB напрямую (не требует запущенного backend/API).
Запуск:  python scripts/test_launch_stop.py
"""
from __future__ import annotations

import subprocess
import sys
import time

PACKAGE = "com.br.top"
WAIT_SEC = 25        # сколько секунд держать приложение запущенным
ADB_TIMEOUT = 30     # таймаут каждой ADB-команды, сек

# ─── Helpers ──────────────────────────────────────────────────────────────────

def adb(*args: str) -> str:
    """Выполнить `adb shell <args>`, вернуть stdout."""
    result = subprocess.run(
        ["adb", "shell", *args],
        capture_output=True, text=True, timeout=ADB_TIMEOUT,
    )
    return result.stdout.strip()


def adb_root(*args: str) -> str:
    """Выполнить команду через su (для устройств с root)."""
    cmd = " ".join(args)
    return adb("su", "-c", cmd)


def banner(msg: str) -> None:
    print(f"\n{'─' * 50}\n  {msg}\n{'─' * 50}")


# ─── Test steps ───────────────────────────────────────────────────────────────

def step_wake_screen() -> None:
    banner("1. Пробуждение экрана")
    adb("input keyevent 224")         # KEYCODE_WAKEUP
    time.sleep(0.8)
    print("  ✓ Экран разбужен")


def step_launch_app() -> None:
    banner(f"2. Запуск приложения: {PACKAGE}")
    # monkey гарантирует запуск Launcher intent без знания Activity
    out = adb("monkey", "-p", PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")
    if out:
        print(f"  monkey: {out[:120]}")
    time.sleep(2)

    pid = adb("pidof", PACKAGE)
    if pid:
        print(f"  ✓ Приложение запущено, PID = {pid}")
    else:
        print(f"  ✗ Приложение не запустилось! Пакет {PACKAGE!r} присутствует на устройстве?",
              file=sys.stderr)
        # Попытаемся через am start как fallback
        print("  Пробуем am start -n fallback...")
        adb_root(f"am start -n {PACKAGE}/.MainActivity")
        time.sleep(2)
        pid2 = adb("pidof", PACKAGE)
        if not pid2:
            print("  ✗ Оба метода запуска провалились.", file=sys.stderr)
            sys.exit(1)
        print(f"  ✓ Запущено через am start, PID = {pid2}")


def step_wait() -> None:
    banner(f"3. Ожидание {WAIT_SEC} сек (приложение работает)")
    for remaining in range(WAIT_SEC, 0, -5):
        pid = adb("pidof", PACKAGE)
        status = f"PID={pid}" if pid else "⚠ приложение уже не запущено"
        print(f"  {remaining:>3}с | {status}")
        time.sleep(5)


def step_stop_app() -> None:
    banner(f"4. Остановка приложения: am force-stop {PACKAGE}")
    adb_root(f"am force-stop {PACKAGE}")
    time.sleep(1)

    pid_after = adb("pidof", PACKAGE)
    if not pid_after:
        print(f"  ✓ Приложение остановлено (PID не найден)")
    else:
        print(f"  ⚠ PID ещё активен: {pid_after}  (возможно activity manager не успел)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n═══════ ТЕСТ: launch → wait → stop ═══════")
    print(f"Пакет : {PACKAGE}")
    print(f"Ожидание: {WAIT_SEC} сек")

    # Проверяем наличие ADB
    try:
        devices = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
        lines = [l for l in devices.stdout.splitlines()[1:] if l.strip() and "offline" not in l]
        if not lines:
            print("✗ Нет подключённых устройств (adb devices пуст)", file=sys.stderr)
            sys.exit(1)
        print(f"Устройство: {lines[0].split()[0]}")
    except FileNotFoundError:
        print("✗ ADB не найден в PATH", file=sys.stderr)
        sys.exit(1)

    step_wake_screen()
    step_launch_app()
    step_wait()
    step_stop_app()

    print("\n✅ Тест завершён успешно")


if __name__ == "__main__":
    main()
