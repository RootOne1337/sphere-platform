#!/usr/bin/env python3
"""Обновляет DAG регистрации в БД через API."""
import ast
import json
import urllib.request

with open("/tmp/seed_farming_dags.py", encoding="utf-8") as f:
    src = f.read()

start = src.find("REGISTRATION_DAG: dict = {")
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

dag = ast.literal_eval(src[start:end])
nodes_count = len(dag["nodes"])
print(f"DAG nodes: {nodes_count}")

script_id = "f3a8ace3-e5dc-4ad5-8264-22e9c932891f"
payload = json.dumps({
    "dag": dag,
    "changelog": "v3: точная копия архитектуры Auto Login v6. fail_if_not_found=true, strategy в candidates, реальные resource-id из data/, обработка 2-полей ника, явные tap_element после ника/пароля/сервера."
}).encode()

req = urllib.request.Request(
    f"http://localhost:8000/api/v1/scripts/{script_id}",
    method="PUT",
    data=payload,
    headers={"Content-Type": "application/json"},
)
try:
    r = urllib.request.urlopen(req)
    d = json.loads(r.read())
    print(f"New version ID: {d.get('id')}")
    print(f"Version: {d.get('version')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP Error {e.code}: {body[:500]}")
except Exception as e:
    print(f"Error: {e}")
