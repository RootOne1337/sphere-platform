# Runbook 01 — Backend API Outage

**Severity:** P1  
**Maintainer:** Backend Team  
**Last Updated:** 2026-01-01  

---

## Overview

This runbook covers scenarios where the Sphere backend API becomes unresponsive,
crashes, or returns 5xx errors to clients and the Android/PC agents.

---

## Symptoms

- Web UI shows "Unable to connect" or perpetual loading state
- Android agents fail to establish WebSocket connection
- Healthcheck probe returns non-200: `curl -f http://localhost:8000/health`
- Grafana alert: **BackendDown** or **HighErrorRate** fires
- `docker compose ps` shows backend container in `Exit` or `Restarting` state

---

## Diagnosis

### Step 1 — Check container state

```bash
docker compose ps backend celery_worker
```

Expected: `Up (healthy)`. If `Exit` or `Restarting`, check exit code:

```bash
docker inspect sphere_backend --format='{{.State.ExitCode}} {{.State.Error}}'
```

| Exit Code | Meaning |
|-----------|---------|
| 0 | Clean shutdown (should not happen in production) |
| 1 | Application error (import error, config error) |
| 137 | OOM kill — processes exceeded memory limit |
| 143 | SIGTERM — systemd/Docker forced shutdown |

### Step 2 — Read logs

```bash
# Last 100 lines
docker compose logs --tail=100 backend

# Filter for errors only (JSON logs)
docker compose logs --no-log-prefix backend | jq 'select(.level == "error" or .level == "critical")'

# Look for startup crash
docker compose logs backend 2>&1 | grep -E "(ERROR|CRITICAL|Traceback|ImportError)"
```

### Step 3 — Check database connectivity

```bash
# Backend can reach Postgres?
docker compose exec backend python -c "
import asyncio, sqlalchemy
from backend.database.session import async_engine
async def test():
    async with async_engine.connect() as conn:
        result = await conn.execute(sqlalchemy.text('SELECT 1'))
        print('DB OK:', result.scalar())
asyncio.run(test())
"
```

### Step 4 — Check Redis connectivity

```bash
docker compose exec backend python -c "
import redis
r = redis.from_url('redis://redis:6379/0')
print('Redis ping:', r.ping())
"
```

### Step 5 — Check for OOM

```bash
# System-level OOM
dmesg | grep -i "oom" | tail -20
journalctl -k | grep -i "killed process" | tail -20

# Container memory usage
docker stats --no-stream sphere_backend
```

### Step 6 — Check disk space

```bash
df -h /
docker system df
```

---

## Remediation

### Scenario A — Container crashed (OOM or exception)

```bash
# Restart container
docker compose restart backend

# Wait for health check
watch -n2 'docker compose ps backend'

# Verify endpoint
curl -f http://localhost:8000/health && echo "RECOVERED"
```

If it crashes again within 5 minutes → proceed to Scenario B.

### Scenario B — Application startup failure (bad config or migration)

```bash
# Check if migration is needed
docker compose exec backend alembic current
docker compose exec backend alembic heads

# Run pending migrations
docker compose exec backend alembic upgrade head

# Restart
docker compose restart backend
```

If migration fails, do not force it. Check migration output for:
- `relation does not exist` → database restore needed (Runbook 03)
- `column already exists` → migration was partially applied, see [Runbook 03](03-database-failure.md#partial-migration-recovery)

### Scenario C — OOM kill (memory exhaustion)

1. Check which process consumed memory:

```bash
docker compose logs --tail=50 backend | jq '.message' | grep -i "memory"
```

2. Increase memory limit (temporary):

```yaml
# docker-compose.override.yml
services:
  backend:
    mem_limit: 2g        # was 512m or 1g
    memswap_limit: 2g
```

```bash
docker compose up -d backend
```

3. Investigate root cause after stabilization:
   - Celery task memory leak
   - Unbounded query result sets
   - Large file upload held in memory

### Scenario D — Disk full

```bash
# Free space immediately
docker system prune -f              # remove stopped containers and dangling images
docker volume prune -f              # WARNING: removes unused volumes (not db/redis)

# Check Postgres WAL logs
docker compose exec postgres du -sh /var/lib/postgresql/data/pg_wal
# If >1GB, check for stuck replication slots
docker compose exec postgres psql -U sphere_user -d sphere_db \
  -c "SELECT slot_name, active, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS lag FROM pg_replication_slots;"
# Drop idle slots if no replica in use
# docker compose exec postgres psql -U sphere_user -d sphere_db \
#   -c "SELECT pg_drop_replication_slot('slot_name');"
```

### Scenario E — High CPU / slow responses (not down, but degraded)

```bash
# Which endpoints are slowest?
docker compose logs --no-log-prefix backend | jq 'select(.duration_ms > 2000)' | tail -30

# Check slow queries
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;"

# Check active DB connections
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
```

---

## Rollback Procedure

If a recent deployment caused the outage:

```bash
# Identify previous image tag
docker images sphere_backend --format "{{.Tag}} {{.CreatedAt}}" | head -10

# Roll back to previous image
docker compose stop backend
docker tag sphere_backend:previous sphere_backend:current   # adjust tags
docker compose up -d backend
```

Or, using Git to identify the last known-good commit and rebuild:

```bash
git log --oneline -10
git checkout <last-good-sha> -- backend/
docker compose build backend
docker compose up -d backend
```

---

## Post-Incident

### Immediate (within 2 hours)

1. Confirm all services healthy: `docker compose ps`
2. Confirm metrics returning to normal in Grafana
3. Post incident summary in `#inc-*` channel

### Within 24 hours

1. Write a brief Post-Mortem:
   - Timeline
   - Root cause
   - Impact (users affected, duration)
   - Remediation
   - Follow-up action items

2. Create GitHub Issues for any action items with label `incident-followup`

3. Update this runbook if new failure modes were discovered

---

## Related Runbooks

- [03-database-failure.md](03-database-failure.md) — If root cause is DB
- [04-fleet-offline.md](04-fleet-offline.md) — Subsequent device reconnection
