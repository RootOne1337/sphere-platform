# Deployment Guide

> **Статус на 11 сентября 2026:** аудит продолжается; этот справочник не является
> подтверждением production readiness. RLS runtime-role rollout заблокирован до
> проверки остальных auth callers, фоновых задач и provisioning ролей: [условия и доказательства](security/postgresql-rls.md).
> Текущий общий PostgreSQL owner/superuser не пройдёт production startup guard.
> Не применять generic rolling deploy/rollback к этим security migrations.

---

> Migration `20260909_user_auth_bootstrap` требует explicit runtime EXECUTE grants
> на две user функции в дополнение к двум device-функциям:
> [user auth и MFA cutover](security/user-auth-bootstrap.md),
> [device credential runbook](security/device-credential-bootstrap.md).
> Revision `20260910_device_refresh_retry` сохраняет существующие grants
> и добавляет recoverable device rotation. [Rollout/rollback](security/device-refresh-recovery.md):
> migration → все backend workers → APK. Полный runtime-role rollout этим не завершается.
> Определяйте актуальные migration heads в выбранном checkout через
> `alembic -c alembic/alembic.ini heads`.

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Configuration](#2-environment-configuration)
3. [Development Stack](#3-development-stack)
4. [Staging Stack](#4-staging-stack)
5. [Production Stack](#5-production-stack)
6. [Database Migrations](#6-database-migrations)
7. [First-Time Bootstrap](#7-first-time-bootstrap)
8. [SSL / TLS](#8-ssl--tls)
9. [Scaling](#9-scaling)
10. [Updates & Rolling Deploys](#10-updates--rolling-deploys)
11. [Backup & Recovery](#11-backup--recovery)
12. [Health Checks](#12-health-checks)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Prerequisites

### Minimum Requirements

| Environment | CPU | RAM | Disk | OS |
|-------------|-----|-----|------|----|
| Development | 2 cores | 4 GB | 20 GB | Any Docker-capable |
| Staging | 4 cores | 8 GB | 50 GB | Ubuntu 22.04 LTS |
| Production | 8 cores | 16 GB | 100 GB SSD | Ubuntu 22.04 LTS |
| **Enterprise (10k+ Devices)** | **16 Cores / 32 Threads** | **64 GB** | **2 TB NVMe** | **Ubuntu 22.04 LTS** |

> Эти конфигурации — прежние ориентиры, а не измеренная ёмкость. Работа 10–64 эмуляторов, 10 000 устройств, CPU/RAM/FPS и запас производительности не подтверждены текущими тестами. NVMe сам по себе не устраняет блокировки PostgreSQL.

### Required Software

```bash
# Docker Engine 24+ with Compose Plugin 2.24.4+ (supports !reset overrides)
docker --version          # >= 24.0
docker compose version    # >= 2.24.4

# Python 3.12 for the documented startup/development workflow
python --version          # 3.12

# (Optional) GitHub CLI for releases
gh --version
```

---

## 2. Environment Configuration

### Quick Setup

Use [Startup](operations/STARTUP.md#first-install) for a new isolated installation.
Without `--output`, `scripts/generate_secrets.py` prints secrets to stdout; with
`--output` it overwrites the selected file. Do not run it against an existing
configuration or publish its output. Generating a file does not rotate passwords
or update a running database or container.

### Required Variables

All variables are documented in [configuration.md](configuration.md).
Development/bootstrap example only; this shared PostgreSQL role is not safe for production runtime. See the [RLS rollout blockers](security/postgresql-rls.md) before separating migration/runtime credentials:

```bash
POSTGRES_USER=sphere
POSTGRES_PASSWORD=<32+ chars random>
POSTGRES_URL=postgresql+asyncpg://sphere:<pass>@postgres:5432/sphereplatform

REDIS_PASSWORD=<32+ chars random>
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0

JWT_SECRET_KEY=<64+ chars random>

WG_SERVER_PUBLIC_KEY=<base64 WireGuard public key>
WG_SERVER_ENDPOINT=vpn.yourdomain.com:51820
VPN_KEY_ENCRYPTION_KEY=<Fernet.generate_key() output>
```

---

## 3. Development Stack

The maintained first-install path is [Startup](operations/STARTUP.md#first-install).
It selects base plus full for development, with explicit configuration, migrations,
bootstrap and readiness. The separate `docker-compose.override.yml` is a dev-only
overlay; do not assume it is part of a separately selected file combination. Always
use the same project, env file and Compose files when inspecting an installation.

### Makefile shortcuts

```bash
make dev        # start infrastructure, not the full application stack
make full       # start base + full application stack
make down       # stop dev stack
make logs       # tail all logs
make migrate    # run alembic upgrade head
make test       # run pytest suite
make lint       # ruff + mypy
```

---

## 4. Staging Stack

There is no independent staging Compose file in this repository. Define an
isolated project, configuration, images, roles, ingress and validation for the
intended staging environment; setting `ENVIRONMENT=staging` alone does not make
the development full overlay equivalent to production. See
[configuration](configuration.md) and [Startup](operations/STARTUP.md).

---

## 5. Production Stack

### 5.1 Single-Host Production

The production launcher uses base plus `docker-compose.production.yml`; the
production override can also be applied last after the full overlay. Select and
review the env file before deployment, provision the migration/runtime roles,
and follow [Startup](operations/STARTUP.md) for the ordered bootstrap. Compose
file validity alone is not authorization or acceptance to start a production stack.

`docker-compose.production.yml` differences from dev:

- No published PostgreSQL/Redis or application ports; nginx reaches the applications on their Docker network
- Resource limits under `deploy.resources.limits`
- Restart policy `always` for the production overrides
- Image-defined application command and user, without development source/cache mounts
- Named volumes for data persistence

Keep the production override last. It uses Compose `!reset` to clear inherited
ports, source mounts, development commands and root-user overrides, including
when an existing script still includes `docker-compose.full.yml` before it.
See the [official Compose merge rules](https://docs.docker.com/reference/compose-file/merge/).
`tests/deployment/test_compose_production.py` validates both file combinations by
running `docker compose config` with synthetic values; it does not start services.

This configuration check is not a deployment sign-off. n8n and MinIO still inherit
their base host-port mappings and require an explicit ingress/access design.
The image root filesystem is not declared read-only here. Runtime database roles,
durable OTA/log storage and backup restore verification remain open audit items.
Do not rely on the removed development bind mounts for production persistence.

### 5.2 Pre-flight Checklist

Before deploying to production:

- [ ] All secrets are unique and > 32 characters
- [ ] `JWT_SECRET_KEY` is unique per environment
- [ ] `VPN_KEY_ENCRYPTION_KEY` is stored in a secrets manager (not just .env)
- [ ] SSL certificates are valid and auto-renewing
- [ ] Database backups are configured and tested
- [ ] Firewall rules: only ports 80, 443 exposed
- [ ] Rate limiting tuned for expected traffic
- [ ] Grafana alerting recipients configured
- [ ] `SENTRY_DSN` set if using Sentry

### 5.3 Firewall Rules (UFW example)

```bash
ufw default deny incoming
ufw allow 22/tcp    # SSH (restrict to known IPs)
ufw allow 80/tcp    # HTTP (nginx → HTTPS redirect)
ufw allow 443/tcp   # HTTPS
ufw allow 51820/udp # WireGuard VPN
ufw enable
```

---

## 6. Database Migrations

Alembic is used for all schema changes.

The audit migration `20260906_vpn_intents` requires a controlled VPN writer
maintenance window, not a mixed-version rolling deployment. Reconcile held
PostgreSQL addresses with actual router inventory, including orphan peers absent
from SQL, and stop legacy allocation writers before applying it. Duplicate held
addresses, invalid addresses or network prefixes make this migration fail
atomically; it does not delete or renumber peers. Downgrade is refused while
PROVISIONING/REVOKING intents exist. See the
[VPN runbook](runbooks/02-vpn-incident.md) and
[transaction/rollout design](audits/2026-09-05/VPN-LEASE-DESIGN.md).

The next revision, `20260906_account_ciphertext`, adds encrypted account storage.
Provision the independent `ACCOUNT_CREDENTIAL_KEYS` key ring, stop account and
dispatch/orchestrator writers, and run the explicit backfill/verification from
[the credential runbook](security/account-credentials.md). Applying Alembic alone
does not encrypt legacy rows; credential reveal and dispatch fail closed until
they are migrated. The maintenance CLI ships in the backend image as
`python -m backend.cli.account_credentials`. Downgrade refuses encrypted rows.
Do not use the generic rolling-deploy/rollback examples below for this transition.

From the repository root, use the repository's explicit Alembic configuration:
`python -m alembic -c alembic/alembic.ini upgrade head`. In a container use the
equivalent path for its working directory and the selected Compose stack.

For example, from a prepared repository environment:

```bash
python -m alembic -c alembic/alembic.ini heads
```

Run `current`, `history` or `upgrade` with the same explicit configuration only
after selecting the correct database, credentials and maintenance procedure.
Security revision `20260908_tenant_policies` blocks downgrade; use a reviewed
forward migration or recovery plan.

### Migration and application rollout

Select the correct Compose project, env file and image. Use the explicit Alembic
configuration and an authorized migration role; the [startup procedure](operations/STARTUP.md)
describes one-off migration and bootstrap ordering. Read each revision's rollout and
rollback constraints before changing a live environment. The Compose stacks in this
repository do not define a `celery-worker` service. A restart is not proof that the
new image, schema and external effects are compatible.

### Manual migrations (if needed)

Do not apply an old standalone `ALTER TABLE` in place of the selected revision's
Alembic migration. Investigate a failed migration with the database runbook and
reviewed migration-specific recovery plan.

---

## 7. First-Time Bootstrap

For the first development pilot, use the [acceptance plan](operations/PILOT-ACCEPTANCE.md).
This sequence assumes prepared database bootstrap credentials and selected Compose
files/environment. Production runtime credentials must remain separate from the
migration/bootstrap role; the snippets do not replace that rollout.

1. Apply the reviewed migrations using `python -m alembic -c alembic/alembic.ini upgrade head`
   with the bootstrap connection, before starting ordinary application work.
2. Run `python scripts/create_admin.py --create-only` in the prepared backend environment.
   Interactive mode prompts for email/password. For unattended mode supply
   `ADMIN_EMAIL`/`ADMIN_PASSWORD`; with a one-off Compose run forward them using
   `-e ADMIN_EMAIL -e ADMIN_PASSWORD`, not only host `SPHERE_ADMIN_*` variables.
3. Run `python -m scripts.seed_enrollment_key`. Both scripts use
   `SPHERE_BOOTSTRAP_ORG_SLUG` (default `default`). The organization must already
   exist and the effective agent-config environment must contain the intended key.
   Existing conflicting/revoked/expired keys are errors, not silently repaired.
4. Check `/api/v1/health/readyz`, then actual login, device registration and device
   visibility. `/api/v1/health` is a static liveness response. `/vpn/health` is also
   static and cannot establish that a VPN tunnel works.
5. Complete the browser → APK → task/result and actual VPN acceptance scenarios.

AUD-78 repairs the bootstrap functions in both full-deploy launchers. It does not
validate their complete env-file selection, migration ordering, final health,
autostart or production role setup. AUD-85 makes both launchers preserve existing
admin credentials with `--create-only`. Direct CLI without that flag intentionally
updates password/role/active. A different organization is rejected; old users/devices
are not automatically moved. [Current admin outcome contract](operations/STARTUP.md).

---

## 8. SSL / TLS

### Option A: nginx with Let's Encrypt (Certbot)

```bash
# Install certbot
apt install certbot python3-certbot-nginx

# Obtain certificate
certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Auto-renewal (verify with dry run)
certbot renew --dry-run
```

Update `infrastructure/nginx/nginx.conf`:

```nginx
server {
    listen 443 ssl http2;
    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_session_cache   shared:SSL:10m;
    add_header Strict-Transport-Security "max-age=63072000" always;
}
```

### Option B: Traefik with ACME

See `infrastructure/traefik/` for the Traefik-based alternative with automatic
Let's Encrypt via ACME HTTP challenge.

---

## 9. Scaling

The checked-in Compose configuration does not establish an accepted replica count,
no-sticky-session guarantee or production scaling recipe. WebSocket ownership,
background work, connection pools, Redis, ingress and device behavior need to be
verified together under the intended topology and workload. Increasing worker or
replica counts also increases database connection demand. There is no
`celery-worker` service in the base, full or production Compose files. PgBouncer
is not included in those stacks; its use and transaction-pooling compatibility
require separate configuration and validation.

---

## 10. Updates & Rolling Deploys

### Controlled update

Identify the deployed versions, selected Compose project and data stores first.
Review migrations and compatibility between the old and new API, agents and
schema; plan the required maintenance window, recovery and acceptance. Use the
specific installation's procedure, [Startup](operations/STARTUP.md), and
[Local pilot](operations/LOCAL-PILOT.md) where applicable. A single-container
Compose recreation can interrupt service; no zero-downtime guarantee follows from
starting services one at a time. Verify actual image identity and readiness, then
perform scoped user/device checks with known outcomes.

### Rollback

Automatic schema/image rollback is not supported across the current security
transitions. Tenant policy downgrade is explicitly blocked; encrypted credentials
and pending VPN intents also have guards. Prepare a reviewed forward repair or a
verified isolated restore with matching application version, keys and role policy.
Do not disable RLS/startup checks to make an older image start.

---

## 11. Backup & Recovery

### Backup and isolated restore

The repository does not establish that backups, an automated schedule, WAL
archiving, or a recovery-time objective are configured for a particular install.
Base Compose enables Redis AOF and uses a named volume; it does not establish that
a host path named `volumes/redis_data/appendonly.aof` exists or is a consistent
backup. Persistence across a restart is not disaster recovery. The legacy cron
example referred to a non-existent `scripts/backup.sh`.

Choose a backup procedure for the actual project and its PostgreSQL/Redis versions,
volumes and credentials. Include application data, required encryption keys,
roles/grants, OTA artifacts and device logs according to the installation's
retention and recovery requirements. Validate backup integrity and perform a
restore drill in a separate database and volume, never over the active installation.
Reconcile schema, representative task receipts and external effects before any
cutover. [Database recovery runbook](runbooks/03-database-failure.md) describes the
checks. Measure and approve RTO/RPO from a real drill; no specific value is
established by this repository.

---

## 11.5 Background Tasks (v4.7)

The backend runs several asyncio background tasks that start automatically:

| Task | Module | Interval | Description |
|------|--------|----------|-------------|
| Orchestration Loop | `backend/tasks/orchestration_loop.py` | `ORCHESTRATION_LOOP_INTERVAL` (10s) | Periodic orchestration tick — checks pending pipelines |
| Task Heartbeat Watchdog | `backend/tasks/task_heartbeat_watchdog.py` | `TASK_HEARTBEAT_CHECK_INTERVAL` (30s) | Marks stale tasks as failed after `TASK_HEARTBEAT_TIMEOUT` |
| Event Reactor | `backend/services/event_reactor.py` | On-demand | Processes device events and fires matching triggers |

These tasks are registered in `backend/main.py` startup lifecycle.

---

## 12. Health Checks

| Endpoint | Auth | Expected Response |
|----------|------|-------------------|
| `GET /api/v1/health/healthz` | Liveness | Process response; does not check dependencies |
| `GET /api/v1/health/readyz` | Readiness | Checks PostgreSQL and Redis; `{"status":"ready"}` on success |
| `GET /api/v1/health` | Static liveness | Does not prove dependencies or device operation |
| `GET /api/v1/vpn/health` | Static VPN response | Does not prove a working tunnel |

Inspect `ps --all` for the selected Compose project and check configured health
probes for each service. Not every service necessarily has a health check, and a
healthy container does not prove the user/device scenario.

### Readiness vs Liveness

- **Liveness**: `GET /api/v1/health/healthz` indicates a responding process.
- **Readiness**: `GET /api/v1/health/readyz` checks PostgreSQL and Redis. It does
  not establish successful device commands, video, VPN or the whole fleet.

---

## 13. Troubleshooting

### Backend won't start

Use the selected project's bounded backend logs, inspect the specific failure,
and follow the [backend outage runbook](runbooks/01-backend-outage.md). Do not
generate new secrets, restart services or apply migrations blindly when an
existing configuration, data store or unknown task outcomes may be present.

### Database connection errors

See [PostgreSQL failure](runbooks/03-database-failure.md) for diagnosis using the
selected database and role. `backend.database.engine` exposes the configured
`engine`, not a `create_engine` factory. A restart can interrupt work and should
follow an identified cause and an appropriate recovery decision.

### WebSocket connections failing

```bash
# Check nginx ws upgrade config
grep "upgrade" infrastructure/nginx/nginx.conf

# Check backend WS logs
docker compose logs backend | grep "websocket"
```

Select the intended Compose files and project for these examples; Redis inspection
also requires that installation's authentication. See the
[backend outage runbook](runbooks/01-backend-outage.md).

### Tunnel Setup (Serveo SSH)

Serveo используется как SSH tunnel для проброса HTTPS/WSS трафика без
статического IP-адреса. Заменяет Cloudflare Quick Tunnel, который дропал
idle WebSocket через 5-50 секунд.

```bash
# 1. Сгенерировать SSH-ключ
mkdir -p infrastructure/tunnel/keys
ssh-keygen -t ed25519 -f infrastructure/tunnel/keys/id_ed25519 -N ""

# 2. Зарегистрировать ключ для кастомного субдомена
# Перейти на https://console.serveo.net → Add SSH Key → ваш публичный ключ

# 3. Запустить tunnel
docker compose -f docker-compose.tunnel.yml up -d

# 4. Проверить
curl https://sphere.serveousercontent.com/api/v1/health
# → {"status":"ok","version":"4.5.0"}
```

**Переменные окружения (.env):**

```bash
SERVER_PUBLIC_URL=https://sphere.serveousercontent.com
CORS_EXTRA_ORIGINS=https://sphere.serveousercontent.com
```

**Agent config (sphere-agent-config repo):**

```json
{ "server_url": "https://sphere.serveousercontent.com" }
```

### H264 стрим не работает (чёрный экран)

```bash
# Проверить что SPS/PPS/IDR кэш заполнен
docker compose logs backend | grep "sps_pps_cached\|idr_cached"

# Проверить viewer ping
docker compose logs backend | grep "viewer.*ping"

# Проверить keepalive noop от агента
docker compose logs backend | grep "noop\|keepalive"
```

### Задачи (Tasks) возвращают 409 Conflict

Сопоставьте task/device identity, состояние, журналы и подтверждения отмены или
завершения в правильной организации. Используйте предусмотренный приложением
путь управления с учётом прав и протокола; timeout или потеря ответа сами по себе
не подтверждают остановку действия на устройстве. Не меняйте статус задачи прямым
`UPDATE`: это обходит доставку команды и может скрыть неизвестный исход.
[Контракт управления задачами](security/task-control-protocol.md).

### VPN peer can't connect

```bash
# Check peer config exists
curl -H "Authorization: Bearer <token>" \
     http://localhost/api/v1/vpn/peers

# Check WireGuard interface on server
wg show sphere0

# Check client config was delivered
# Look for vpn.connect event in backend logs
docker compose logs backend | grep "vpn"
```

### High memory usage

The source Compose Redis budget is 512 MiB dataset / 3072 MiB container; the
configured source limit is not proof of the limit of an already running instance.
Capacity and rollout acceptance depend on the actual workload and installation.
Compare Redis RSS and the Docker ceiling as well as `used_memory`; persistence
forks and buffers are not covered by the dataset number alone. See the
[measured memory contract and rollout](operations/REDIS-MEMORY.md).

```bash
# Check per-container memory
docker stats --no-stream

# PostgreSQL: check for slow queries
docker compose exec postgres psql -U sphere sphereplatform \
  -c "SELECT pid, now()-query_start AS dur, query FROM pg_stat_activity
      WHERE state='active' ORDER BY dur DESC LIMIT 10;"

# Redis: check memory
docker compose exec redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli INFO memory'
```

### Windows configuration selection (AUD-80)

The full-deploy Compose wrapper and normal start-dev config/build/up path explicitly
select checkout `.env.local`, then `.env`, matching Makefile priority. Files are not
merged. Process environment overrides retain Compose precedence. Full-deploy refuses
to invoke Compose without either file; start-dev creates a template only when both
are missing and requires the operator to fill it before retry. The real Compose
renderer is tested with synthetic files, without starting services. This does not
certify full startup, legacy branches or deployment roles/migrations.

### Immutable image bootstrap tools (AUD-81)

The production backend image ships the two administrative CLIs used by full-deploy:
`scripts/create_admin.py` and `scripts/seed_enrollment_key.py`. A separate backend CI
job builds that Dockerfile and executes four CLI/migration/user probes without
network, source mounts or a writable root filesystem. The probe validates packaged
entry points; SQL initialization, migration privileges and rollout order still
require their own acceptance. Unrelated scripts are not included.

### Full-deploy phase contract (AUD-82)

Both full-deploy launchers now build, wait for PostgreSQL/Redis (180 s), execute
migration/admin/enrollment with `compose run --rm --no-deps -T backend`, then start
the full stack with `up --wait --wait-timeout 300`. A phase failure stops later work;
host Alembic fallback is removed. The production overlay includes internal backend
readyz/frontend login probes, so readiness does not depend on host port publication.
The final output reports selected-project Compose status, not universal readiness.
These limits exclude image build/pull and do not validate ingress/TLS, device/tasks
or services without probes. Existing workers are not stopped: incompatible upgrades
still require a coordinated rollout and explicit runtime/migration roles/grants.

### Enrollment identity during development startup

AUD-83 makes the dev hook use the same configured key, exact bootstrap org and SQL
serialization as the explicit CLI. Both Compose overlays forward
`SPHERE_BOOTSTRAP_ORG_SLUG`; persist it in the installation env file. Known key or
configuration conflicts are warnings in the hook and errors in the explicit CLI.
Check actual device registration after API readiness. [Diagnostic events and limits](operations/STARTUP.md).

### Preserve existing installation configuration

AUD-84 prevents full-deploy from generating a higher-priority `.env.local` when
the installation already uses `.env`. Existing files are retained on unattended
startup; fresh generation still works. This does not rotate database credentials
or validate persistent-volume recovery. See [repeat-startup contract](operations/STARTUP.md).

### Packaged SQL bootstrap acceptance

The production Dockerfile is now exercised against disposable PostgreSQL/Redis,
with fresh migrations, both real bootstrap CLIs, full application lifespan and ASGI
login/device visibility across two processes. This development-mode scenario uses
an internal Docker network, no host ports and no source mounts. It complements the
four no-network image probes. [Run it and read the limits](../tests/containers/README.md).
Full Compose, browser/APK, VPN and production DB-role rollout remain separate gates.

### Fresh configuration parsing

AUD-86 fixes a startup failure in the full overlay: missing/empty `DEV_SKIP_AUTH`
now renders to `false`, preserving the backend's strict boolean validation and
production's forced false. The real generator → Compose → Settings path is retained
as eight regression cases; all 93 deployment cases pass locally. This is separate
from daemon startup and installed-APK acceptance.

### PostgreSQL init.sql with a configured user

AUD-87 removes hardcoded n8n ownership from init.sql; a fresh cluster assigns the
database to the entrypoint's POSTGRES_USER. Two real PostgreSQL container cases
verify default/custom users, n8n ownership, required extensions and a restart with
retained data. [Probe and cleanup](../tests/containers/README.md). No existing volume
is changed. Partially initialized installations need inspection/repair separately;
init.sql is not an application migration or production role-provisioning mechanism.
