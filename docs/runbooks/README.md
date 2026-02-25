# Operational Runbooks — Index

This directory contains step-by-step operational runbooks for common incident scenarios.
Each runbook follows the same structure: **Symptoms → Diagnosis → Remediation → Post-Incident**.

---

## Available Runbooks

| # | Title | Last Updated | Severity |
|---|-------|-------------|----------|
| [01](01-backend-outage.md) | Backend API Outage | 2026-01-01 | P1 |
| [02](02-vpn-incident.md) | VPN Tunnel Failure / Pool Exhaustion | 2026-01-01 | P1 |
| [03](03-database-failure.md) | Database Failure & Recovery | 2026-01-01 | P1 |
| [04](04-fleet-offline.md) | Mass Device Disconnect (Fleet Offline) | 2026-01-01 | P2 |

---

## Runbook Usage Guide

### Getting oriented

All production services run under Docker Compose. Replace `DEPLOY_DIR` with your deployment path:

```bash
export DEPLOY_DIR=/opt/sphere-platform
cd $DEPLOY_DIR
```

### Quick health summary

```bash
docker compose ps           # container states
docker compose logs --tail=50 backend
docker compose logs --tail=50 nginx
curl -f http://localhost:8000/health || echo "backend down"
curl -f http://localhost/health/live || echo "nginx probe failed"
```

### Metric dashboards

| Dashboard | URL |
|-----------|-----|
| Grafana | `http://<host>:3000` (admin / see `.env`) |
| API metrics (raw) | `http://localhost:8000/metrics` |
| Prometheus | `http://localhost:9090` |

### Alertmanager silences

```bash
# Mute an alert for 4 hours while working an incident
curl -s -X POST http://localhost:9093/api/v2/silences \
  -H "Content-Type: application/json" \
  -d '{
    "matchers": [{"name": "alertname", "value": "BackendDown", "isRegex": false}],
    "startsAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "endsAt":   "'$(date -u -d '+4 hours' +%Y-%m-%dT%H:%M:%SZ)'",
    "createdBy": "oncall",
    "comment":   "Working incident INC-XXX"
  }'
```

---

## Severity / Priority Matrix

| Priority | Response SLA | Description |
|----------|-------------|-------------|
| P1 | 15 minutes | Production totally down; users cannot log in or devices unreachable |
| P2 | 1 hour | Degraded service; some features unavailable |
| P3 | Next business day | Partial outage; workaround available |
| P4 | Next sprint | Low-impact issue; no user facing degradation |

---

## Escalation Path

```
On-call engineer
   └─ If not resolved in 30 min → Lead engineer
         └─ If not resolved in 60 min → Engineering manager
               └─ Customer comms if external users affected
```

### Incident channel

Open a channel `#inc-YYYYMMDDhhmmss` in Slack (or equivalent) for P1/P2 and
post the Grafana alert screenshot, current status, and your remediation steps.

---

## Common Commands Reference

### Container management

```bash
docker compose restart backend
docker compose restart celery_worker
docker compose pull backend && docker compose up -d backend
docker compose exec backend /bin/bash
```

### Database access

```bash
# Open psql CLI
docker compose exec postgres psql -U sphere_user -d sphere_db

# Tail live queries
docker compose exec postgres psql -U sphere_user -d sphere_db \
  -c "SELECT pid, state, wait_event, query FROM pg_stat_activity WHERE state != 'idle';"
```

### Redis CLI

```bash
docker compose exec redis redis-cli
127.0.0.1:6379> INFO stats
127.0.0.1:6379> CLIENT LIST
127.0.0.1:6379> MONITOR    # live command stream (dev only, high overhead)
```

### Logs

```bash
# Structured JSON log search (requires jq)
docker compose logs backend --no-log-prefix | jq 'select(.level == "error")'
docker compose logs backend --no-log-prefix | jq 'select(.event | contains("VPN"))'
```
