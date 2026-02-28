# Architecture

> **Sphere Platform v4.2** — System Design Reference

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Component Breakdown](#2-component-breakdown)
3. [Data Flow Diagrams](#3-data-flow-diagrams)
4. [Database Schema](#4-database-schema)
5. [Auth & Identity](#5-auth--identity)
6. [WebSocket Architecture](#6-websocket-architecture)
7. [VPN Architecture](#7-vpn-architecture)
8. [Streaming Pipeline](#8-streaming-pipeline)
9. [Script Engine & Task Queue](#9-script-engine--task-queue)
10. [Multi-tenancy & Isolation](#10-multi-tenancy--isolation)
11. [Observability](#11-observability)
12. [Deployment Topology](#12-deployment-topology)
13. [Agent Discovery & Auto-Registration](#13-agent-discovery--auto-registration)
14. [Pipeline Orchestrator Engine](#14-pipeline-orchestrator-engine)
15. [Cron Scheduler](#15-cron-scheduler)

---

## 1. High-Level Overview

Sphere Platform is structured as a **multi-tier, event-driven microservice monolith**:
the backend is a single FastAPI process augmented with asyncio background tasks and a Redis-backed
WebSocket pub/sub layer. This design avoids the operational overhead of microservices
while retaining horizontal scalability through stateless API workers.

```
╔═══════════════════════════════════════════════════════════════╗
║                        CLIENTS                                ║
║  Web Browser (Next.js)  │  Android APK  │  PC Agent (Python) ║
╚═════════════╤═══════════╧═══════════════╧═════════╤══════════╝
              │ HTTPS/WSS                            │ WSS
       ┌──────▼──────────────────────────────────────▼──────┐
       │                    nginx                            │
       │  TLS · Rate limit · Static files · WS upgrade      │
       └──────┬──────────────────────────────────────┬───────┘
              │ HTTP                                 │ WS
       ┌──────▼──────────┐               ┌───────────▼───────┐
       │  FastAPI (async)│               │ WebSocket Manager │
       │  API v1 router  │◄──────────────│ PubSub (Redis)    │
       └──────┬──────────┘               └───────────────────┘
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
PostgreSQL  Redis     asyncio
(SQLAlchemy) (cache,  Tasks
             pub/sub,  (фоновые
             rate-lim)  задачи)
```

---

## 2. Component Breakdown

### 2.1 Backend (FastAPI)

| Module | Path | Responsibility |
|--------|------|----------------|
| API Router | `backend/api/v1/` | HTTP endpoint dispatch |
| Auth | `api/v1/auth/` | JWT login, refresh, MFA, API keys |
| Devices | `api/v1/devices/` | CRUD, status, bulk actions, discovery |
| Groups | `api/v1/groups/` | Device grouping and tagging |
| Scripts | `api/v1/scripts/` | DAG script CRUD and execution |
| VPN | `api/v1/vpn/` | Peer management, IP pool, health |
| Streaming | `api/v1/streaming/` | Stream session lifecycle |
| Monitoring | `api/v1/monitoring/` | Health, metrics, pool stats |
| Audit | `api/v1/audit/` | Immutable audit log queries |
| Tasks | `backend/tasks/` | Фоновые asyncio-задачи |
| Services | `backend/services/` | Бизнес-логика (discovery, VPN, streaming, orchestrator, scheduler) |
| Orchestrator | `backend/services/orchestrator/` | PipelineService, PipelineExecutor, 9 StepHandler-ов |
| Scheduler | `backend/services/scheduler/` | ScheduleService, SchedulerEngine (croniter) |
| Pipelines API | `api/v1/pipelines/` | CRUD + execute + clone + runs + stats |
| Schedules API | `api/v1/schedules/` | CRUD + toggle + executions + dry-run |
| WebSocket | `backend/websocket/` | `ConnectionManager`, `PubSubRouter` |
| Core | `backend/core/` | Config, RBAC, security, dependencies |
| Models | `backend/models/` | SQLAlchemy ORM models |
| Schemas | `backend/schemas/` | Pydantic v2 request/response schemas |
| Middleware | `backend/middleware/` | Request ID, tenant, audit log, metrics |

### 2.2 Frontend (Next.js 15)

| Route | Description |
|-------|-------------|
| `/login` | JWT login form with MFA support |
| `/dashboard` | Fleet analytics: device count, VPN stats, system health |
| `/devices` | Device list with real-time status, search, bulk actions |
| `/scripts` | Script library + DAG builder (`@xyflow/react`) |
| `/stream` | Device selection → H.264 WebCodecs decoder |
| `/vpn` | Peer list, IP pool utilization, health, batch operations |

### 2.3 Android Agent

The APK runs as a persistent foreground service:

```
SphereApp (Hilt Application)
  └── SphereAgentService (Foreground Service)
        ├── SphereWebSocketClient  ← commands in / events out
        ├── CommandHandler         ← adb_exec, screenshot, stream_start/stop
        ├── StreamingModule        ← MediaProjection → MediaCodec → WS binary
        ├── SphereVpnManager       ← wg-quick tunnel lifecycle
        └── KillSwitchManager      ← iptables SPHERE_KILLSWITCH chain
```

### 2.4 PC Agent

Python asyncio daemon:

```
agent/main.py
  ├── WebSocketClient        ← JWT auth + command dispatch
  ├── ADBBridge              ← adb shell exec, device list
  ├── DiscoveryService       ← USB device enumeration
  ├── LDPlayerManager        ← emulator lifecycle
  └── TelemetryCollector     ← CPU/RAM/disk metrics → backend
```

---

## 3. Data Flow Diagrams

### 3.1 Authentication Flow

```
Client                   Backend              PostgreSQL       Redis
  │                         │                     │               │
  │─── POST /auth/login ───►│                     │               │
  │                         │──── SELECT user ───►│               │
  │                         │◄─── user row ────────│               │
  │                         │  verify bcrypt hash  │               │
  │                         │──── store refresh ──────────────────►│
  │◄── access_token (30m) ──│                     │               │
  │    refresh_token (7d)    │                     │               │
  │                         │                     │               │
  │─── POST /auth/refresh ─►│                     │               │
  │   (HttpOnly cookie)      │──── lookup token ──────────────────►│
  │◄── new access_token ────│                     │               │
```

### 3.2 Device Command Execution

```
Web UI          Backend API        Redis PubSub      Android Agent
  │                  │                  │                  │
  │─ POST /scripts/  │                  │                  │
  │   {id}/execute ─►│                  │                  │
  │                  │─ PUBLISH ────────►│                  │
  │                  │  device:{id}:cmd  │                  │
  │                  │                  │──── WS text ─────►│
  │                  │                  │   {"cmd":"..."}    │
  │                  │                  │                  │── execute
  │                  │                  │◄─ WS text ────────│
  │                  │                  │  {"result":"..."}  │
  │                  │◄─ SUBSCRIBE ─────│                  │
  │◄─ SSE progress ──│                  │                  │
```

### 3.3 H.264 Streaming

```
Android Agent                             Backend              Browser
     │                                       │                    │
     │  MediaProjection capture              │                    │
     │  → MediaCodec H.264 encode            │                    │
     │─── WS binary (NAL units) ────────────►│                    │
     │                                       │─ Redis PUBLISH ───►│ (via WS)
     │                                       │  stream:{device_id} │
     │                                       │                    │ WebCodecs
     │                                       │                    │ VideoDecoder
     │                                       │                    │ → canvas
```

---

## 4. Database Schema

### Core Entity Relationships

```
organizations
    │
    ├── users (org_id FK)
    │     ├── refresh_tokens
    │     ├── api_keys
    │     └── audit_logs (actor)
    │
    ├── devices (org_id FK)
    │     ├── device_group_members
    │     └── vpn_peers (device_id FK)
    │
    ├── device_groups (org_id FK)
    │     └── device_group_members
    │
    ├── scripts (org_id FK)
    │     └── task_batches (script_id FK)
    │           └── tasks (batch_id FK)
    │
    ├── pipelines (org_id FK)
    │     └── pipeline_runs (pipeline_id FK)
    │           └── pipeline_batches (run_id FK)
    │
    ├── schedules (org_id FK, pipeline_id FK)
    │     └── schedule_executions (schedule_id FK, pipeline_run_id FK)
    │
    └── workstations (org_id FK)
          └── ldplayer_instances
```

### Key Tables

| Table | Primary Key | RLS | Description |
|-------|-------------|-----|-------------|
| `organizations` | UUID | — | Tenant root |
| `users` | UUID | `org_id` | Platform users |
| `devices` | UUID | `org_id` | Android devices |
| `device_groups` | UUID | `org_id` | Device grouping |
| `scripts` | UUID | `org_id` | DAG scripts |
| `tasks` | UUID | `org_id` | Script execution tasks |
| `task_batches` | UUID | `org_id` | Wave/batch execution sets |
| `vpn_peers` | UUID | `org_id` | WG peer configs |
| `workstations` | UUID | `org_id` | PC Agent hosts |
| `audit_logs` | UUID | `org_id` | Immutable audit trail |
| `api_keys` | UUID | `user_id` | API key credentials |
| `refresh_tokens` | UUID | `user_id` | JWT refresh tokens |
| `pipelines` | UUID | `org_id` | Определения пайплайнов (steps, версионирование) |
| `pipeline_runs` | UUID | `org_id` | История запусков пайплайнов |
| `pipeline_batches` | UUID | `org_id` | Batch-группы устройств в run |
| `schedules` | UUID | `org_id` | Cron-расписания |
| `schedule_executions` | UUID | `org_id` | История срабатываний расписаний |

### Row-Level Security

All tenant tables use PostgreSQL RLS policies:

```sql
-- Example: devices table
CREATE POLICY devices_isolation ON devices
  USING (org_id = current_setting('app.current_org_id')::UUID);
```

The `tenant_middleware.py` sets `app.current_org_id` on every request from the JWT claim.

---

## 5. Auth & Identity

### JWT Token Flow

```
Login ──► access_token (HS256, 30 min, in-memory)
      ──► refresh_token (opaque UUID, 7 days, HttpOnly cookie → Redis)
```

Token claims:
```json
{
  "sub": "user-uuid",
  "org_id": "org-uuid",
  "role": "org_admin",
  "exp": 1234567890,
  "jti": "unique-token-id"
}
```

### RBAC Permission Matrix

| Permission | viewer | script_runner | device_manager | org_admin | org_owner | super_admin |
|-----------|--------|---------------|----------------|-----------|-----------|-------------|
| device:read | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| device:write | | | ✓ | ✓ | ✓ | ✓ |
| device:delete | | | | ✓ | ✓ | ✓ |
| device:bulk_action | | | ✓ | ✓ | ✓ | ✓ |
| script:read | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| script:write | | | ✓ | ✓ | ✓ | ✓ |
| script:execute | | ✓ | ✓ | ✓ | ✓ | ✓ |
| vpn:read | ✓ | | ✓ | ✓ | ✓ | ✓ |
| vpn:write | | | | ✓ | ✓ | ✓ |
| vpn:mass_operation | | | | ✓ | ✓ | ✓ |
| user:read | | | | ✓ | ✓ | ✓ |
| user:write | | | | | ✓ | ✓ |
| audit:read | | | | ✓ | ✓ | ✓ |
| pipeline:read | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| pipeline:write | | | ✓ | ✓ | ✓ | ✓ |
| pipeline:execute | | ✓ | ✓ | ✓ | ✓ | ✓ |
| schedule:read | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| schedule:write | | | | ✓ | ✓ | ✓ |

### MFA (TOTP)

1. `POST /auth/mfa/setup` — generates TOTP secret, returns QR code URI
2. User scans in Google Authenticator / Authy
3. `POST /auth/mfa/verify` — validates 6-digit code, activates MFA
4. Subsequent logins require `totp_code` field

---

## 6. WebSocket Architecture

### Connection Manager

```
Browser/Agent ──WS──► ConnectionManager
                           │
                           ├── device_connections: Dict[str, WebSocket]
                           ├── org_connections: Dict[str, Set[WebSocket]]
                           └── stream_sessions: Dict[str, Set[WebSocket]]
```

The `ConnectionManager` lives in-process. For multi-instance deployments, the
`PubSubRouter` bridges across processes via Redis Pub/Sub.

### Pub/Sub Channels

| Channel Pattern | Publisher | Subscriber | Payload |
|----------------|-----------|------------|---------|
| `device:{id}:cmd` | API handler | Android Agent | JSON command |
| `device:{id}:event` | Android Agent | API / frontend | JSON event |
| `stream:{id}` | Android Agent | Browser(s) | Binary NAL unit |
| `org:{id}:broadcast` | API handler | All org connections | JSON broadcast |
| `discovery:{ws_id}` | PC Agent | API discovery handler | JSON device list |

### Message Types

```typescript
// Inbound (from agent to backend)
{ "type": "device.status", "data": { "status": "ONLINE", "battery": 87 } }
{ "type": "command.result", "correlation_id": "...", "data": { "exit_code": 0, "stdout": "..." } }
{ "type": "stream.frame", "data": <binary NAL unit> }

// Outbound (from backend to agent)
{ "type": "command.execute", "correlation_id": "...", "data": { "cmd": "adb shell ls" } }
{ "type": "stream.start", "data": { "bitrate": 2000000, "fps": 30 } }
{ "type": "stream.stop" }
{ "type": "vpn.connect", "data": { "config_b64": "..." } }
```

### Backpressure

- Slow consumer detector: if send buffer exceeds 1 MB, connection is forcibly closed
- Frame drop policy: streaming frames are marked `DROPPABLE` — skipped if backlogged
- Heartbeat interval: 30s ping, 60s max silence before disconnect

---

## 7. VPN Architecture

AmneziaWG (AWG) — an obfuscated fork of WireGuard.

### IP Pool

```
VPN_POOL_SUBNET = 10.100.0.0/16  (65 534 possible peers)

Assignment:
  1. POST /vpn/peers { device_id }
  2. IpPoolManager.allocate() → next free IP from CIDR
  3. AWGConfigGenerator.build_peer_config(pubkey, ip) → wg config
  4. Config encrypted with Fernet(VPN_KEY_ENCRYPTION_KEY), stored in vpn_peers
  5. PUT /vpn/peers/{id}/activate → config delivered to device via WS
```

### Kill Switch (Android)

`KillSwitchManager` manages an `iptables` chain:

```
SPHERE_KILLSWITCH
  ACCEPT  lo
  ACCEPT  sphere0       ← VPN interface
  ACCEPT  [vpn_server_endpoint]/32
  DROP    all           ← blocks all non-VPN traffic
```

Enabled on VPN connect start, disabled on clean disconnect only.

### Self-Healing Monitor

`HealthMonitor` (APScheduler, 30s interval):
- Checks `sphere0` interface via `ConnectivityManager`
- Exponential backoff reconnect: `1s, 2s, 4s, 8s … 120s max`
- After 3 failed reconnects: emits `vpn.error` event to backend

---

## 8. Streaming Pipeline

### Android Side

```
Screen capture (MediaProjection)
  └──► Surface (InputSurface)
         └──► MediaCodec (H.264 baseline, configurable bitrate)
                └──► MediaCodec.Callback.onOutputBufferAvailable()
                       └──► NAL unit framing (4-byte length prefix)
                              └──► WebSocket.send(ByteString)
```

Configuration defaults:
- Codec: `video/avc` (H.264 Baseline)
- Bitrate: `2 Mbps` (configurable via `stream.start` command)
- Frame rate: `30 fps`
- I-frame interval: `1s`
- Frame drop: enabled under backpressure (non-key frames dropped first)

### Browser Side

```
WebSocket binary frame
  └──► ArrayBuffer (NAL units)
         └──► EncodedVideoChunk (WebCodecs API)
                └──► VideoDecoder (H.264)
                       └──► VideoFrame
                              └──► canvas.drawImage()
```

### Backend Relay

The backend acts as a relay only:
- Backend receives binary WS from agent → PUBLISH to Redis `stream:{id}` channel
- Frontend subscribes via WS → backend reads from Redis → forwards binary
- No transcoding, no buffering — zero-copy relay

---

## 9. Script Engine & Task Queue

### DAG Schema

```json
{
  "nodes": [
    { "id": "n1", "type": "action",    "data": { "cmd": "adb shell input tap 500 500" } },
    { "id": "n2", "type": "condition", "data": { "expr": "result.exit_code == 0" } },
    { "id": "n3", "type": "delay",     "data": { "ms": 1000 } },
    { "id": "n4", "type": "loop",      "data": { "count": 5, "target_node": "n1" } }
  ],
  "edges": [
    { "source": "n1", "target": "n2" },
    { "source": "n2", "target": "n3", "condition": "true" },
    { "source": "n3", "target": "n4" }
  ]
}
```

### Execution Flow

```
POST /scripts/{id}/execute
  │
  ├── Validate DAG (cycle detection, schema check)
  ├── Create TaskBatch record (status=PENDING)
  ├── Fan-out: for each device in target group
  │     └── asyncio task: execute_dag(script, device_id)
  │           ├── Walk DAG nodes topologically
  │           ├── For each action node: send WS command, await result
  │           ├── For each condition node: evaluate Python expr safely
  │           ├── For each delay node: asyncio.sleep(ms)
  │           └── Write Task result to DB
  └── SSE stream: GET /tasks/{batch_id}/progress (events: task.complete, batch.done)
```

### Wave Execution

Large device groups are split into **waves** to avoid overwhelming devices:
- Default wave size: 50 devices
- Inter-wave delay: 5s
- Max parallel tasks per wave: configurable via `TASK_WAVE_CONCURRENCY`

---

## 10. Multi-tenancy & Isolation

Every API request carries an `org_id` extracted from the JWT. The
`TenantMiddleware` sets the PostgreSQL session variable before any query:

```python
await conn.execute(
    text("SET LOCAL app.current_org_id = :org_id"),
    {"org_id": str(current_user.org_id)}
)
```

RLS policies on every table enforce that queries only return rows matching
`current_setting('app.current_org_id')`. This provides **database-level isolation**
even if application-level checks are accidentally bypassed.

Audit log entries capture `org_id`, `user_id`, action, resource, and remote IP for
every mutating API call.

---

## 11. Observability

### Metrics (Prometheus)

| Metric | Type | Labels |
|--------|------|--------|
| `http_requests_total` | Counter | method, endpoint, status |
| `http_request_duration_seconds` | Histogram | method, endpoint |
| `websocket_connections_active` | Gauge | org_id |
| `stream_bytes_sent_total` | Counter | device_id |
| `stream_keyframe_ratio` | Gauge | device_id |
| `vpn_pool_utilization` | Gauge | org_id |
| `task_queue_depth` | Gauge | queue_name |
| `pipeline_runs_total` | Counter | pipeline_id, status |
| `pipeline_run_duration_seconds` | Histogram | pipeline_id |
| `schedule_executions_total` | Counter | schedule_id, status |
| `scheduler_tick_duration_seconds` | Histogram | — |

Endpoint: `GET /metrics` (internal only, not exposed through nginx)

### Logging (structlog)

All logs are emitted as JSON:
```json
{
  "timestamp": "2026-02-23T10:00:00Z",
  "level": "info",
  "event": "device.connected",
  "device_id": "...",
  "org_id": "...",
  "request_id": "...",
  "latency_ms": 12
}
```

### Grafana Dashboards

| Dashboard | File |
|-----------|------|
| Fleet Overview | `infrastructure/monitoring/grafana/dashboards/fleet-overview.json` |
| VPN | `infrastructure/monitoring/grafana/dashboards/vpn.json` |
| Android Agents | `infrastructure/monitoring/grafana/dashboards/android-agents.json` |
| Performance | `infrastructure/monitoring/grafana/dashboards/performance.json` |

### Alerting (Alertmanager)

Alert rules defined in `infrastructure/monitoring/alert-rules.yml`:
- `BackendDown` — backend unreachable for > 1 min
- `HighErrorRate` — HTTP 5xx rate > 1% for 5 min
- `VpnPoolExhausted` — pool utilization > 90%
- `DeviceFleetOffline` — > 20% devices offline simultaneously

---

## 12. Deployment Topology

### Single-Host (Development / Small Production)

```
Host machine (8+ GB RAM, 4+ cores)
  └── Docker Compose
        ├── nginx          (port 80, 443)
        ├── backend        (port 8000, internal)
        ├── frontend       (port 3000, internal)
        ├── n8n            (port 5678, internal)
        ├── postgres       (port 5432, dev only)
        ├── redis          (port 6379, dev only)
        ├── prometheus     (port 9090, internal)
        ├── grafana        (port 3001, internal)
        └── alertmanager   (port 9093, internal)
```

### Multi-Host (Enterprise Production)

```
Load Balancer (HAProxy/AWS ALB)
  │
  ├── Backend cluster (N × FastAPI + Uvicorn)
  │     shared: PostgreSQL (primary + replica)
  │     shared: Redis Cluster (3 node minimum)
  │
  ├── Frontend CDN (Vercel / CloudFront)
  │
  ├── asyncio Task Workers (встроены в backend-процесс)
  │
  └── Monitoring stack (dedicated host)
        Prometheus + Grafana + Alertmanager + Loki
```

> For deployment instructions see [docs/deployment.md](deployment.md).

---

## 13. Agent Discovery & Auto-Registration

> Добавлено в v4.1.0 (TZ-12)

Модуль Agent Discovery решает проблему массового разворачивания агентов на LDPlayer-клонах:
все клоны делят одни и те же `ANDROID_ID`, `Build.SERIAL` и MAC-адрес, что делает невозможной
стандартную идентификацию. Решение — **composite fingerprint + zero-touch provisioning**.

### 13.1 Архитектура

```
┌──────────────────────────────────────────────────────┐
│                  agent-config/                         │
│  environments/  schema/  tools/                       │
│  (dev.json,     (v1/)   (batch_generate.py)           │
│   staging.json,                                       │
│   production.json)                                    │
└──────────────────────┬───────────────────────────────┘
                       │ загружается при старте
                       ▼
┌──────────────────────────────────────────────────────┐
│  Backend: GET /api/v1/config/agent                    │
│  (soft-auth — без обязательной авторизации)           │
│  AgentConfigService → Redis кэш (TTL 300s)           │
└──────────────────────┬───────────────────────────────┘
                       │ ServerConfig JSON
                       ▼
┌──────────────────────────────────────────────────────┐
│  Android Agent: ZeroTouchProvisioner                  │
│  Source #6: HTTP Config Endpoint                      │
│  1. Получить ServerConfig                             │
│  2. Если autoRegister=true → зарегистрироваться       │
└──────────────────────┬───────────────────────────────┘
                       │ fingerprint + device_info
                       ▼
┌──────────────────────────────────────────────────────┐
│  Backend: POST /api/v1/devices/register               │
│  DeviceRegistrationService:                           │
│   - JSONB fingerprint search (дедупликация)           │
│   - Авто-нейминг: sphere-{org_prefix}-{seq}          │
│   - Генерация JWT access + refresh токенов            │
│   - Возврат device_id + tokens → агент готов          │
└──────────────────────────────────────────────────────┘
```

### 13.2 CloneDetector — Composite Fingerprint

Android-агент вычисляет SHA-256 fingerprint из 7 компонентов:

| # | Компонент | Описание | Clone-safe |
|---|-----------|----------|------------|
| 1 | `/proc/self/cgroup` hash | Уникален для каждого контейнера LDPlayer | ✓ |
| 2 | `/proc/uptime` boot time | Время загрузки инстанса | ✓ |
| 3 | `ActivityManager` task list hash | Набор запущенных задач | ✓ |
| 4 | Allocated memory pages | Физическая раскладка памяти | ✓ |
| 5 | `Build.DISPLAY` | Build fingerprint (shared на клонах) | ✗ |
| 6 | Random UUID (fallback) | Генерируется при первом запуске | ✓ |
| 7 | Canvas rendering hash | GPU fingerprint | ~ |

Итоговый fingerprint: `SHA-256(component1 + component2 + ... + component7)`

Даже на идентичных LDPlayer-клонах компоненты 1–4 гарантируют уникальность.

### 13.3 Конфигурационный репозиторий

Структура `agent-config/`:

```
agent-config/
├── schema/v1/agent-config.schema.json   # JSON Schema валидации
├── environments/
│   ├── dev.json           # Локальная разработка (autoRegister: true)
│   ├── staging.json       # Staging (autoRegister: true, restrictedMode)
│   └── production.json    # Продакшн (autoRegister: false по умолчанию)
├── tools/
│   └── batch_generate.py  # Генератор batch-конфигов для массовых деплоев
└── README.md
```

Конфигурация кэшируется в Redis (TTL = `AGENT_CONFIG_CACHE_TTL`, по умолчанию 300s).
`AGENT_CONFIG_ENV` определяет активное окружение (dev / staging / production).

### 13.4 Безопасность

- **Soft-auth**: `GET /config/agent` доступен без токена, но rate-limited (10 req/min per IP)
- **Fingerprint в JSONB**: позволяет эффективный поиск по `@>` оператору PostgreSQL
- **Идемпотентная регистрация**: повторный вызов с тем же fingerprint возвращает существующее устройство
- **JWT токены**: регистрация возвращает полноценную пару access/refresh, агент сразу готов к работе
- **Нет секретов в конфиге**: agent-config не содержит ключей, только URL + policy флаги

---

## 14. Pipeline Orchestrator Engine

> Добавлено в v4.2.0 (TZ-12 SPLIT-4)

Pipeline Orchestrator объединяет скрипты, условия, HTTP-вызовы, задержки и уведомления
в управляемые цепочки с персистенцией состояния и поддержкой вложенного запуска.

### 14.1 Архитектура

```
REST API (/pipelines)
  │
  ├── PipelineService          ← CRUD, клонирование, версионирование
  │     └── Pipeline ORM model ← steps (JSONB), status lifecycle: draft → active → archived
  │
  └── PipelineExecutor         ← движок исполнения
        ├── StepRouter         ← маршрутизатор по step.type
        │     ├── run_script   ← запуск DAG-скрипта через WS
        │     ├── run_pipeline ← вложенный запуск Pipeline (рекурсия с лимитом)
        │     ├── http_request ← HTTP-вызов внешнего API
        │     ├── condition    ← if/else по выражению
        │     ├── delay        ← asyncio.sleep()
        │     ├── parallel     ← asyncio.gather() подшагов
        │     ├── set_variable ← запись в контекст выполнения
        │     ├── notify       ← webhook / email
        │     └── approval     ← ручное подтверждение оператором
        │
        └── PipelineRun ORM    ← персистенция: state, step_results, timing
              └── PipelineBatch ← группировка устройств в run
```

### 14.2 Модель данных

| Таблица | Описание | Ключевые поля |
|---------|----------|---------------|
| `pipelines` | Определения пайплайнов | `name`, `steps` (JSONB), `status`, `version`, `org_id` |
| `pipeline_runs` | Запуски | `pipeline_id`, `status`, `variables`, `step_results`, `started_at`, `finished_at` |
| `pipeline_batches` | Batch группировка устройств | `run_id`, `device_ids`, `status` |

### 14.3 Lifecycle пайплайна

```
draft ──(activate)──► active ──(archive)──► archived
  ▲                     │
  └──(clone)────────────┘
```

- **draft**: редактируемый, нельзя запустить
- **active**: можно запускать (execute)
- **archived**: только чтение, нельзя запустить

### 14.4 Исполнение

1. `POST /pipelines/{id}/execute` → создаёт `PipelineRun` (status=running)
2. `PipelineExecutor` обходит steps последовательно (или parallel для `parallel` типа)
3. Каждый step записывает результат в `step_results` JSONB
4. При ошибке — run переходит в `failed`, context сохраняется для отладки
5. `condition` step может разветвить поток на `on_true` / `on_false`

---

## 15. Cron Scheduler

> Добавлено в v4.2.0 (TZ-12 SPLIT-5)

DB-backed планировщик для автоматического запуска пайплайнов по cron-расписанию
с поддержкой таймзон и политик конфликтов.

### 15.1 Архитектура

```
SchedulerEngine (фоновый asyncio-цикл, тик = 60с)
  │
  ├── SELECT ... WHERE enabled = true AND next_run_at <= NOW()
  │   FOR UPDATE SKIP LOCKED   ← конкурентная безопасность
  │
  ├── Для каждого сработавшего Schedule:
  │     ├── Проверка conflict_policy (skip / queue)
  │     ├── Вызов PipelineExecutor.execute()
  │     ├── Создание ScheduleExecution записи
  │     └── Пересчёт next_run_at через croniter
  │
  └── ScheduleService  ← CRUD, валидация cron, toggle, dry-run
        └── Schedule ORM model
```

### 15.2 Модель данных

| Таблица | Описание | Ключевые поля |
|---------|----------|---------------|
| `schedules` | Определения расписаний | `cron_expression`, `timezone`, `pipeline_id`, `enabled`, `conflict_policy`, `next_run_at` |
| `schedule_executions` | История срабатываний | `schedule_id`, `pipeline_run_id`, `status`, `triggered_at`, `finished_at` |

### 15.3 Политики конфликтов

| Policy | Поведение |
|--------|-----------|
| `skip` | Если предыдущий run ещё выполняется — пропустить текущий тик |
| `queue` | Поставить в очередь и запустить после завершения текущего run |

### 15.4 Зависимости

- **croniter** — парсинг и итерация cron-выражений (включая 5-полевый формат)
- **pytz** — поддержка IANA таймзон (Europe/Moscow, America/New_York, etc.)

### 15.5 Безопасность

- `FOR UPDATE SKIP LOCKED` предотвращает double-execute при горизонтальном масштабировании
- Все расписания привязаны к `org_id` — RLS обеспечивает tenant-изоляцию
- Валидация cron-выражений на уровне API (невалидный cron = 422)
