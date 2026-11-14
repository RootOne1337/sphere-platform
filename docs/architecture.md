# Architecture

> **Architecture overview.** This page maps components and links to their
> maintained contracts. Implementation, deployed versions and historical evidence
> are separate; examples and acceptance claims require verification in the target
> environment. [Documentation index](README.md) · [Recorded state](operations/CURRENT-STATE.md).

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

Sphere Platform combines a FastAPI backend, web frontend, Android and PC agents,
PostgreSQL and Redis. Background workers and WebSocket coordination are part of
the backend design. The deployment topology and scalability require verification
for the selected environment.

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
| Audit | `api/v1/audit/` | Audit log queries; integrity depends on database roles and policy |
| Tasks | `backend/tasks/` | Фоновые asyncio-задачи |
| Services | `backend/services/` | Бизнес-логика (discovery, VPN, streaming, orchestrator, scheduler) |
| Orchestrator | `backend/services/orchestrator/` | PipelineService, PipelineExecutor, 9 StepHandler-ов |
| Scheduler | `backend/services/scheduler/` | ScheduleService, SchedulerEngine (croniter) |
| Pipelines API | `api/v1/pipelines/` | CRUD + execute + clone + runs + stats |
| Schedules API | `api/v1/schedules/` | CRUD + toggle + executions + dry-run |
| Batches API | `api/v1/batches/` | Bulk batch operations on devices/tasks |
| Game Accounts | `api/v1/game_accounts/` | In-game account CRUD with nick generation |
| Event Triggers | `api/v1/event_triggers/` | Configurable event-driven automation rules |
| Pipeline Settings | `api/v1/pipeline_settings/` | Per-pipeline configuration persistence |
| Account Sessions | `api/v1/account_sessions/` | Active account session tracking per device |
| Device Events | `api/v1/device_events/` | Device lifecycle event logging and queries |
| Event Reactor | `backend/services/event_reactor.py` | Reactive event processing engine |
| Orchestration Engine | `backend/services/orchestrator/orchestration_engine.py` | Pipeline orchestration coordinator |
| Nick Generator | `backend/services/nick_generator.py` | Random nickname generation utility |
| Task Heartbeat | `backend/tasks/task_heartbeat_watchdog.py` | Background: watchdog for stale tasks |
| Orchestration Loop | `backend/tasks/orchestration_loop.py` | Background: periodic orchestration tick |
| WebSocket | `backend/websocket/` | `ConnectionManager`, `PubSubRouter` |
| Core | `backend/core/` | Config, RBAC, security, dependencies |
| Models | `backend/models/` | SQLAlchemy ORM models |
| Schemas | `backend/schemas/` | Pydantic v2 request/response schemas |
| Middleware | `backend/middleware/` | Request ID, tenant, audit log, metrics |

### 2.2 Frontend (Next.js 15)

The App Router serves the operator interface. The complete source route inventory,
including `/fleet` redirecting to `/groups`, is maintained in the
[Web UI guide](web-ui-guide.md). Session and capability checks gate navigation and
actions; they do not replace backend authorization. The installed frontend may
not be the same revision as this source tree.

### 2.3 Android Agent

The Android application manages enrollment, connection, commands, capture and
supported network operations. Available execution paths depend on the installed
APK, device privileges, policy and supported capabilities. See the
[Android agent guide](android-agent.md), [connection protocol](architecture/ANDROID-CONNECTION-PROTOCOL.md)
and [VPN outcomes](operations/VPN-CONTROL-OUTCOMES.md). A captured frame or
accepted command is not proof that an end-to-end user scenario completed.

### 2.4 PC Agent

The Python agent connects a workstation to the backend and provides its implemented
host and emulator commands. Its dispatcher is the source of supported commands:
[PC agent guide](pc-agent.md). In particular, the discovery UI's `discover_adb`
request is not implemented by that dispatcher in the reviewed source; an empty
result is not evidence that an ADB scan succeeded. [Limits](operations/DEVICE-STREAM-GUIDE.md).

---

## 3. Data Flow Diagrams

### 3.1 Authentication Flow

Login checks the user's credentials and may require a separate MFA challenge.
The access token is a JWT; the opaque refresh token is stored as a SHA-256 hash in
PostgreSQL and rotated on use. The browser uses an HttpOnly cookie and retains a
JavaScript-readable fallback when a refresh token is returned. Cookie attributes
depend on configuration and request scheme. See [auth API](api-reference.md#auth--auth)
and [frontend sessions](security/frontend-sessions.md).

### 3.2 Device Command Execution

A task or interactive request passes authentication and authorization, reaches the
agent through the appropriate delivery path, and may produce a receipt and later
result. The acknowledgement, terminal result and physical state are distinct.
Unknown outcomes must not be retried as if failure were confirmed. See
[task control](security/task-control-protocol.md), [Android connection](architecture/ANDROID-CONNECTION-PROTOCOL.md)
and [device actions](operations/DEVICE-STREAM-GUIDE.md).

### 3.3 H.264 Streaming

Android captures and encodes video; the browser can receive it through available
relay or direct transports. A source frame, transport delivery and decoded display
are separate observations. Availability, rate and latency vary by source, APK,
network and browser; no transport or frame-rate SLA follows from this diagram.
See [stream actions](operations/DEVICE-STREAM-GUIDE.md) and
[connection protocol](architecture/ANDROID-CONNECTION-PROTOCOL.md).

---

## 4. Database Schema

### Core Entity Relationships

The following is an illustrative overview, not a migration or a complete schema.
Use the current models and Alembic revisions for exact fields and constraints.

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
| `audit_logs` | UUID | `org_id` | Audit records; protection depends on effective role and policies |
| `api_keys` | UUID | `user_id` | API key credentials |
| `refresh_tokens` | UUID | `user_id` | Hashed opaque user refresh tokens |
| `pipelines` | UUID | `org_id` | Определения пайплайнов (steps, версионирование) |
| `pipeline_runs` | UUID | `org_id` | История запусков пайплайнов |
| `pipeline_batches` | UUID | `org_id` | Batch-группы устройств в run |
| `schedules` | UUID | `org_id` | Cron-расписания |
| `schedule_executions` | UUID | `org_id` | История срабатываний расписаний |

### Row-Level Security

Tenant isolation depends on the transaction-bound database context, the active
policies and the database role's privileges; a privileged or owner role can change
the guarantees. Authentication, middleware and `get_db()` alone do not prove that
all paths are isolated. See the [PostgreSQL RLS contract](security/postgresql-rls.md)
and the migration/runtime-role limitations described there.

---

## 5. Auth & Identity

### JWT Token Flow

Access JWTs and opaque refresh tokens have different lifecycles. The refresh-token
hash and revocation state are persisted in PostgreSQL; the browser cookie and
JavaScript-readable fallback have different security properties. Token lifetime and
cookie settings depend on configuration. The [session contract](security/frontend-sessions.md)
describes refresh races, failure handling and logout boundaries.

### RBAC Permission Matrix

The effective role-to-permission mapping is defined by
[backend/core/rbac.py](../backend/core/rbac.py); route dependencies and object/role
checks additionally determine access. Use [user access](operations/USER-ACCESS.md)
and [API reference](api-reference.md) for the relevant workflow. A client-side
visibility gate is not authorization, and a static matrix cannot describe every
route-specific restriction.

### MFA (TOTP)

`POST /auth/mfa/setup` creates a pending setup and returns a secret and QR image;
`POST /auth/mfa/verify-setup` confirms the code. Login for an MFA-enabled user
returns a challenge which is completed through `POST /auth/login/mfa`. See
[auth API](api-reference.md#auth--auth) and [operator guidance](operations/WEB-ENTRY-GUIDE.md).

---

<a id="websocket-architecture"></a>
## 6. WebSocket Architecture

The backend maintains authenticated connections for agents and viewers and uses
Redis for cross-process coordination. Ownership, tenant boundaries, acknowledgements,
backpressure and recovery depend on the particular channel; do not treat a
conceptual channel name or a generic JSON example as the wire contract.
See [Android connection protocol](architecture/ANDROID-CONNECTION-PROTOCOL.md),
[continuous input](protocols/CONTINUOUS-INPUT-SERVER.md),
[receipts](protocols/CONTINUOUS-INPUT-RECEIPTS.md) and the
[WebSocket source](../backend/websocket/). A connection or published message does
not establish that an Android action completed.

---

## 7. VPN Architecture

VPN profiles, catalog state, provider/peer configuration and Android tunnel state
are different concerns. Saved configuration and server-side health are not proof
of device traffic isolation, kill-switch behavior or recovery after reboot. Use
[VPN profiles](operations/VPN-PROFILES.md), [control outcomes](operations/VPN-CONTROL-OUTCOMES.md)
and the [Android VPN observation](audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION.md)
for concrete capabilities and evidence. The latter describes a dated experiment,
not a current fleet guarantee.

---

## 8. Streaming Pipeline

Video capture, encoding, delivery and browser decoding are independently observable
stages. The relay and direct paths have distinct setup, fallback and diagnostic
conditions; cached metadata or a connected viewer does not guarantee a new frame,
latency or frame rate. Settings are targets, not measurements. See the
[device and stream guide](operations/DEVICE-STREAM-GUIDE.md),
[Android connection protocol](architecture/ANDROID-CONNECTION-PROTOCOL.md),
and [video cadence canary](operations/VIDEO-CADENCE-CANARY.md).

---

<a id="script-engine--dag-execution"></a>
## 9. Script Engine & Task Queue

Script versions contain validated DAG data; Studio editing, server-side structural
validation, publication, admission and execution are distinct stages. The
validation response explicitly does not prove device execution or installed APK
capabilities. Use the [Studio guide](operations/SCRIPT-STUDIO.md),
[version contract](operations/SCRIPT-VERSIONS.md), [tasks and orchestration](operations/TASKS-AND-ORCHESTRATION.md)
and [schemas](../backend/schemas/script.py) instead of a duplicated example.
Broadcast and version-pinned launches have different admission conditions.

---

## 10. Multi-tenancy & Isolation

Organization identity is established by the applicable authentication path; tenant
context must be bound before data access and maintained across transaction
boundaries. PostgreSQL RLS relies on policies, grants and a non-bypassing runtime
role, not on a middleware statement alone. Coverage varies by path, role and
migration state. See [RLS](security/postgresql-rls.md),
[worker isolation](audits/2026-09-20/PIPELINE-RLS.md) and
[authentication bootstrap](security/user-auth-bootstrap.md).

---

## 11. Observability

Monitoring combines backend health, metrics, Prometheus and optional Grafana.
Coverage, scrape configuration and deployed services vary by environment. Missing
or stale measurements must not be interpreted as zero or as a healthy device.
Consult the [observability guide](operations/OBSERVABILITY.md),
[HTTP metrics](operations/HTTP-METRICS.md), [device logs](operations/DEVICE-LOG-STORAGE.md)
and the source [monitoring configuration](../infrastructure/monitoring/).

The source [`GET /api/v1/streaming/{device_id}/status`](../backend/api/v1/streaming/router.py)
sets `viewer_connected` from `is_streaming`; when no bridge is available it uses a
`drop_ratio` of zero. Neither value independently proves a connected viewer or
absence of frame loss. The separate device stream-diagnostics endpoint reports a
bounded, freshness-checked agent snapshot, not browser rendering. Validate the
deployed revision and actual telemetry before drawing runtime conclusions.

---

## 12. Deployment Topology

The repository provides Compose configurations and launchers for different
contexts. The selected project, files, env, volumes, ingress and images determine
what is actually running. Multi-host layouts, redundancy, scaling and zero-downtime
are deployment designs requiring their own verification; they are not established
by an example diagram. Follow [deployment](deployment.md), [startup](operations/STARTUP.md)
and [readiness](operations/READINESS.md) for the selected environment.

---

## 13. Agent Discovery & Auto-Registration

Device enrollment uses a scoped enrollment credential and a fingerprint with an
optional instance binding; copied identifiers or a copied APK do not prove a unique
clone. Registration returns credentials, not a guarantee that the device is online
or ready to execute. The optional-key configuration endpoint and the separately
authorized registration route have different boundaries. The manual PC discovery
path currently has the dispatcher limitation described in the
[device guide](operations/DEVICE-STREAM-GUIDE.md).

See [device bootstrap](security/device-credential-bootstrap.md),
[Android bootstrap discovery](architecture/ANDROID-BOOTSTRAP-DISCOVERY.md),
[discovery recovery](architecture/ANDROID-DISCOVERY-RECOVERY.md) and
[registered API](api-endpoints.md).

---

## 14. Pipeline Orchestrator Engine

Pipeline definitions, runs and batches are persisted separately. Supported step
names and fields are defined by [pipeline schemas](../backend/schemas/pipeline.py),
not by an illustrative step list. Admission, durable execution, child task results
and cancellation are separate stages. See [pipeline definitions](operations/PIPELINE-DEFINITIONS.md),
[tasks and orchestration](operations/TASKS-AND-ORCHESTRATION.md) and
[task control](security/task-control-protocol.md).

---

## 15. Cron Scheduler

The scheduler stores definitions and execution records and supports multiple
trigger forms and conflict policies. A scheduled or admitted run is not an
execution receipt from a device. In the current UI newly created schedules are
submitted active, and one-shot input is interpreted in UTC. Check the target,
time and selected environment before saving; disabling a schedule does not stop
already created tasks. [Operator workflow](operations/TASKS-AND-ORCHESTRATION.md)
and [scheduler runtime evidence](audits/2026-09-20/SCHEDULER-RUNTIME.md).
