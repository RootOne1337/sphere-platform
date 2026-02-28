"""Диагностика: текущее состояние устройств, тасков и WebSocket соединений."""
import requests
import json

API = "http://localhost/api/v1"
H = {"Authorization": "Bearer test"}

# 1. Устройства
r = requests.get(f"{API}/devices/", headers=H, params={"page_size": 20})
devs = r.json().get("items", [])
print("=== УСТРОЙСТВА В БД ===")
for d in devs:
    name = d.get("name", "?")
    did = d["id"][:8]
    ls = d.get("live_status") or {}
    status = ls.get("status", "нет данных")
    ws_sid = ls.get("ws_session_id", "")
    print(f"  {name:25s}  id={did}...  status={status:10s}  ws={ws_sid[:8] if ws_sid else 'нет'}")
print(f"Всего: {len(devs)}")

# 2. Таски  
r2 = requests.get(f"{API}/tasks/", headers=H, params={"page_size": 20})
if r2.status_code == 200:
    tasks = r2.json()
    items = tasks.get("items", [])
    print(f"\n=== ТАСКИ ({len(items)} шт) ===")
    for t in items:
        tid = t["id"][:8]
        status = t.get("status", "?")
        dev = (t.get("device_id") or "?")[:8]
        script = (t.get("script_id") or "?")[:8]
        print(f"  {tid}...  status={status:12s}  device={dev}...  script={script}...")
    if not items:
        print("  (пусто — нет тасков)")
else:
    print(f"\n=== ТАСКИ: ошибка {r2.status_code} ===")
    print(f"  {r2.text[:300]}")

# 3. Fleet status
r3 = requests.get(f"{API}/devices/status/fleet", headers=H)
if r3.status_code == 200:
    fleet = r3.json()
    print(f"\n=== FLEET STATUS ===")
    print(f"  online={fleet.get('online', 0)}  offline={fleet.get('offline', 0)}  total={fleet.get('total', 0)}")
else:
    print(f"\n=== FLEET: ошибка {r3.status_code}: {r3.text[:200]} ===")

# 4. Скрипты (текущая версия)
r4 = requests.get(f"{API}/scripts/770bf806-6fb6-4e44-abc6-dc20b53c32ef", headers=H)
if r4.status_code == 200:
    script = r4.json()
    cv = script.get("current_version", {})
    print(f"\n=== СКРИПТ ===")
    print(f"  name: {script.get('name')}")
    print(f"  version: {cv.get('version')}")
    print(f"  nodes: {len(cv.get('dag', {}).get('nodes', []))}")
