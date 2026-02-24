#!/usr/bin/env python3
"""
test_tap_first_visible.py — тест оптимизированного multi-XPath поиска.

Суть: один uiautomator dump → проверяем весь пак XPath сразу → тапаем первый
найденный элемент. Zero лишних dump-операций.

Сценарий:
  1. Разбудить экран
  2. Запустить целевое приложение
  3. Выполнить несколько раундов tap_first_visible:
       - Раунд 1: пак XPath для главного экрана (кнопки старта/входа)
       - Раунд 2: пак XPath для обработки диалогов/попапов (Allow / OK / Skip)
       - Раунд 3: пак XPath для пост-экрана (Continue / Next / Done)
  4. Принудительно остановить приложение

Запуск:
  python scripts/test_tap_first_visible.py
  python scripts/test_tap_first_visible.py --package com.example.app --rounds 3

Можно передать свой пак XPath через --xpath-file pack.json.
Формат pack.json:
  [
    { "selector": "//android.widget.Button[@text='Start']", "strategy": "xpath", "label": "start" },
    { "selector": "//android.widget.Button[@text='Play']",  "strategy": "xpath", "label": "play" },
    { "selector": "start_button",                           "strategy": "id",    "label": "start_id" }
  ]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import re
from dataclasses import dataclass
from typing import Optional

# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_PACKAGE  = "com.br.top"
DUMP_PATH        = "/sdcard/sphere_ui_dump.xml"
POLL_INTERVAL    = 0.6   # сек между dump-попытками
ADB_TIMEOUT      = 30    # таймаут каждой ADB-команды, сек

# ─── Пак XPath кандидатов по раундам ─────────────────────────────────────────
#
# Каждый раунд — список кандидатов проверяется против ОДНОГО dump.
# Порядок важен: первый совпавший → тап.
#
DEFAULT_ROUNDS = [
    {
        "name": "Главный экран / вход",
        "timeout": 12.0,
        "candidates": [
            # Явные кнопки по тексту (xpath)
            {"selector": "//android.widget.Button[@text='Start']",    "strategy": "xpath", "label": "Start"},
            {"selector": "//android.widget.Button[@text='Play']",     "strategy": "xpath", "label": "Play"},
            {"selector": "//android.widget.Button[@text='Login']",    "strategy": "xpath", "label": "Login"},
            {"selector": "//android.widget.Button[@text='Sign In']",  "strategy": "xpath", "label": "Sign In"},
            {"selector": "//android.widget.Button[@text='Enter']",    "strategy": "xpath", "label": "Enter"},
            # Поиск по resource-id суффиксу
            {"selector": "btn_start",   "strategy": "id",   "label": "btn_start [id]"},
            {"selector": "btn_play",    "strategy": "id",   "label": "btn_play [id]"},
            {"selector": "btn_login",   "strategy": "id",   "label": "btn_login [id]"},
            # Любое clickable с текстом "start" или "play" (xpath contains)
            {"selector": "//android.widget.TextView[contains(translate(@text,'STARTPLAY','startplay'),'start')]",
             "strategy": "xpath", "label": "TextView[start]"},
            {"selector": "//android.widget.TextView[contains(translate(@text,'STARTPLAY','startplay'),'play')]",
             "strategy": "xpath", "label": "TextView[play]"},
        ],
    },
    {
        "name": "Диалоги / попапы / пермишены",
        "timeout": 8.0,
        "candidates": [
            {"selector": "//android.widget.Button[@text='Allow']",            "strategy": "xpath", "label": "Allow"},
            {"selector": "//android.widget.Button[@text='OK']",               "strategy": "xpath", "label": "OK"},
            {"selector": "//android.widget.Button[@text='Accept']",           "strategy": "xpath", "label": "Accept"},
            {"selector": "//android.widget.Button[@text='ALLOW']",            "strategy": "xpath", "label": "ALLOW"},
            {"selector": "//android.widget.Button[@text='Skip']",             "strategy": "xpath", "label": "Skip"},
            {"selector": "//android.widget.Button[@text='No thanks']",        "strategy": "xpath", "label": "No thanks"},
            {"selector": "//android.widget.Button[@text='Not now']",          "strategy": "xpath", "label": "Not now"},
            {"selector": "//android.widget.Button[contains(@text,'Allow')]",  "strategy": "xpath", "label": "contains:Allow"},
            {"selector": "//android.widget.Button[contains(@text,'OK')]",     "strategy": "xpath", "label": "contains:OK"},
            # com.android.packageinstaller / permissiondialog
            {"selector": "com.android.packageinstaller:id/permission_allow_button",
             "strategy": "id", "label": "permission_allow"},
        ],
    },
    {
        "name": "Пост-экран / завершение",
        "timeout": 8.0,
        "candidates": [
            {"selector": "//android.widget.Button[@text='Continue']", "strategy": "xpath", "label": "Continue"},
            {"selector": "//android.widget.Button[@text='Next']",     "strategy": "xpath", "label": "Next"},
            {"selector": "//android.widget.Button[@text='Done']",     "strategy": "xpath", "label": "Done"},
            {"selector": "//android.widget.Button[@text='Finish']",   "strategy": "xpath", "label": "Finish"},
            {"selector": "//android.widget.Button[@text='Close']",    "strategy": "xpath", "label": "Close"},
            {"selector": "btn_continue", "strategy": "id",  "label": "btn_continue [id]"},
            {"selector": "btn_next",     "strategy": "id",  "label": "btn_next [id]"},
        ],
    },
]


# ─── ADB helpers ──────────────────────────────────────────────────────────────

def adb(*args: str) -> str:
    result = subprocess.run(
        ["adb", "shell", *args],
        capture_output=True, text=True, timeout=ADB_TIMEOUT,
    )
    return result.stdout.strip()


def adb_root(*args: str) -> str:
    cmd = " ".join(args)
    return adb("su", "-c", cmd)


def banner(msg: str) -> None:
    print(f"\n{'─' * 55}\n  {msg}\n{'─' * 55}")


# ─── UI dump & multi-xpath search ────────────────────────────────────────────

@dataclass
class ElementMatch:
    coords: str
    label: str
    index: int
    selector: str
    strategy: str


def dump_ui_xml() -> Optional[str]:
    """Один вызов uiautomator dump → строка XML. Ключевая операция."""
    adb_root(f"uiautomator dump {DUMP_PATH} 2>/dev/null")
    time.sleep(0.25)
    xml = adb_root(f"cat {DUMP_PATH}")
    return xml if "<hierarchy" in xml else None


def _parse_bounds_center(bounds: str) -> Optional[str]:
    """[x1,y1][x2,y2] → 'cx,cy'"""
    m = re.search(r'\[(\d+),(\d+)]\[(\d+),(\d+)]', bounds)
    if not m:
        return None
    x1, y1, x2, y2 = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    return f"{(x1 + x2) // 2},{(y1 + y2) // 2}"


def _find_in_xml(xml: str, selector: str, strategy: str) -> Optional[str]:
    """
    Ищет элемент в уже-считанном XML (без нового dump).
    Python-аналог parseUiXml() из AdbActionExecutor.kt.
    """
    # xpath — используем lxml/ElementTree
    if strategy == "xpath":
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            for node in root.iter():
                # Простейший xpath: ищем все узлы и проверяем атрибуты
                # Для полного xpath используется lxml (если доступен)
                pass
            # Попытка через lxml (более полный XPath 1.0)
            try:
                from lxml import etree
                tree = etree.fromstring(xml.encode())
                nodes = tree.xpath(selector)
                for node in nodes:
                    bounds = node.get("bounds", "")
                    center = _parse_bounds_center(bounds)
                    if center:
                        return center
            except ImportError:
                # Fallback: ElementTree + простой xpath (//Tag[@attr='val'])
                tree = ET.fromstring(xml)
                # ElementTree поддерживает базовый XPath
                try:
                    nodes = tree.findall("." + selector.replace("//*", "//").replace("//", ".//{*}"))
                except Exception:
                    nodes = list(tree.iter())
                for node in nodes:
                    attrib = node.attrib
                    # Для простых случаев //Tag[@text='X'] проверяем все предикаты
                    m = re.search(r"\[@([^=]+)='([^']+)'\]", selector)
                    if m:
                        attr_name, attr_val = m.group(1), m.group(2)
                        if attrib.get(attr_name) == attr_val:
                            center = _parse_bounds_center(attrib.get("bounds", ""))
                            if center:
                                return center
                    else:
                        bounds = attrib.get("bounds", "")
                        center = _parse_bounds_center(bounds)
                        if center:
                            return center
        except Exception as e:
            print(f"    [xml parse error xpath] {e}")
        return None

    # id / text / desc / class — линейный scan
    attr_map = {"id": "resource-id", "desc": "content-desc", "class": "class"}
    attr = attr_map.get(strategy, "text")
    try:
        import xml.etree.ElementTree as ET
        tree = ET.fromstring(xml)
        for node in tree.iter():
            val = node.attrib.get(attr, "")
            if strategy == "id":
                hit = val == selector or val.endswith(f":id/{selector}")
            else:
                hit = selector.lower() in val.lower()
            if hit:
                center = _parse_bounds_center(node.attrib.get("bounds", ""))
                if center:
                    return center
    except Exception as e:
        print(f"    [xml parse error {strategy}] {e}")
    return None


def find_first_visible(
    candidates: list[dict],
    timeout: float,
) -> Optional[ElementMatch]:
    """
    ОДИН dump на итерацию → проверяем все N кандидатов → первый совпавший.

    Это точное Python-воспроизведение логики findFirstElement() из
    AdbActionExecutor.kt: O(1 dump) per poll cycle вместо O(N dumps).
    """
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        t0 = time.monotonic()
        xml = dump_ui_xml()          # ← ЕДИНСТВЕННЫЙ dump за итерацию
        dump_ms = int((time.monotonic() - t0) * 1000)

        if xml is None:
            print(f"    [attempt {attempt}] dump failed, retry...")
            time.sleep(POLL_INTERVAL)
            continue

        # Проверяем всех кандидатов против одного XML
        for idx, c in enumerate(candidates):
            coords = _find_in_xml(xml, c["selector"], c["strategy"])
            if coords:
                print(f"    [attempt {attempt}] dump={dump_ms}ms → HIT idx={idx} label={c.get('label','?')} coords={coords}")
                return ElementMatch(
                    coords=coords,
                    label=c.get("label", f"candidate_{idx}"),
                    index=idx,
                    selector=c["selector"],
                    strategy=c["strategy"],
                )

        print(f"    [attempt {attempt}] dump={dump_ms}ms → no match ({len(candidates)} candidates checked)")
        time.sleep(POLL_INTERVAL)

    return None


# ─── Test steps ───────────────────────────────────────────────────────────────

def step_wake_screen() -> None:
    banner("Wake screen")
    adb("input keyevent 224")
    time.sleep(0.8)
    print("  ✓ Screen on")


def step_launch_app(package: str) -> None:
    banner(f"Launch: {package}")
    adb("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(2.5)
    pid = adb("pidof", package)
    if pid:
        print(f"  ✓ Running, PID={pid}")
    else:
        print(f"  ✗ Not running — check package name", file=sys.stderr)
        sys.exit(1)


def step_round(round_def: dict, round_num: int) -> bool:
    """
    Один раунд multi-xpath поиска.
    Возвращает True если нашёл и тапнул, False если timeout (не fatal).
    """
    banner(f"Round {round_num}: {round_def['name']}")
    candidates = round_def["candidates"]
    timeout    = round_def["timeout"]

    print(f"  Кандидатов : {len(candidates)}")
    print(f"  Timeout    : {timeout}s")
    print(f"  Стратегия  : 1 dump → {len(candidates)} проверок за итерацию\n")

    match = find_first_visible(candidates, timeout)

    if match is None:
        print(f"\n  ⚠  Никто из {len(candidates)} кандидатов не найден за {timeout}s — пропускаем раунд")
        return False

    print(f"\n  ✓  Найден: [{match.label}]  coords={match.coords}  strategy={match.strategy}")
    print(f"     Тапаем...")
    cx, cy = match.coords.split(",")
    adb("input", "tap", cx, cy)
    time.sleep(1.0)
    print(f"  ✓  Тап выполнен → ({cx}, {cy})")
    return True


def step_stop_app(package: str) -> None:
    banner(f"Stop: {package}")
    adb_root(f"am force-stop {package}")
    time.sleep(0.8)
    pid = adb("pidof", package)
    print(f"  {'✓ Остановлено' if not pid else '⚠ Ещё активен PID=' + pid}")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="test_tap_first_visible — one dump, N xpath checks")
    parser.add_argument("--package",    default=DEFAULT_PACKAGE,
                        help="Package name (default: %(default)s)")
    parser.add_argument("--xpath-file", default=None,
                        help="JSON file with custom candidates list for round 1")
    parser.add_argument("--rounds",     type=int, default=None,
                        help="How many rounds to run (default: all)")
    parser.add_argument("--no-launch",  action="store_true",
                        help="Skip app launch (app already running)")
    parser.add_argument("--no-stop",    action="store_true",
                        help="Skip force-stop at the end")
    args = parser.parse_args()

    # Проверяем ADB
    try:
        devs = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
        online = [l for l in devs.stdout.splitlines()[1:] if l.strip() and "offline" not in l]
        if not online:
            print("✗ Нет подключённых устройств", file=sys.stderr)
            sys.exit(1)
        print(f"\n═══ test_tap_first_visible ═══")
        print(f"Устройство : {online[0].split()[0]}")
        print(f"Пакет      : {args.package}")
    except FileNotFoundError:
        print("✗ ADB не найден в PATH", file=sys.stderr)
        sys.exit(1)

    # Загрузить кастомный пак если передан
    rounds = DEFAULT_ROUNDS.copy()
    if args.xpath_file:
        with open(args.xpath_file, encoding="utf-8") as f:
            custom_candidates = json.load(f)
        rounds[0] = {
            "name": f"Custom pack ({args.xpath_file})",
            "timeout": 12.0,
            "candidates": custom_candidates,
        }
        print(f"XPath pack : {args.xpath_file}  ({len(custom_candidates)} кандидатов)")

    if args.rounds:
        rounds = rounds[:args.rounds]

    # Запуск
    if not args.no_launch:
        step_wake_screen()
        step_launch_app(args.package)

    results = []
    for i, round_def in enumerate(rounds, 1):
        hit = step_round(round_def, i)
        results.append((round_def["name"], hit))

    if not args.no_stop:
        step_stop_app(args.package)

    # Итоговая сводка
    print(f"\n{'═' * 55}")
    print(f"  РЕЗУЛЬТАТЫ")
    print(f"{'═' * 55}")
    for name, hit in results:
        status = "✓ HIT " if hit else "– miss"
        print(f"  {status}  {name}")
    hits = sum(1 for _, h in results if h)
    print(f"\n  Раундов: {len(results)}, нашли: {hits}, пропущено: {len(results) - hits}")
    print(f"{'═' * 55}\n")

    sys.exit(0 if hits > 0 else 1)


if __name__ == "__main__":
    main()
