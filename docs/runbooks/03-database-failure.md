# Runbook 03 — Database Failure & Recovery

**Severity:** P1  
**Maintainer:** Infrastructure Team  
**Last Updated:** 2026-01-01  

---

## Overview

This runbook covers PostgreSQL failure scenarios: service crash, disk corruption,
failed migrations, connection pool exhaustion, and restore from backup.

Always prefer the **least destructive** option first. A misconfigured restore is
worse than a slow database.

---

## Symptoms

### Database down

- Backend returns HTTP 503: `{"detail": "Database connection error"}`
- `docker compose ps postgres` shows `Exit` or `Restarting` state
- Grafana alert: **PostgresDown** fires
- Backend logs: `asyncpg.exceptions.ConnectionDoesNotExistError`

### Connection pool exhausted

- Backend returns HTTP 503 intermittently
- Backend logs: `QueuePool limit of size X overflow Y reached`
- `pg_stat_activity` shows `state='idle in transaction'` stuck queries
- Grafana: **PgActiveConnections** near max_connections value

### Slow queries / locks

- API responses consistently > 2 seconds
- Grafana: **SlowQueryDuration** alert
- `pg_stat_activity` shows `wait_event_type='Lock'`

### Failed migration

- Backend fails to start: `alembic.util.exc.CommandError: Can't locate revision`
- OR backend starts but returns 500 on data-touching endpoints
- `alembic current` shows unexpected revision or `(head)` mismatch

---

## Architecture Reference

```
Database:           PostgreSQL 15
Container:          sphere_postgres
Data volume:        postgres_data (Docker named volume)
WAL archive dir:    /var/lib/postgresql/data/pg_wal/
Backups:            /opt/sphere-backups/postgres/ (cron)
Connection pool:    SQLAlchemy async + asyncpg, pool_size=20, max_overflow=30
Row-Level Security: Enabled on all tenant tables
```

---

## Diagnosis

### Step 1 — Container state

```bash
docker compose ps postgres
docker inspect sphere_postgres --format='{{.State.ExitCode}} {{.State.Status}}'
docker compose logs --tail=100 postgres
```

### Step 2 — Database health (if running)

```bash
# Basic connection test
docker compose exec postgres pg_isready -U sphere_user -d sphere_db

# Active connections breakdown
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT
  state,
  wait_event_type,
  count(*) AS count
FROM pg_stat_activity
GROUP BY state, wait_event_type
ORDER BY count DESC;"

# Long-running queries (> 30s)
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT pid, now() - query_start AS duration, state, wait_event, left(query, 120) AS query
FROM pg_stat_activity
WHERE now() - query_start > interval '30 seconds'
AND state != 'idle'
ORDER BY duration DESC;"

# Table bloat / dead tuples
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT relname, n_dead_tup, n_live_tup
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC LIMIT 10;"
```

### Step 3 — Disk space

```bash
df -h /var/lib/docker/volumes/

# Volume size
docker run --rm -v postgres_data:/data alpine du -sh /data
```

### Step 4 — Check migration state

```bash
docker compose exec backend alembic current
docker compose exec backend alembic history --verbose | head -40
docker compose exec backend alembic heads
```

---

## Remediation

### Scenario A — Container crashed / won't start

```bash
# Attempt graceful restart
docker compose restart postgres
sleep 10
docker compose exec postgres pg_isready -U sphere_user -d sphere_db

# If still failing:
docker compose logs postgres | grep -E "(FATAL|ERROR|PANIC)" | tail -30
```

Common PostgreSQL startup errors:

| Error | Cause | Fix |
|-------|-------|-----|
| `could not write lock file "postmaster.pid"` | Unclean shutdown, pid file stale | `docker compose exec postgres rm /var/lib/postgresql/data/postmaster.pid` |
| `database file appears to be corrupted` | Disk error or forced shutdown | Restore from backup |
| `out of memory` | Container OOM | Increase `mem_limit` in `docker-compose.override.yml` |
| `PANIC: could not locate a valid checkpoint record` | WAL corruption | Restore from backup |

#### Clear stale PID file

```bash
docker compose stop postgres
docker run --rm -v postgres_data:/data alpine rm /data/postmaster.pid
docker compose start postgres
```

### Scenario B — Connection pool exhaustion

#### Immediate: kill idle-in-transaction queries

```bash
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND now() - query_start > interval '5 minutes';"
```

#### Immediate: kill blocked queries

```bash
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT pg_cancel_backend(pid)
FROM pg_stat_activity
WHERE wait_event_type = 'Lock'
  AND now() - query_start > interval '2 minutes';"
```

#### Temporary: restart backend (releases pool)

```bash
docker compose restart backend
```

#### Permanent: reduce pool size for overcrowded deployments

```bash
# In .env or docker-compose.yml environment:
# DB_POOL_SIZE=10            (was 20)
# DB_MAX_OVERFLOW=15         (was 30)

docker compose up -d backend   # apply env change
```

### Scenario C — Slow queries / missing indexes

```bash
# Enable pg_stat_statements for query analysis
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"

# Top 10 slowest queries
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;"

# Run EXPLAIN ANALYZE on suspect query
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM devices WHERE organization_id = '<uuid>';"

# Manual VACUUM + ANALYZE on bloated tables
docker compose exec postgres psql -U sphere_user -d sphere_db -c "
VACUUM ANALYZE devices;"
```

### Scenario D — Failed Alembic migration

#### Case 1: Migration not applied (backend won't start)

```bash
# Check exact migration state
docker compose exec backend alembic current

# Apply all pending migrations
docker compose exec backend alembic upgrade head

# If a specific revision is stuck:
docker compose exec backend alembic stamp <last-good-revision>
docker compose exec backend alembic upgrade head
```

#### Case 2: Migration partially applied (table half-migrated)

```bash
# Open psql and inspect
docker compose exec postgres psql -U sphere_user -d sphere_db

# Check columns current state
\d devices

# Manually complete or rollback:
# Option A: complete the migration manually
ALTER TABLE devices ADD COLUMN IF NOT EXISTS vpn_ip INET;

# Option B: rollback the migration
docker compose exec backend alembic downgrade -1
# (Fix the migration file, then:)
docker compose exec backend alembic upgrade head
```

#### Case 3: Downgrade a migration in production

```bash
# DANGER: always back up first
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker compose exec postgres pg_dump -U sphere_user sphere_db \
  | gzip > /opt/sphere-backups/postgres/pre-downgrade-$TIMESTAMP.sql.gz

# Downgrade one step
docker compose exec backend alembic downgrade -1

# Or to a specific revision
docker compose exec backend alembic downgrade <revision_id>
```

---

## Backup & Restore

### Create manual backup

```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p /opt/sphere-backups/postgres

docker compose exec postgres pg_dump \
  -U sphere_user \
  -d sphere_db \
  --format=custom \
  --compress=9 \
  > /opt/sphere-backups/postgres/sphere_db_$TIMESTAMP.dump

echo "Backup size: $(du -sh /opt/sphere-backups/postgres/sphere_db_$TIMESTAMP.dump)"
```

### Full restore from backup

> **WARNING:** This restores all data to the backup point.  
> Run this **only** on a stopped or isolated instance.  
> Stop backend before restoring to prevent write conflicts.

```bash
# 1. Stop application services (not postgres)
docker compose stop backend celery_worker celery_beat

# 2. Pick backup file
BACKUP_FILE="/opt/sphere-backups/postgres/sphere_db_20260101_120000.dump"

# 3. Drop and recreate database
docker compose exec postgres psql -U sphere_user -d postgres -c "DROP DATABASE sphere_db;"
docker compose exec postgres psql -U sphere_user -d postgres -c "CREATE DATABASE sphere_db;"

# 4. Restore
docker compose exec postgres pg_restore \
  -U sphere_user \
  -d sphere_db \
  --no-privileges \
  --no-owner \
  < $BACKUP_FILE

# 5. Re-enable RLS policies (if not stored in dump)
docker compose exec backend alembic upgrade head

# 6. Restart application services
docker compose start backend celery_worker celery_beat

# 7. Verify
curl -f http://localhost:8000/health && echo "RECOVERED"
```

### Partial restore (specific tables)

```bash
docker compose exec postgres pg_restore \
  -U sphere_user \
  -d sphere_db \
  --table=audit_logs \
  < $BACKUP_FILE
```

---

## Backup Verification Schedule

Perform restore-verification drill monthly:

```bash
# Restore to a separate test container
docker run -d --name pg_test \
  -e POSTGRES_USER=sphere_user \
  -e POSTGRES_PASSWORD=testpw \
  -e POSTGRES_DB=sphere_test \
  postgres:15-alpine

docker exec -i pg_test pg_restore \
  -U sphere_user \
  -d sphere_test \
  < /opt/sphere-backups/postgres/latest.dump

# Verify row counts
docker exec pg_test psql -U sphere_user -d sphere_test \
  -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 10;"

docker rm -f pg_test
```

---

## RTO / RPO Targets

| Metric | Target |
|--------|--------|
| RPO (Recovery Point Objective) | 1 hour (automated hourly backups) |
| RTO (Recovery Time Objective) | 30 minutes for restore from latest backup |

---

## Post-Incident

1. Record exact failure time and duration in the incident channel.
2. Identify row/data loss (if any). Notify affected customers.
3. Verify backup integrity immediately after recovery.
4. Fix the root cause before re-enabling automated backups if they were paused.
5. Schedule a backup drill if restore was not tested recently.
6. File a GitHub Issue with label `incident-db-followup` for any schema or reliability improvements.

---

## Related Runbooks

- [01-backend-outage.md](01-backend-outage.md) — Backend outage triggered by DB problems
- [04-fleet-offline.md](04-fleet-offline.md) — Device reconnection after DB recovery
