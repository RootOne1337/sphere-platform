# Changelog

All notable changes to **Sphere Platform** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

_Нет нереализованных изменений._

---

## [4.1.0] — 2026-02-25

### Краткое описание
TZ-12 Agent Discovery & Auto-Registration, DAG v6/v7 performance, расширение фронтенда задач, enterprise-тесты.
18+ коммитов на ветке `feature/dag-v6-task-execution-2025-02-25`, интегрировано через PR #4 → main → PR #5 → develop.

---

### Добавлено

#### TZ-12 — Agent Discovery & Auto-Registration
- `agent-config/` — конфигурационный репозиторий: JSON Schema v1, 3 окружения (dev, staging, production), batch-генератор
- `GET /api/v1/config/agent` — soft-auth эндпоинт конфигурации агента (отдаёт `ServerConfig` без обязательной авторизации)
- `POST /api/v1/devices/register` — идемпотентная авторегистрация устройств по fingerprint (JSONB-поиск)
- `DeviceRegistrationService` — авто-нейминг, генерация JWT-токенов, дедупликация по fingerprint
- `CloneDetector.kt` — clone-safe SHA-256 composite fingerprint (7 компонентов, безопасен для LDPlayer-клонов)
- `DeviceRegistrationClient.kt` — HTTP-клиент авторегистрации с авто-сохранением токенов
- `ZeroTouchProvisioner` source #6 — HTTP Config Endpoint
- `SetupActivity` — интеграция авторегистрации с legacy fallback

#### DAG v6/v7 — Движок автоматизации
- DAG v6: reactive smart scan, XPath-элементы, watchdog-оптимизация (`152d146`)
- DAG v7: устранение 3-минутных зависаний, оптимизация таймингов (`48e5081`)
- Расширен DAG-движок Android: `cancelRequested`, `increment_variable`, `find_first_element`, `tap_first_visible`
- `CANCEL_DAG` обработчик в `CommandDispatcher`

#### Backend — Task Execution
- Поля прогресса на модели Task: `cycles`, `started_at` (`0b99c35`)
- Эндпоинты `/progress`, `/live-logs`, `/stop` для задач (`6271665`)
- WebSocket progress handler для live execution logs (`bc9c996`)
- Расширен `TaskService`: dispatch `CANCEL_DAG`, bulk operations (`65ea409`)
- Улучшения WebSocket layer и middleware (`b0ff6ef`)

#### Frontend — Task Management UI
- `useTasks` расширен: `TaskProgress` с циклами + `useTaskLiveLogs` (`2f652cf`)
- Live Execution Dashboard — страница деталей задачи (`adaba59`)
- `RunScriptModal` + улучшены страницы Scripts и Tasks (`8efae3e`)
- OpenAPI 3.1 спецификация обновлена (`b95a907`)

#### Тестирование
- 17 тестов Agent Discovery (config endpoint + device register) (`4ab3eb3`)
- Enterprise-тесты: WS handlers, VPN health loop, n8n integration, user management, OTA updates (`609740f`)
- Service-layer unit-тесты, покрытие ≥ 70% (`5c5b05b`)
- Итого: **743 теста PASSED** (ruff 0 ошибок, mypy 0 ошибок)

---

### Исправлено

| # | Компонент | Проблема | Решение |
|---|-----------|----------|---------|
| 1 | Tests | SQLite не поддерживает ARRAY-тип | `SQLiteArrayType` bind/result processor (`e3722e8`) |
| 2 | Scripts | ruff E741 + import sorting в dev-скриптах | ruff auto-fix 23 ошибки → 0 (`e3c8ddd`) |
| 3 | CI | lint (ruff + mypy) и падающие тесты | Комплексное исправление (`177a961`) |
| 4 | Frontend | WebSocket URL определение в `useFleetEvents` | Исправлено (`2c562af`) |
| 5 | Android | Документация `LuaEngine` — ctx доступен как Lua-таблица | Исправлено (`a123404`) |
| 6 | CI | `PYTHONPATH`, alembic config path, gradlew +x | Серия фиксов (`befea81`, `a5b5692`, `425ec2d`) |
| 7 | Backend | `vpn_peers.status` отсутствовал в базовой миграции | Добавлен в baseline (`b25b49d`) |

---

### Deployment Notes

Новых обязательных переменных окружения нет.
Docker-образы: пересобрать backend и Android APK после merge.

```bash
# Пересборка backend
docker compose build backend

# Миграции (если обновлялись)
docker compose exec backend alembic upgrade head
```

---

## [4.0.0] — 2026-02-23

### Summary
Initial v4.0.0 platform release: full TZ-00 … TZ-11 implementation integrated into `develop`.
255 files changed, 25 779 insertions, 119 deletions across all subsystems.

---

### Added

#### TZ-00 — Infrastructure & CI/CD
- Docker Compose stack: `docker-compose.yml` + `docker-compose.full.yml` + `docker-compose.override.yml`
- Traefik reverse-proxy, nginx, PostgreSQL 15, Redis 7, Prometheus + Grafana
- GitHub Actions workflows: `ci-backend.yml`, `ci-android.yml`, `deploy-staging.yml`
- Pre-commit hooks (ruff, mypy, detect-secrets, commitlint)
- `scripts/generate_secrets.py` — one-shot `.env` secrets generator
- `scripts/create_admin.py` — idempotent super-admin bootstrapper
- `CODEOWNERS` and branch-protection rules

#### TZ-01 — Auth Service
- JWT access + refresh token pair (HS256) with 15-min access / 7-day refresh TTL
- TOTP-based MFA (`/auth/mfa/setup`, `/auth/mfa/verify`)
- RBAC: 7 roles — `super_admin`, `org_admin`, `operator`, `developer`, `viewer`, `api_key`, `pc_agent` — with PostgreSQL RLS enforcement
- API Key management (`/api-keys` CRUD)
- Audit log with RLS policies

#### TZ-02 — Device Registry
- Device CRUD with pagination and filtering
- Groups & Tags sub-resource
- Device status caching via Redis (`ONLINE/OFFLINE/BUSY/ERROR`)
- Bulk actions: assign group, add tag, change status
- Discovery endpoint — real WS RPC to PC Agent (`discover_adb` command)

#### TZ-03 — WebSocket Layer
- `ConnectionManager` with per-device fan-out
- Redis Pub/Sub router for cross-process messaging
- Backpressure: slow-consumer detection and disconnect
- Heartbeat: ping/pong with configurable TTL
- Typed event schema (`device.connected`, `device.status`, `stream.frame`, etc.)

#### TZ-04 — Script Engine
- DAG schema: nodes (action/condition/delay/loop), edges, validation
- Script CRUD (`/scripts`)
- Celery task queue with Redis broker
- Wave/batch execution: fan-out to device groups
- Progress API with SSE stream

#### TZ-05 — H.264 Streaming (Android)
- `MediaProjection` + `MediaCodec` encoder pipeline
- NAL unit framing over WebSocket binary
- Frame-drop policy under backpressure
- `WebCodecs`-based frontend decoder

#### TZ-06 — VPN / AmneziaWG
- `AWGConfigGenerator` — per-device WireGuard config
- IP pool manager with lease/release
- Self-healing monitor: reconnect on tunnel loss
- Kill-switch: iptables `SPHERE_KILLSWITCH` chain (Android side)
- REST API: `/vpn/peers`, `/vpn/pool/stats`, `/vpn/health`

#### TZ-07 — Android Agent
- Full Hilt DI architecture (`SphereApp` + WorkManager)
- WebSocket client with reconnect and binary frame handling
- Command handler: `adb_exec`, `screenshot`, `stream_start/stop`, `vpn_connect/disconnect`
- Live `SphereWebSocketClientLive` adapter wiring streaming module to real WS
- `KillSwitchManager` — iptables VPN kill-switch

#### TZ-08 — PC Agent
- `agent/` package: ADB bridge, topology discovery, telemetry, LDPlayer manager
- WebSocket client with JWT auth and command dispatch
- `pc-agent/main.py` launcher shim → `agent.main`

#### TZ-09 — n8n Integration
- Custom n8n node package (`n8n-nodes/`)
- Nodes: `SphereDevice`, `SphereScript`, `SphereEventTrigger`, `SphereDevicePool`
- OAuth2 + API Key credential types

#### TZ-10 — Web Frontend (Next.js 15)
- App Router layout with sidebar navigation
- Pages: Dashboard analytics, Devices, Groups, Scripts (DAG builder), VPN, Streaming, Settings
- `useDevices`, `useFleetStats`, `usePoolStats`, `useVpnHealth` hooks
- Auth loop fix: raw axios in `useInitAuth` to avoid interceptor recursion

#### TZ-11 — Monitoring
- Prometheus metrics middleware (request count, latency, active WS connections)
- Grafana dashboard provisioning
- Structured JSON logging (structlog)
- Health endpoints: `/health`, `/vpn/health`

---

### Fixed

| # | Component | Issue | Fix |
|---|-----------|-------|-----|
| 1 | Backend | VPN `/vpn/peers` returned 403 for super_admin | Replaced `require_role` with `require_permission("vpn:read")` |
| 2 | Backend | `GET /devices` 500 — `invalid input value for enum device_status_enum: ONLINE` | Added `values_callable=lambda x: [e.value for e in x]` to `DeviceStatus` column |
| 3 | Backend | Discovery service always returned `[]` | Real WS RPC via `PubSubRouter.send_command_wait_result("discover_adb")` |
| 4 | Backend | Missing `/vpn/health` endpoint | Added endpoint |
| 5 | Backend | `vpn_peers.status` column missing | `ALTER TABLE vpn_peers ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'assigned'` |
| 6 | Frontend | `scripts.map is not a function` | Handle paginated `{items,total}` response: `data.items ?? []` |
| 7 | Frontend | Auth infinite redirect loop on token refresh | Raw `axios.post('/auth/refresh')` in `useInitAuth` bypasses interceptor |
| 8 | Frontend | `useDevices` passed `page_size`, backend expects `per_page` | Param renamed in hook |
| 9 | Android | `SphereVpnManager.connect()` was a TODO stub | Full wg-quick integration with exponential backoff and Mutex safety |
| 10 | Android | `StreamingModule` bound no-op WS stub — frames discarded | Bind `SphereWebSocketClientLive` adapter |
| 11 | Android | Duplicate `@HiltAndroidApp` class caused build failure | Cleared `SphereApplication.kt` — canonical app is `SphereApp.kt` |
| 12 | PC Agent | `pc-agent/main.py` was `asyncio.sleep(0)` stub | Launcher shim: `from agent.main import main; asyncio.run(main())` |

---

### Deployment Notes

```sql
-- Run once before deploying this release:
ALTER TABLE vpn_peers ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'assigned';
```

Environment variables — no new required vars in this release.
Docker images — rebuild all services after merge (`docker compose build`).

---

## Previous releases

See `docs/merge_log.md` and [walkthrough.md.resolved](walkthrough.md.resolved) for full branch-by-branch integration history.

[4.1.0]: https://github.com/RootOne1337/sphere-platform/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/RootOne1337/sphere-platform/releases/tag/v4.0.0
