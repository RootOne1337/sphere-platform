# Changelog

All notable changes to **Sphere Platform** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

_No unreleased changes yet._

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

[4.0.0]: https://github.com/RootOne1337/sphere-platform/releases/tag/v4.0.0
