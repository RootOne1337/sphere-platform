# Deployment Guide

> **Sphere Platform v4.5** — Production Deployment Reference

---

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

> *Note on Enterprise Hardware:* For orchestrating 10,000+ devices, 64 GB RAM provides ample headroom for Redis Pub/Sub queues and PostgreSQL shared buffers. NVMe storage is critical to avoid write-locks during mass task execution. A dedicated GPU (e.g., Nvidia RTX 4000 series or Tesla T4) is highly recommended if hardware-accelerated video transcoding or AI-based screen analysis is planned for the streaming pipeline.

### Required Software

```bash
# Docker Engine 24+ with Compose Plugin V2
docker --version          # >= 24.0
docker compose version    # >= 2.20

# Python 3.11+ (for scripts / local dev)
python --version          # >= 3.11

# (Optional) GitHub CLI for releases
gh --version
```

---

## 2. Environment Configuration

### Quick Setup

```bash
# Generate all secrets automatically
python scripts/generate_secrets.py
# Creates .env.local with secure random values

# Or copy and fill manually
cp .env.example .env.local
$EDITOR .env.local
```

### Required Variables

All variables are documented in [configuration.md](configuration.md).
Minimally required for any environment:

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

Uses `docker-compose.override.yml` which enables:

- Hot-reload for backend and frontend
- Exposed DB and Redis ports for local tooling
- Dev Dockerfiles (no multi-stage build)

```bash
# Start full dev stack
docker compose \
  -f docker-compose.yml \
  -f docker-compose.full.yml \
  -f docker-compose.override.yml \
  up -d --build

# Monitor logs
docker compose logs -f backend frontend

# Stop
docker compose down
```

### Makefile shortcuts

```bash
make up         # start dev stack
make down       # stop dev stack
make logs       # tail all logs
make migrate    # run alembic upgrade head
make test       # run pytest suite
make lint       # ruff + mypy
```

---

## 4. Staging Stack

Staging mirrors production but with debug logging and relaxed rate limits.

```bash
# Pull latest images / rebuild
docker compose -f docker-compose.yml -f docker-compose.full.yml pull
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --build

# Environment: set ENVIRONMENT=staging in .env.local
```

Staging-specific settings in `.env.local`:

```bash
ENVIRONMENT=staging
DEBUG=false
LOG_LEVEL=DEBUG
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
```

---

## 5. Production Stack

### 5.1 Single-Host Production

```bash
# Use production compose file
docker compose \
  -f docker-compose.yml \
  -f docker-compose.full.yml \
  -f docker-compose.production.yml \
  up -d --build

# Production-specific settings
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
DB_POOL_SIZE=30
DB_MAX_OVERFLOW=20
```

`docker-compose.production.yml` differences from dev:

- No exposed DB/Redis ports
- Resource limits (`mem_limit`, `cpus`)
- Restart policy `unless-stopped`
- Read-only root filesystems where possible
- Named volumes for data persistence

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

```bash
# Apply all pending migrations
docker compose exec backend alembic upgrade head

# Check current revision
docker compose exec backend alembic current

# View migration history
docker compose exec backend alembic history --verbose

# Rollback one step
docker compose exec backend alembic downgrade -1

# Rollback to specific revision
docker compose exec backend alembic downgrade 0001
```

### Migration after production deploy

```bash
# Always run migrations BEFORE restarting the application
docker compose exec backend alembic upgrade head

# Then restart backend workers
docker compose restart backend celery-worker
```

### Manual migrations (if needed)

One-time SQL applied in v4.0:

```sql
-- Required for VPN peer status tracking
ALTER TABLE vpn_peers
  ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'assigned';
```

---

## 7. First-Time Bootstrap

After fresh deploy on any environment:

```bash
# 1. Run migrations
docker compose exec backend alembic upgrade head

# 2. Create super admin (interactive)
docker compose exec backend python scripts/create_admin.py
# Prompts for: email, username, password

# 3. Verify health
curl http://localhost/api/v1/health
# Expected: {"status":"ok","checks":{"database":{"status":"ok"},"redis":{"status":"ok"}}}

# 4. Verify VPN health
curl -H "Authorization: Bearer <token>" http://localhost/api/v1/vpn/health

# 5. Open Web UI
open http://localhost
```

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

### Horizontal Scaling — Backend

The FastAPI backend is stateless (all state in PostgreSQL + Redis).
Scale with multiple replicas behind load balancer:

```yaml
# docker-compose.production.yml
services:
  backend:
    deploy:
      replicas: 4
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
```

WebSocket sessions are coordinated via Redis Pub/Sub — no sticky sessions required.

### Horizontal Scaling — Celery Workers

```yaml
services:
  celery-worker:
    deploy:
      replicas: 8
```

```bash
# Or scale at runtime (without recreating)
docker compose up -d --scale celery-worker=8
```

### PostgreSQL Connection Pooling (PgBouncer)

For production with many backend replicas, add PgBouncer:

```yaml
services:
  pgbouncer:
    image: bitnami/pgbouncer:latest
    environment:
      POSTGRESQL_HOST: postgres
      POSTGRESQL_DATABASE: sphereplatform
      PGBOUNCER_POOL_MODE: transaction
      PGBOUNCER_MAX_CLIENT_CONN: 1000
```

---

## 10. Updates & Rolling Deploys

### Standard Update

```bash
# 1. Pull new code
git pull origin main

# 2. Re-build images
docker compose -f docker-compose.yml -f docker-compose.full.yml build --no-cache

# 3. Run migrations (BEFORE app restart)
docker compose exec backend alembic upgrade head

# 4. Restart with zero-downtime (one service at a time)
docker compose up -d --no-deps backend
docker compose up -d --no-deps celery-worker
docker compose up -d --no-deps frontend
```

### Rollback

```bash
# Rollback database
docker compose exec backend alembic downgrade -1

# Rollback to previous image
docker compose down
git checkout <previous-tag>
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d
```

---

## 11. Backup & Recovery

### PostgreSQL Backup

```bash
# Daily backup
docker compose exec postgres pg_dump \
  -U sphere sphereplatform \
  | gzip > "backups/sphereplatform-$(date +%Y%m%d).sql.gz"

# Restore
gunzip < backups/sphereplatform-20260223.sql.gz \
  | docker compose exec -T postgres \
    psql -U sphere sphereplatform
```

### Automated backup with cron

```cron
# /etc/cron.d/sphere-backup
0 2 * * * root /opt/sphere-platform/scripts/backup.sh >> /var/log/sphere-backup.log 2>&1
```

### Redis Backup

Redis uses AOF persistence (`appendonly yes`). Data is preserved across restarts.
For point-in-time recovery:

```bash
# Copy AOF file
docker compose exec redis redis-cli BGREWRITEAOF
cp volumes/redis_data/appendonly.aof backups/redis-$(date +%Y%m%d).aof
```

### Disaster Recovery RTO/RPO Targets

| Metric | Target |
|--------|--------|
| RTO (Recovery Time Objective) | < 30 minutes |
| RPO (Recovery Point Objective) | < 24 hours (with daily backups) / < 1 minute (with streaming replication) |

---

## 12. Health Checks

| Endpoint | Auth | Expected Response |
|----------|------|-------------------|
| `GET /api/v1/health` | None | `{"status":"ok","checks":{...}}` |
| `GET /api/v1/vpn/health` | Bearer token | `{"status":"ok"}` |
| `GET /metrics` | Internal only | Prometheus text format |

Docker compose health checks are defined for all services. Check status:

```bash
docker compose ps
# All services should show: Up (healthy)
```

### Readiness vs Liveness

- **Liveness**: `GET /health` — returns 200 if process is alive
- **Readiness**: `GET /health` with DB + Redis check — returns 200 only if
  all dependencies are reachable (used by load balancer)

---

## 13. Troubleshooting

### Backend won't start

```bash
# Check logs
docker compose logs backend --tail=50

# Common causes:
# - Missing .env.local → python scripts/generate_secrets.py
# - DB not ready → docker compose up postgres -d && sleep 10
# - Migration not run → docker compose exec backend alembic upgrade head
```

### Database connection errors

```bash
# Test connectivity
docker compose exec backend python -c "
from backend.database.engine import create_engine
import asyncio
asyncio.run(create_engine().connect())
print('OK')
"

# Reset connection pool
docker compose restart backend
```

### WebSocket connections failing

```bash
# Check nginx ws upgrade config
grep "upgrade" infrastructure/nginx/nginx.conf

# Check Redis pub/sub
docker compose exec redis redis-cli PUBSUB CHANNELS "*"

# Check backend WS logs
docker compose logs backend | grep "websocket"
```

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

```bash
# Проверить зависшие задачи
docker compose exec postgres psql -U sphere sphereplatform \
  -c "SELECT id, status, device_id, created_at FROM tasks
      WHERE status IN ('queued', 'running', 'assigned')
      ORDER BY created_at;"

# Бэкенд автоматически протухает задачи если устройство оффлайн.
# Для ручной отмены:
docker compose exec postgres psql -U sphere sphereplatform \
  -c "UPDATE tasks SET status='failed' WHERE id='<task_id>';"
```

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

```bash
# Check per-container memory
docker stats --no-stream

# PostgreSQL: check for slow queries
docker compose exec postgres psql -U sphere sphereplatform \
  -c "SELECT pid, now()-query_start AS dur, query FROM pg_stat_activity
      WHERE state='active' ORDER BY dur DESC LIMIT 10;"

# Redis: check memory
docker compose exec redis redis-cli info memory
```
