"""
Скрипт обновления DAG до v3 — КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ БЕЗОПАСНОСТИ.

ПРОБЛЕМЫ v2:
  1. restart_sleep = 3 сек → сервер Black Russia БАНИТ за подключение чаще 15 сек!
     → Увеличиваем до 60 000 мс (1 минута).
  2. scan_all может нажать play_but/button_play/play_butt/servers_play, но phase
     не обновляется на "playing" → watchdog через 7 мин делает ложный рестарт.
     → Добавляем route_play после route_name: если label содержит 'play' → phase=playing.
  3. launch_game_wait = 4 сек — слишком мало для первоначальной загрузки.
     → Увеличиваем до 15 000 мс.

РЕЗУЛЬТАТ: полностью исключены ложные рестарты в игре и баны за частые заходы.
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

    # ═══════════════════════════════════════════════════════════════════════
    # FIX 1: restart_sleep 3с → 60с (АНТИ-БАН: сервер не пускает чаще 15с)
    # ═══════════════════════════════════════════════════════════════════════
    rs = find_node(nodes, "restart_sleep")
    old_ms = rs["action"]["ms"]
    rs["action"]["ms"] = 60000
    print(f"  restart_sleep: {old_ms}ms → 60000ms")

    # ═══════════════════════════════════════════════════════════════════════
    # FIX 2: launch_game_wait 4с → 15с (достаточно для загрузки Unity)
    # ═══════════════════════════════════════════════════════════════════════
    lgw = find_node(nodes, "launch_game_wait")
    old_lgw = lgw["action"]["ms"]
    lgw["action"]["ms"] = 15000
    lgw["timeout_ms"] = 20000
    print(f"  launch_game_wait: {old_lgw}ms → 15000ms")

    # restart_wait тоже увеличиваем — после рестарта нужно время
    rw = find_node(nodes, "restart_wait")
    old_rw = rw["action"]["ms"]
    rw["action"]["ms"] = 15000
    rw["timeout_ms"] = 20000
    print(f"  restart_wait: {old_rw}ms → 15000ms")

    # ═══════════════════════════════════════════════════════════════════════
    # FIX 3: route_name.on_false → route_play (вместо sleep_ok)
    #         Когда scan_all нажимает play-кнопку — ставим phase=playing!
    # ═══════════════════════════════════════════════════════════════════════
    rn = find_node(nodes, "route_name")
    rn["action"]["on_false"] = "route_play"
    print(f"  route_name.on_false: sleep_ok → route_play")

    # Новый узел: route_play — проверяет tapped_label содержит 'play'
    # Покрывает: servers_play, button_play, play_butt, play_but
    nodes.append({
        "id": "route_play",
        "action": {
            "type": "condition",
            "code": (
                "local label = ctx.scan_all and ctx.scan_all.tapped_label or ''\n"
                "return string.find(label, 'play') ~= nil"
            ),
            "on_true": "set_phase_playing",
            "on_false": "sleep_ok",
        },
        "on_success": "set_phase_playing",
        "on_failure": "sleep_ok",
        "timeout_ms": 2000,
        "retry": 0,
    })
    print(f"  Добавлен route_play: play-кнопки → set_phase_playing")

    # ═══════════════════════════════════════════════════════════════════════
    # FIX 4: sleep_wait увеличить с 1с до 5с (менее агрессивный polling)
    # ═══════════════════════════════════════════════════════════════════════
    sw = find_node(nodes, "sleep_wait")
    old_sw = sw["action"]["ms"]
    sw["action"]["ms"] = 5000
    print(f"  sleep_wait: {old_sw}ms → 5000ms (менее агрессивный polling)")

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
        print("ОШИБКИ ВАЛИДАЦИИ:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    print("✓ Валидация пройдена")

    # ── Отправить ─────────────────────────────────────────────────────────
    payload = {
        "dag": dag,
        "changelog": (
            "v3 КРИТИЧЕСКИЙ: restart_sleep 3с→60с (анти-бан), "
            "route_play фиксит phase при нажатии play через scan_all, "
            "launch/restart_wait 4с→15с, sleep_wait 1с→5с"
        ),
    }

    serialized = json.dumps(payload, ensure_ascii=False)
    print(f"Payload: {len(serialized)} байт")

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
        print(f"✓ Версия: {ver} → {new_ver}")
        print(f"  version_id: {new_vid}")
    else:
        print(f"✗ Ошибка: {r2.text[:500]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
