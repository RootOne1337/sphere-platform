"""Анализ всех устройств в БД — найти дубли и legacy записи."""
import requests

API = "http://localhost/api/v1"
H = {"Authorization": "Bearer test"}

r = requests.get(f"{API}/devices/", headers=H, params={"page_size": 50})
devs = r.json().get("items", [])

print(f"=== ВСЕ УСТРОЙСТВА В БД ({len(devs)} шт) ===\n")
for d in devs:
    did = d["id"]
    name = d.get("name", "?")
    model = d.get("model", "?")
    serial = d.get("serial_number", "?")
    created = d.get("created_at", "?")[:19]
    tags = d.get("tags", [])
    print(f"  {name}")
    print(f"    id:      {did}")
    print(f"    model:   {model}")
    print(f"    serial:  {serial}")
    print(f"    created: {created}")
    print(f"    tags:    {tags}")
    print()

# Группируем по serial
from collections import defaultdict
by_serial = defaultdict(list)
for d in devs:
    s = d.get("serial_number", "?")
    by_serial[s].append(d)

print("=== ГРУППИРОВКА ПО SERIAL ===\n")
for serial, devices in by_serial.items():
    if len(devices) > 1:
        print(f"  ДУБЛЬ serial={serial} — {len(devices)} записей:")
        for d in devices:
            print(f"    - {d['name']} (id={d['id'][:8]}..., created={d.get('created_at','?')[:19]})")
    else:
        d = devices[0]
        print(f"  serial={serial} → {d['name']} (id={d['id'][:8]}...)")

# Какие 3 актуальных?
print("\n=== АКТУАЛЬНЫЕ (new naming convention) ===")
actual = [d for d in devs if "-old-" not in d.get("name", "") and "legacy" not in d.get("name", "")]
legacy = [d for d in devs if "-old-" in d.get("name", "") or "legacy" in d.get("name", "")]
for d in actual:
    print(f"  ✓ {d['name']} ({d['id'][:8]}...)")
print(f"\n=== LEGACY (удалить?) ===")
for d in legacy:
    print(f"  ✗ {d['name']} ({d['id'][:8]}...)")
