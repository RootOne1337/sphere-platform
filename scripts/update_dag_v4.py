"""
Скрипт обновления DAG до v4 — ПОЛНОЕ УДАЛЕНИЕ РЕСТАРТА.

КОРНЕВАЯ ПРИЧИНА (v3):
  Когда игрок УЖЕ В ИГРЕ, on screen нет login-элементов (pw, name, play).
  scan_all (tap_first_visible) ВСЕГДА фейлится → cycle_count растёт.
  Через 28 циклов (~2.8 мин) → check_watchdog → false → restart_app.
  phase=playing ставится только если scan_all НАХОДИТ play-кнопку,
  но в игре play-кнопок нет → phase навсегда "login" → watchdog рестартит.

FIX v4:
  1. check_watchdog.on_false → scan_all (ВМЕСТО restart_app)
     → Watchdog НИКОГДА не приводит к рестарту
  2. Убираем restart chain из routing (restart_app, restart_sleep, etc.)
     → Они становятся unreachable = мёртвый код, безопасно
  3. scan_all.on_failure = sleep_wait = check_game_alive → если app жив → scan_all
     → Если app мёртв → launch_game (единственный способ запуска)
  4. scan_all timeout: fail_if_not_found → false! Сейчас tap_first_visible
     бросает исключение если ничего не нашёл → on_failure. Нужно чтобы
     при отсутствии элементов шёл на on_failure, а не крашился.

РЕЗУЛЬТАТ: скрипт крутится бесконечно. Если элементов нет — ждёт.
  Если app умер — запускает. Рестартов — НОЛЬ.
"""

import copy
import json
import sys
import requests

API = "http://localhost/api/v1"
HEADERS = {"Authorization": "Bearer test", "Content-Type": "application/json"}
SCRIPT_ID = "770bf806-6fb6-4e44-abc6-dc20b53c32ef"


def find_node(nodes: list, node_id: str) -> dict:
    """Поиск узла DAG по идентификатору."""
    for n in nodes:
        if n["id"] == node_id:
            return n
    raise KeyError(f"Узел '{node_id}' не найден в DAG")


def main() -> None:
    # ── Получить текущий скрипт ──────────────────────────────────────────
    r = requests.get(f"{API}/scripts/{SCRIPT_ID}", headers=HEADERS)
    r.raise_for_status()
    script = r.json()
    dag = copy.deepcopy(script["current_version"]["dag"])
    nodes = dag["nodes"]
    ver = script["current_version"]["version"]

    print(f"Текущий DAG: {len(nodes)} узлов, version={ver}")
    print()

    # ═══════════════════════════════════════════════════════════════════════
    # FIX 1: check_watchdog.on_false → scan_all (вместо restart_app)
    #         НИКАКИХ РЕСТАРТОВ. НИКОГДА.
    # ═══════════════════════════════════════════════════════════════════════
    wd = find_node(nodes, "check_watchdog")
    old_target = wd["action"]["on_false"]
    wd["action"]["on_false"] = "scan_all"
    # on_failure (обработка ошибки самого condition) тоже на scan_all
    if wd.get("on_failure"):
        wd["on_failure"] = "scan_all"
    print(f"  FIX 1: check_watchdog.on_false: {old_target} → scan_all")
    print(f"         → Watchdog больше НИКОГДА не вызывает рестарт")

    # ═══════════════════════════════════════════════════════════════════════
    # FIX 2: scan_all — добавить fail_if_not_found=false
    #         tap_first_visible по дефолту бросает исключение если
    #         ни один кандидат не найден. Нам нужно on_failure, не crash.
    # ═══════════════════════════════════════════════════════════════════════
    sa = find_node(nodes, "scan_all")
    sa["action"]["fail_if_not_found"] = False
    print(f"  FIX 2: scan_all.fail_if_not_found = false")
    print(f"         → Не крашится если элементов нет, идёт на on_failure")

    # ═══════════════════════════════════════════════════════════════════════
    # FIX 3: Удалить мёртвые restart-узлы (unreachable после fix 1)
    #         Чистый DAG без мёртвого кода
    # ═══════════════════════════════════════════════════════════════════════
    dead_nodes = {
        "restart_app", "restart_sleep", "restart_launch", "restart_wait",
        "reset_counter", "reset_phase_restart", "reset_dead_restart",
    }
    before = len(nodes)
    dag["nodes"] = [n for n in nodes if n["id"] not in dead_nodes]
    nodes = dag["nodes"]
    after = len(nodes)
    print(f"  FIX 3: Удалены unreachable restart-узлы: {dead_nodes}")
    print(f"         {before} → {after} узлов")

    print(f"\nОбновлённый DAG: {len(nodes)} узлов")

    # ── Валидация: все ссылки корректны ───────────────────────────────────
    node_ids = {n["id"] for n in nodes}
    errors = []
    for n in nodes:
        for field in ("on_success", "on_failure"):
            target = n.get(field)
            if target and target not in node_ids:
                errors.append(f"{n['id']}.{field} → '{target}' не найден")
        action = n.get("action", {})
        for field in ("on_true", "on_false"):
            target = action.get(field)
            if target and target not in node_ids:
                errors.append(f"{n['id']}.action.{field} → '{target}' не найден")

    if errors:
        print("\nОШИБКИ ВАЛИДАЦИИ:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    print("✓ Валидация пройдена — все ссылки корректны")

    # ── Вывести чистый flow ───────────────────────────────────────────────
    print("\n=== FLOW v4 ===")
    for n in nodes:
        a = n["action"]
        t = a["type"]
        nid = n["id"]
        if t == "condition":
            print(f"  {nid}: {t} → T:{a.get('on_true','')} F:{a.get('on_false','')}")
        else:
            succ = n.get("on_success", "")
            fail = n.get("on_failure", "")
            extra = ""
            if t == "set_variable":
                extra = f" ({a.get('key','')}={a.get('value','')})"
            elif t == "sleep":
                extra = f" ({a.get('ms',0)}ms)"
            line = f"  {nid}: {t}{extra}"
            if succ:
                line += f" → {succ}"
            if fail:
                line += f" fail→{fail}"
            print(line)

    # ── Отправить ─────────────────────────────────────────────────────────
    payload = {
        "dag": dag,
        "changelog": (
            "v4 УДАЛЁН РЕСТАРТ: watchdog → scan_all вместо restart. "
            "Удалены 7 unreachable restart-узлов. "
            "scan_all.fail_if_not_found=false. "
            "Единственный запуск: check_dead_limit → launch_game (app мёртв)."
        ),
    }

    serialized = json.dumps(payload, ensure_ascii=False)
    print(f"\nPayload: {len(serialized)} байт")

    r2 = requests.put(
        f"{API}/scripts/{SCRIPT_ID}",
        headers=HEADERS,
        data=serialized.encode("utf-8"),
    )
    print(f"PUT: {r2.status_code}")

    if r2.status_code == 200:
        result = r2.json()
        new_ver = result.get("current_version", {}).get("version")
        new_vid = result.get("current_version_id")
        print(f"\n✓ Версия: {ver} → {new_ver}")
        print(f"  version_id: {new_vid}")
        print(f"  РЕСТАРТ: ПОЛНОСТЬЮ УДАЛЁН")
    else:
        print(f"\n✗ Ошибка: {r2.text[:500]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
