# SPLIT-5 — Topology (Instance Registry)

**ТЗ-родитель:** TZ-08-PC-Agent  
**Ветка:** `stage/8-pc-agent`  
**Задача:** `SPHERE-045`  
**Исполнитель:** Backend/Python  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Интеграция при merge:** TZ-09 n8n и TZ-10 Frontend работают с mock topology; при merge подключить реальное API

---

## Цель Сплита

Регистрировать воркстанцию и её экземпляры LDPlayer на сервере при старте и при изменениях. Хранить топологию (какой экземпляр на какой воркстанции) для маршрутизации команд.

---

## Шаг 1 — Topology модели

```python
# agent/models.py (добавить)
class InstanceRegistration(BaseModel):
    index: int
    name: str
    adb_port: int
    android_serial: str | None = None  # e.g. "127.0.0.1:5554"

class WorkstationRegistration(BaseModel):
    workstation_id: str
    hostname: str
    os_version: str
    ip_address: str
    instances: list[InstanceRegistration]
    agent_version: str
```

---

## Шаг 2 — TopologyReporter

```python
# agent/topology.py
import socket
import platform
import asyncio
from loguru import logger
from .config import config
from .models import WorkstationRegistration, InstanceRegistration
from .ldplayer import LDPlayerManager
from .client import AgentWebSocketClient

AGENT_VERSION = "1.0.0"

class TopologyReporter:
    def __init__(self, ws_client: AgentWebSocketClient, ldplayer: LDPlayerManager):
        self.ws_client = ws_client
        self.ldplayer = ldplayer
    
    async def report_on_connect(self):
        """Вызывается сразу после подключения WS — отправляет полную топологию."""
        try:
            reg = await self._build_registration()
            await self.ws_client.send({
                "type": "workstation_register",
                "payload": reg.model_dump(),
            })
            logger.info(
                f"Topology reported: {len(reg.instances)} instances on {reg.hostname}"
            )
        except Exception as e:
            logger.error(f"Topology report failed: {e}")
    
    async def _build_registration(self) -> WorkstationRegistration:
        instances_raw = await self.ldplayer.list_instances()
        instances = [
            InstanceRegistration(
                index=inst.index,
                name=inst.name,
                adb_port=inst.adb_port or (5554 + inst.index * 2),
                android_serial=f"127.0.0.1:{inst.adb_port}" if inst.adb_port else None,
            )
            for inst in instances_raw
        ]
        
        return WorkstationRegistration(
            workstation_id=config.workstation_id,
            hostname=socket.gethostname(),
            os_version=platform.version(),
            ip_address=self._get_local_ip(),
            instances=instances,
            agent_version=AGENT_VERSION,
        )
    
    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
```

---

## Шаг 3 — Server-Side Topology Handler

```python
# backend/routers/workstation_ws.py (добавить ветку)
elif msg_type == "workstation_register":
    payload = msg["payload"]
    # Upsert workstation
    await db.execute(
        text("""
            INSERT INTO workstations (id, org_id, hostname, os_version, ip_address, agent_version, last_seen)
            VALUES (:wid, :org_id, :hostname, :os_version, :ip, :agent_ver, now())
            ON CONFLICT (id) DO UPDATE
            SET hostname=EXCLUDED.hostname, ip_address=EXCLUDED.ip_address,
                agent_version=EXCLUDED.agent_version, last_seen=now()
        """),
        {
            "wid": payload["workstation_id"],
            "org_id": str(agent.org_id),
            "hostname": payload["hostname"],
            "os_version": payload["os_version"],
            "ip": payload["ip_address"],
            "agent_ver": payload["agent_version"],
        }
    )
    
    # Upsert экземпляры
    for inst in payload["instances"]:
        await db.execute(
            text("""
                INSERT INTO ldplayer_instances (workstation_id, index, name, adb_port, android_serial, org_id)
                VALUES (:wid, :idx, :name, :port, :serial, :org_id)
                ON CONFLICT (workstation_id, index) DO UPDATE
                SET name=EXCLUDED.name, adb_port=EXCLUDED.adb_port,
                    android_serial=EXCLUDED.android_serial
            """),
            {
                "wid": payload["workstation_id"],
                "idx": inst["index"],
                "name": inst["name"],
                "port": inst["adb_port"],
                "serial": inst.get("android_serial"),
                "org_id": str(agent.org_id),
            }
        )
    await db.commit()
    
    # Кэшируем в Redis
    topology_key = f"topology:workstation:{payload['workstation_id']}"
    await redis.setex(topology_key, 3600, json.dumps(payload))
```

---

## Шаг 4 — DB Migration (топология)

```sql
-- migrations/versions/0006_workstation_topology.sql
CREATE TABLE workstations (
    id              TEXT PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organizations(id),
    hostname        TEXT,
    os_version      TEXT,
    ip_address      TEXT,
    agent_version   TEXT,
    last_seen       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE ldplayer_instances (
    workstation_id  TEXT NOT NULL REFERENCES workstations(id),
    index           INTEGER NOT NULL,
    name            TEXT,
    adb_port        INTEGER,
    android_serial  TEXT,
    org_id          UUID NOT NULL,
    PRIMARY KEY (workstation_id, index)
);

CREATE INDEX ix_ldplayer_instances_org ON ldplayer_instances(org_id);
```

---

## Критерии готовности

- [ ] `report_on_connect()` отправляется сразу после WS auth успеха
- [ ] Upsert воркстанции: конфликт не ломает запрос
- [ ] Upsert экземпляров: (workstation_id, index) PK, обновляет name/port
- [ ] Redis кэш топологии TTL 1 час
- [ ] `_get_local_ip()` не крашит при отсутствии сети (fallback 127.0.0.1)
- [ ] Migration создаёт индекс по org_id на ldplayer_instances
