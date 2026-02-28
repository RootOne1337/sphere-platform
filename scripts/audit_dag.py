"""Аудит текущего DAG v3 — проверка всех узлов на совместимость с DagRunner.kt."""
import requests
import json

r = requests.get(
    "http://localhost/api/v1/scripts/770bf806-6fb6-4e44-abc6-dc20b53c32ef",
    headers={"Authorization": "Bearer test"},
)
dag = r.json()["current_version"]["dag"]

# Типы, реально поддерживаемые DagRunner.kt (из исходника)
VALID_TYPES = {
    "tap", "swipe", "type_text", "sleep", "key_event", "screenshot",
    "lua", "find_element", "condition", "launch_app", "stop_app",
    "long_press", "double_tap", "scroll", "scroll_to",
    "wait_for_element_gone", "tap_element",
    "find_first_element", "tap_first_visible",
    "get_element_text", "input_clear",
    "set_variable", "get_variable", "increment_variable",
    "http_request", "open_url", "clear_app_data",
    "get_device_info", "shell", "assert",
    "loop", "start", "end",
}

print("=" * 80)
print("АУДИТ DAG v3")
print("=" * 80)

errors = []
for n in dag["nodes"]:
    nid = n["id"]
    a = n["action"]
    t = a["type"]
    ok = "✓" if t in VALID_TYPES else "✗"
    
    line = f"  {ok} {nid:25s} type={t}"
    
    # Проверка set_variable: DagRunner ожидает 'key', не 'name'
    if t == "set_variable":
        if "name" in a and "key" not in a:
            errors.append(f"{nid}: set_variable использует 'name' вместо 'key' → NPE!")
            line += f"  [BUG: name={a['name']}, нужен key]"
        elif "key" in a:
            line += f"  key={a['key']} value={a.get('value','?')}"
    
    # Проверка increment_variable: тоже ожидает 'key'
    if t == "increment_variable":
        if "name" in a and "key" not in a:
            errors.append(f"{nid}: increment_variable использует 'name' вместо 'key' → NPE!")
            line += f"  [BUG: name={a['name']}, нужен key]"
        elif "key" in a:
            line += f"  key={a['key']}"
    
    # Проверка на невалидный тип
    if t not in VALID_TYPES:
        errors.append(f"{nid}: тип '{t}' НЕ СУЩЕСТВУЕТ в DagRunner.kt → UnsupportedOperationException!")
    
    # Routing
    succ = n.get("on_success", "")
    fail = n.get("on_failure", "")
    if t == "condition":
        ot = a.get("on_true", "")
        of = a.get("on_false", "")
        line += f"  true→{ot} false→{of}"
    else:
        if succ:
            line += f"  →{succ}"
        if fail:
            line += f"  fail→{fail}"
    
    print(line)

print()
if errors:
    print("КРИТИЧЕСКИЕ ОШИБКИ:")
    for e in errors:
        print(f"  ✗ {e}")
else:
    print("✓ Ошибок не найдено")

print(f"\nВсего узлов: {len(dag['nodes'])}")
print(f"Версия: {r.json()['current_version']['version']}")
