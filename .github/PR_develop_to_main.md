# PR: feat — Sphere Platform v1.0 — Full TZ-00..TZ-11 implementation

**Branch:** `develop` → `main`
**Scope:** 255 files changed · 25 779 insertions · 119 deletions

---

## Description

This PR merges the complete implementation of all 12 technical specifications
(TZ-00 through TZ-11) from `develop` into `main`, making the platform production-ready.

It includes a **gap-analysis response pass** that filled the following real gaps
found during architect review:

| Component | Gap | Resolution |
|-----------|-----|------------|
| Android | `SphereVpnManager` was a TODO stub | Full wg-quick integration |
| Android | `StreamingModule` bound a no-op WS stub | Wired `SphereWebSocketClientLive` |
| Android | Duplicate `@HiltAndroidApp` broke build | Cleared `SphereApplication.kt` |
| Backend | `/vpn/peers` 403 for super_admin | `require_permission("vpn:read")` |
| Backend | `GET /devices` 500 on enum | `values_callable` on `DeviceStatus` |
| Backend | Discovery always returned `[]` | Real WS RPC to PC Agent |
| Frontend | `scripts.map is not a function` | Handle paginated response |
| Frontend | Auth infinite redirect loop | Raw axios in `useInitAuth` |
| PC Agent | `main.py` was `asyncio.sleep(0)` | Launcher shim to `agent.main` |

---

## Commits (develop ahead of main — 30 commits)

```
c19e11c chore: dev infrastructure — override compose, dev Dockerfiles, nginx, admin script, openapi
83a2fbf fix(pc-agent): replace stub entrypoint with launcher shim (TZ-08)
d334abe fix(frontend): auth loop + API params + scripts pagination + Dashboard page (TZ-10)
36b5902 fix(backend): VPN router permissions + device enum + real discovery RPC (TZ-02/06)
cc5ae90 fix(android): implement SphereVpnManager + KillSwitch + live WS wiring (TZ-06/07)
7ba498f fix: backend startup + alembic migrations
3e74cfd fix: remove duplicate require_role definition, keep single canonical implementation
1c36c26 docs: complete merge log with all 6 phases, 10 conflicts resolved, statistics
3ac8910 merge: Phase 6 — TZ-10 Frontend into develop
f45e48d merge: Phase 5 — TZ-09 n8n Integration into develop
2e87cf7 merge: Phase 4b — TZ-08 PC Agent into develop
5802207 merge: Phase 4a — TZ-07 Android Agent into develop
de448b4 merge: Phase 3b — TZ-06 VPN AmneziaWG into develop
44d0e7f merge: Phase 3a — TZ-05 H264 Streaming into develop
f06c87f merge: Phase 2+3 — TZ-01..TZ-04 Auth/Devices/WebSocket/Scripts into develop
c564d02 merge: Phase 1 — TZ-11 Monitoring into develop
```

---

## Type of change
- [x] feat: new feature (full platform implementation)
- [x] fix: bug fixes (12 runtime issues resolved)
- [x] chore: build / infra / tooling

## Linked to
SPHERE-001 … SPHERE-056 (all TZ tasks)

---

## Checklist
- [x] All 55+ PC Agent architecture tests pass
- [x] Backend health endpoints (`/health`, `/vpn/health`) return 200
- [x] VPN API (`/vpn/peers`, `/vpn/pool/stats`) return 200 for super_admin
- [x] Device list (`/devices`) returns data without 500
- [x] Frontend auth flow does not loop
- [x] No secrets committed (`detect-secrets` baseline present)
- [x] Migrations reversible (Alembic downgrade chain intact)
- [ ] `ruff check` — run before final merge
- [ ] `mypy` — run before final merge
- [x] API is backward-compatible (no breaking changes)

## Security Checklist
- [x] No SQL injection — SQLAlchemy ORM throughout
- [x] No XSS — Next.js JSX auto-escapes
- [x] No IDOR — `org_id` enforced via RLS + middleware on every request
- [x] RBAC checked on all protected endpoints
- [x] Rate limiting via nginx (10 req/s burst on `/api/`)
- [x] JWT RS256 with configurable expiry

## Breaking Changes
None — this is the initial integration of all feature branches into develop/main.

## Deployment Notes

### Required DB migration (run once before deploying):
```sql
ALTER TABLE vpn_peers
  ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'assigned';
```

### First-time stack bootstrap:
```bash
# Generate secrets
python scripts/generate_secrets.py

# Start stack
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d

# Run migrations
docker compose exec backend alembic upgrade head

# Create super-admin
docker compose exec backend python scripts/create_admin.py
```

### Environment variables (new in this release):
| Variable | Description | Example |
|----------|-------------|---------|
| `AWG_WG_PATH` | Path to wg-quick binary | `/usr/bin/wg-quick` |
| `AWG_SERVER_PUBKEY` | AmneziaWG server public key | `<base64>` |
| `AWG_SERVER_ENDPOINT` | VPN server host:port | `vpn.example.com:51820` |
| `AWG_IP_POOL_CIDR` | Peer IP pool | `10.8.0.0/24` |
