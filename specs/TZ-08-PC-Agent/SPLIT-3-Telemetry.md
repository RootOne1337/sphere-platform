# SPLIT-3 — Telemetry (psutil → сервер)

**ТЗ-родитель:** TZ-08-PC-Agent  
**Ветка:** `stage/8-pc-agent`  
**Задача:** `SPHERE-043`  
**Исполнитель:** Backend/Python  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Интеграция при merge:** TZ-09 n8n работает с mock telemetry; при merge подключить реальные метрики

> [!NOTE]
> **MERGE-13: При merge `stage/8-pc-agent` + `stage/9-n8n`:**
>
> 1. n8n DevicePool node → подключить реальный topology API (TZ-08 SPLIT-5) для запроса доступных workstations
> 2. Telemetry метрики ПК → доступны через WS message type `telemetry` (не отдельный endpoint)

---

## Цель Сплита

Периодически собирать системные метрики воркстанции (CPU, RAM, диск, сеть) и отправлять в бэкенд через WebSocket.

---

## Шаг 1 — WorkstationTelemetry схема

```python
# agent/models.py (добавить)
class NetworkStats(BaseModel):
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int

class DiskStats(BaseModel):
    path: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float

class WorkstationTelemetry(BaseModel):
    workstation_id: str
    timestamp: float
    cpu_percent: float
    cpu_count: int
    ram_total_mb: int
    ram_used_mb: int
    ram_percent: float
    disk: list[DiskStats]
    network: NetworkStats
    ldplayer_instances_running: int
```

---

## Шаг 2 — TelemetryReporter

```python
# agent/telemetry.py
import asyncio
import time
import psutil
from loguru import logger
from .config import config
from .models import WorkstationTelemetry, NetworkStats, DiskStats

class TelemetryReporter:
    def __init__(self, ws_client, ldplayer_mgr=None):
        self.ws_client = ws_client
        self.ldplayer_mgr = ldplayer_mgr
        self._last_net = psutil.net_io_counters()
        self._last_net_ts = time.monotonic()
    
    async def run(self):
        while True:
            try:
                await asyncio.sleep(config.telemetry_interval)
                telemetry = await self._collect()
                await self.ws_client.send({
                    "type": "workstation_telemetry",
                    "payload": telemetry.model_dump(),
                })
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Telemetry error: {e}")
    
    async def _collect(self) -> WorkstationTelemetry:
        # CPU (1-second interval sample)
        # ⚠️ ВАЖНО: asyncio.get_running_loop(), не get_event_loop() (deprecated в 3.10+)
        cpu_pct = await asyncio.get_running_loop().run_in_executor(
            None, lambda: psutil.cpu_percent(interval=1)
        )
        
        mem = psutil.virtual_memory()
        
        # Диски
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append(DiskStats(
                    path=part.mountpoint,
                    total_gb=round(usage.total / 1024**3, 2),
                    used_gb=round(usage.used / 1024**3, 2),
                    free_gb=round(usage.free / 1024**3, 2),
                    percent=usage.percent,
                ))
            except PermissionError:
                pass
        
        # Сеть (delta)
        curr_net = psutil.net_io_counters()
        net = NetworkStats(
            bytes_sent=curr_net.bytes_sent,
            bytes_recv=curr_net.bytes_recv,
            packets_sent=curr_net.packets_sent,
            packets_recv=curr_net.packets_recv,
        )
        
        # LDPlayer running count
        running_count = 0
        if self.ldplayer_mgr:
            try:
                instances = await self.ldplayer_mgr.list_instances()
                running_count = sum(1 for i in instances if i.status.value == "running")
            except Exception:
                pass
        
        return WorkstationTelemetry(
            workstation_id=config.workstation_id,
            timestamp=time.time(),
            cpu_percent=cpu_pct,
            cpu_count=psutil.cpu_count(logical=True),
            ram_total_mb=mem.total // 1024**2,
            ram_used_mb=mem.used // 1024**2,
            ram_percent=mem.percent,
            disk=disks,
            network=net,
            ldplayer_instances_running=running_count,
        )
```

---

## Шаг 3 — Серверный endpoint приёма

```python
# backend/routers/workstation_ws.py (в бэкенде)
#
# FIX 8.1: ДУБЛИРУЮЩИЙ WS ENDPOINT УДАЛЁН!
# ──────────────────────────────────────────────────────────────────
# БЫЛО: @router.websocket("/ws/agent/{workstation_id}") — ВТОРОЙ endpoint
#   → Конфликт с TZ-03 SPLIT-1 backend/api/ws/agent/router.py
#   → FastAPI поведение при дубле WS endpoint недетерминировано:
#     один из двух обработчиков "выиграет" при mount, второй — мёртвый код
#
# СТАЛО: Обработка телеметрии через CASE в едином endpoint (TZ-03 SPLIT-1)
# В backend/api/ws/agent/router.py — handle_agent_message():
# ──────────────────────────────────────────────────────────────────

# Добавить в handle_agent_message() (TZ-03 SPLIT-1, стр. 341):
async def handle_workstation_telemetry(
    workstation_id: str,
    payload: dict,
    redis: Redis,
    org_id: str,
):
    """Обработчик телеметрии — вызывается из единого WS endpoint."""
    key = f"workstation:telemetry:{workstation_id}"
    await redis.setex(key, 120, json.dumps(payload))
    # Публикуем событие для дашборда
    await redis.publish(
        f"sphere:org:events:{org_id}",
        json.dumps({"type": "workstation_telemetry", "data": payload}),
    )
```

---

## Критерии готовности

- [ ] `cpu_percent(interval=1)` запускается в executor (не блокирует event loop)
- [ ] disk_partitions только физические диски (all=False)
- [ ] LDPlayer running count не крашит при недоступном LDPlayer
- [ ] Интервал телеметрии из конфига (по умолчанию 30 секунд)
- [ ] Telemetry продолжает работать при ошибке сбора (except Exception)
- [ ] Бэкенд хранит в Redis с TTL 120s (stale data detection)
