"""
Скрипт обновления DAG "Black Russia Auto Login" до версии 2.

Изменения:
1. Фаза "playing" — после tap_play_login устанавливается phase=playing,
   watchdog при phase=playing НЕ перезапускает приложение.
2. Отложенный перезапуск (~1 мин) — когда процесс не найден, dead_count
   инкрементируется. Пока dead_count < 4 (~60 сек), скан продолжается
   (может подхватить кнопку "Установить"). При >= 4 → launch_game.
3. Кнопка "Установить" от Android package installer добавлена в scan_all.
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

    print(f"Текущий DAG: {len(nodes)} узлов, version={script['current_version']['version']}")

    # ════ Добавить обязательные мета-поля DAGScript ═══════════════════════
    dag["version"] = "1.0"
    if "name" not in dag or not dag["name"]:
        dag["name"] = script.get("name", "Black Russia — Auto Login")

    # ═══════════════════════════════════════════════════════════════════════
    # 1. Инициализация переменных phase и dead_count
    # ═══════════════════════════════════════════════════════════════════════
    # init_counter → init_phase → init_dead_count → check_game_alive
    find_node(nodes, "init_counter")["on_success"] = "init_phase"

    nodes.append({
        "id": "init_phase",
        "action": {"type": "set_variable", "key": "phase", "value": "login"},
        "on_success": "init_dead_count",
        "on_failure": None,
        "timeout_ms": 1000,
        "retry": 0,
    })

    nodes.append({
        "id": "init_dead_count",
        "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
        "on_success": "check_game_alive",
        "on_failure": None,
        "timeout_ms": 1000,
        "retry": 0,
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 2. Отложенный перезапуск: check_game_alive → dead_count → limit
    # ═══════════════════════════════════════════════════════════════════════
    cga = find_node(nodes, "check_game_alive")
    cga["on_success"] = "reset_dead_alive"
    cga["on_failure"] = "increment_dead_count"

    # При успехе check_game_alive — сбросить dead_count
    nodes.append({
        "id": "reset_dead_alive",
        "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
        "on_success": "increment_counter",
        "on_failure": None,
        "timeout_ms": 1000,
        "retry": 0,
    })

    # При неудаче — инкрементировать dead_count
    nodes.append({
        "id": "increment_dead_count",
        "action": {"type": "increment_variable", "key": "dead_count"},
        "on_success": "check_dead_limit",
        "on_failure": "scan_all",
        "timeout_ms": 1000,
        "retry": 0,
    })

    # Проверка: dead_count < 4 (~60 сек) → скан продолжается, иначе → запуск
    nodes.append({
        "id": "check_dead_limit",
        "action": {
            "type": "condition",
            "code": "return (tonumber(ctx.dead_count) or 0) < 4",
            "on_true": "scan_all",
            "on_false": "launch_game",
        },
        "on_success": "scan_all",
        "on_failure": "launch_game",
        "timeout_ms": 2000,
        "retry": 0,
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 3. Watchdog учитывает фазу — в играе не рестартить
    # ═══════════════════════════════════════════════════════════════════════
    cw = find_node(nodes, "check_watchdog")
    cw["action"]["code"] = (
        "return (tonumber(ctx.cycle_count) or 0) < 28 or ctx.phase == 'playing'"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # 4. tap_play_login → set_phase_playing → sleep_ok
    # ═══════════════════════════════════════════════════════════════════════
    find_node(nodes, "tap_play_login")["on_success"] = "set_phase_playing"

    nodes.append({
        "id": "set_phase_playing",
        "action": {"type": "set_variable", "key": "phase", "value": "playing"},
        "on_success": "sleep_ok",
        "on_failure": None,
        "timeout_ms": 1000,
        "retry": 0,
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 5. launch_game_wait → reset_dead_launched → scan_all
    # ═══════════════════════════════════════════════════════════════════════
    find_node(nodes, "launch_game_wait")["on_success"] = "reset_dead_launched"

    nodes.append({
        "id": "reset_dead_launched",
        "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
        "on_success": "scan_all",
        "on_failure": None,
        "timeout_ms": 1000,
        "retry": 0,
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 6. После рестарта — сбросить phase и dead_count
    #    reset_counter → reset_phase_restart → reset_dead_restart → scan_all
    # ═══════════════════════════════════════════════════════════════════════
    find_node(nodes, "reset_counter")["on_success"] = "reset_phase_restart"

    nodes.append({
        "id": "reset_phase_restart",
        "action": {"type": "set_variable", "key": "phase", "value": "login"},
        "on_success": "reset_dead_restart",
        "on_failure": None,
        "timeout_ms": 1000,
        "retry": 0,
    })

    nodes.append({
        "id": "reset_dead_restart",
        "action": {"type": "set_variable", "key": "dead_count", "value": "0"},
        "on_success": "scan_all",
        "on_failure": None,
        "timeout_ms": 1000,
        "retry": 0,
    })

    # ═══════════════════════════════════════════════════════════════════════
    # 7. scan_all — добавить кнопку «Установить» от Android
    # ═══════════════════════════════════════════════════════════════════════
    scan = find_node(nodes, "scan_all")
    candidates = scan["action"]["candidates"]

    # По resource-id (надёжный способ для com.android.packageinstaller)
    candidates.append({
        "label": "pkg_install_id",
        "selector": "com.android.packageinstaller:id/ok_button",
        "strategy": "id",
    })

    # По xpath — fallback для разных локалей
    candidates.append({
        "label": "pkg_install_xpath",
        "selector": (
            "//android.widget.Button["
            "contains(@text,'\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c') or "
            "contains(@text,'Install') or "
            "contains(@text,'\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c') or "
            "contains(@text,'Update')]"
        ),
        "strategy": "xpath",
    })

    print(f"Обновлённый DAG: {len(nodes)} узлов")

    # ── Валидация: все on_success/on_failure ссылаются на существующие узлы ─
    node_ids = {n["id"] for n in nodes}
    errors = []
    for n in nodes:
        for field in ("on_success", "on_failure"):
            target = n.get(field)
            if target and target not in node_ids:
                errors.append(f"{n['id']}.{field} → '{target}' не найден")
        # Проверяем condition on_true/on_false
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

    print("✓ Валидация пройдена, все ссылки корректны")

    # ── Отправить обновлённый DAG ────────────────────────────────────────
    payload = {
        "dag": dag,
        "changelog": "v2: фаза playing (нет ложных рестартов в игре), отложенный запуск ~1мин, кнопка Установить",
    }

    # Отладка: проверяем что отправляем
    serialized = json.dumps(payload, ensure_ascii=False)
    print(f"Payload начало: {serialized[:300]}")
    print(f"Payload длина: {len(serialized)} байт")

    # Сохраняем в файл для возможного curl
    with open("dag_payload.json", "w", encoding="utf-8") as f:
        f.write(serialized)

    r2 = requests.put(
        f"{API}/scripts/{SCRIPT_ID}",
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
        data=serialized.encode("utf-8"),
    )
    print(f"PUT статус: {r2.status_code}")

    if r2.status_code == 200:
        result = r2.json()
        print(f"✓ Новая версия: {result.get('current_version', {}).get('version')}")
        print(f"  version_id: {result.get('current_version_id')}")
    else:
        print(f"✗ Ошибка: {r2.text[:500]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
