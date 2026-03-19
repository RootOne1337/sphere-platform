#!/usr/bin/env python3
"""Валидация DAG — проверка ссылок и типов."""
import ast
import sys

with open("scripts/seed_farming_dags.py", encoding="utf-8") as f:
    src = f.read()

# Находим REGISTRATION_DAG через AST
start = src.find("REGISTRATION_DAG: dict = {")
if start == -1:
    print("NOT FOUND")
    sys.exit(1)
start = src.index("{", start)

depth = 0
end = start
for i in range(start, len(src)):
    if src[i] == "{":
        depth += 1
    elif src[i] == "}":
        depth -= 1
    if depth == 0:
        end = i + 1
        break

dag_str = src[start:end]
dag = ast.literal_eval(dag_str)
nodes = dag["nodes"]
print(f"Total nodes: {len(nodes)}")
ids = set()
for i, n in enumerate(nodes):
    nid = n["id"]
    atype = n["action"]["type"]
    ons = str(n.get("on_success", "null"))
    onf = str(n.get("on_failure", "null"))
    dup = " DUPLICATE!" if nid in ids else ""
    ids.add(nid)
    print(f"[{i:2d}] {nid:30s} {atype:22s} s={ons:25s} f={onf}{dup}")

broken = 0
for n in nodes:
    for ref_name, ref in [("on_success", n.get("on_success")), ("on_failure", n.get("on_failure"))]:
        if ref and ref not in ids:
            print(f"  BROKEN {ref_name}: {n['id']} -> {ref}")
            broken += 1
    act = n.get("action", {})
    for ref_name, ref in [("on_true", act.get("on_true")), ("on_false", act.get("on_false"))]:
        if ref and ref not in ids:
            print(f"  BROKEN {ref_name}: {n['id']} -> {ref}")
            broken += 1

VALID_TYPES = {
    "stop_app", "launch_app", "sleep", "tap_first_visible", "tap_element",
    "type_text", "find_element", "condition", "set_variable", "increment_variable",
    "start", "end", "shell", "key_event", "tap", "swipe", "long_press",
    "double_tap", "scroll", "scroll_to", "screenshot", "open_url", "clear_app_data",
    "find_first_element", "get_element_text", "input_clear", "wait_for_element_gone",
    "loop", "assert", "get_variable", "http_request", "get_device_info", "lua",
}
bad_types = 0
for n in nodes:
    atype = n["action"]["type"]
    if atype not in VALID_TYPES:
        print(f"  INVALID TYPE: {n['id']} uses '{atype}'")
        bad_types += 1

if broken == 0 and bad_types == 0:
    print("=== ALL VALID ===")
else:
    print(f"=== {broken} broken refs, {bad_types} bad types ===")
