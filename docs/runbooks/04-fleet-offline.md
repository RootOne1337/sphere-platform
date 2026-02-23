# Runbook 04 — Mass Device Disconnect (Fleet Offline)

**Severity:** P2  
**Maintainer:** Backend Team / Operations  
**Last Updated:** 2026-01-01  

---

## Overview

This runbook covers scenarios where a large number (or all) of Android devices
simultaneously drop their WebSocket connections to the backend, causing the fleet
to appear offline in the dashboard.

This is a P2 (not P1) because devices continue running autonomously on their last
known state, but remote management is unavailable until reconnected.

---

## Symptoms

- Dashboard shows most/all devices as `status: offline`
- Grafana alert: **FleetOfflineRate > 80%** fires
- WebSocket connection metrics drop to near zero
- Backend logs: repeated `WebSocket connection closed code=1006` or `1011` at high rate
- Redis Pub/Sub channels `ws:device:*` empty after a brief period

---

## Architecture Reference

```
Android Device
│  WebSocket Client (OkHttp3)
│  Reconnect backoff: 1s → 5s → 15s → 60s → 5min
│
└─► nginx (WSS reverse proxy)
      └─► Backend ConnectionManager
            ├─ In-memory connection registry
            ├─ Redis PubSub (cross-instance fan-out)
            └─ Heartbeat: 30s ping / 90s timeout
```

Devices automatically attempt reconnection when the WebSocket is closed. Under
normal circumstances, **all devices should auto-reconnect within 5 minutes**
without manual intervention, once the backend is healthy.

---

## Common Root Causes

| Cause | Detection |
|-------|-----------|
| Backend restarted / deployed | Recent deployment in CI/CD logs |
| nginx restarted (proxy drop) | `docker compose logs nginx` |
| Redis failure (PubSub broken) | `docker compose ps redis` |
| Server-side network change | `ip addr` / routing table |
| Host firewall rule change | `iptables -L` |
| SSL certificate expired | `openssl s_client -connect host:443` |
| Backend OOM restart | dmesg OOM, container exit code 137 |

---

## Diagnosis

### Step 1 — Check backend and infrastructure

Follow [Runbook 01](01-backend-outage.md) Step 1–5 first. If backend is down,
fix it and devices will reconnect automatically.

### Step 2 — Check nginx WebSocket proxy

```bash
# nginx health
docker compose ps nginx
docker compose logs --tail=50 nginx | grep -E "(error|warn|crit)"

# Test WebSocket upgrade directly through nginx
# Replace localhost with your host
curl -v --no-buffer \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" \
  "https://your-domain/ws"
# Expect: 101 Switching Protocols
```

Key nginx WebSocket config (should be in `infrastructure/nginx/conf.d/`):

```nginx
location /ws {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;    # must be > heartbeat timeout
    proxy_send_timeout 3600s;
}
```

If `proxy_read_timeout` is missing or too short (< 90s default), nginx will
drop idle WebSocket connections.

### Step 3 — Check Redis PubSub

```bash
docker compose exec redis redis-cli

# Check if any device channels are active
> PUBSUB CHANNELS ws:device:*
> PUBSUB CHANNELS ws:broadcast:*

# Check Redis memory
> INFO memory
```

### Step 4 — Check SSL certificate

```bash
# Certificate expiry
echo | openssl s_client -connect your-domain.com:443 2>/dev/null | \
  openssl x509 -noout -dates
```

### Step 5 — Measure reconnect rate

```bash
# Are devices reconnecting?
watch -n5 'docker compose logs --no-log-prefix backend --since=30s | \
  grep -c "WebSocket.*connected"'

# Count currently active WebSocket connections
docker compose exec redis redis-cli KEYS "ws:conn:*" | wc -l
```

### Step 6 — Check ConnectionManager state

```bash
# Active connection count from backend metrics
curl -s http://localhost:8000/metrics | grep "ws_connections_active"

# Connection events in last 5 min
docker compose logs --no-log-prefix backend --since=5m | \
  jq 'select(.event | contains("socket") or contains("connect"))' | \
  jq -c '{time: .timestamp, event: .event, device: .device_id}' | tail -30
```

---

## Remediation

### Scenario A — Natural reconnect (infrastructure recovered)

After fixing the root cause (backend, nginx, Redis), devices reconnect on their
own backoff timer. No manual action needed.

**Expected timeline:**
- Within 30 seconds: devices that were in the 1s/5s backoff bucket
- Within 5 minutes: all devices with normal backoff schedule

Monitor:
```bash
# Watch connection count rise
watch -n5 'curl -s http://localhost:8000/metrics | grep ws_connections_active'
```

### Scenario B — nginx proxy timeout too short

```nginx
# infrastructure/nginx/conf.d/sphere.conf
location /ws {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout  3600s;     # ADD or increase
    proxy_send_timeout  3600s;     # ADD or increase
    proxy_connect_timeout 10s;
}
```

```bash
docker compose exec nginx nginx -t   # validate config
docker compose exec nginx nginx -s reload  # reload without drop
```

### Scenario C — Devices stuck in reconnect backoff (5-minute waits)

If devices had many consecutive failures, they may be in the 300-second backoff tier.
Options:

**Option 1 — Wait it out** (recommended if fleet is large, affects network bandwidth)

All devices will reconnect within 5 minutes. Monitor via Grafana.

**Option 2 — Reboot devices (last resort)**

```bash
# Broadcast reboot to all offline devices (if some are still reachable via ADB)
# This resets the reconnect backoff
adb devices | tail -n +2 | awk '{print $1}' | while read serial; do
  echo "Rebooting $serial"
  adb -s $serial reboot &
done
```

**Option 3 — Use PC Agent to trigger reconnect**

If PC Agent has a LAN path to devices, send a `restart_agent` command through
the PC Agent → device ADB bridge.

### Scenario D — Redis PubSub broken (cross-instance fan-out failing)

Symptoms: connections appear in metrics, but commands sent to device from UI
get no response.

```bash
# Restart Redis (all volatile state, connections must re-register)
docker compose restart redis

# Then restart backend (clears in-memory registry, forces device re-registration)
docker compose restart backend
```

> **Note:** Restarting Redis clears VPN IP assignments from volatile keys.
> VPN assignments must be re-applied from the database.
> Backend runs reconciliation on startup — this is automatic.

### Scenario E — SSL certificate expired

```bash
# Renew with Certbot
certbot renew --force-renewal

# OR update manually
cp /path/to/new_cert.pem infrastructure/nginx/certs/cert.pem
cp /path/to/new_key.pem  infrastructure/nginx/certs/key.pem

# Reload nginx (no connection drop)
docker compose exec nginx nginx -s reload
```

Devices will reconnect automatically once SSL is valid.

---

## Preventing Future Mass Disconnects

### Deployment best practice

Use rolling restart to avoid simultaneous connection drops:

```bash
# Instead of docker compose restart backend:

# Build new image
docker compose build backend

# Scale up temporarily (if running multiple replicas)
docker compose up -d --scale backend=2

# Wait for new instance healthy
sleep 30

# Scale back to 1 (old instance removed)
docker compose up -d --scale backend=1
```

### nginx keepalive for backend upstream

```nginx
upstream backend {
    server backend:8000;
    keepalive 32;
}
```

### Heartbeat configuration

Backend heartbeat interval (default 30s) must be less than `proxy_read_timeout`.
Configure in `.env`:

```
WS_HEARTBEAT_INTERVAL=30
WS_CONNECTION_TIMEOUT=90
```

---

## Recovery Verification

Run this checklist after mass disconnect recovery:

```bash
# 1. Connections rising
curl -s http://localhost:8000/metrics | grep ws_connections_active

# 2. Device statuses updating
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/devices?status=online" | jq '.total'

# 3. No error spike in logs
docker compose logs --no-log-prefix backend --since=5m | \
  jq 'select(.level == "error")' | wc -l

# 4. VPN re-established for connected devices
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/vpn/pool-stats"
```

---

## Post-Incident

1. Record how many devices were affected and for how long.
2. Identify the root cause from logs/metrics.
3. Measure auto-reconnect time (target: < 5 minutes for 90% of fleet).
4. If reconnect time was > 10 minutes for any device, investigate the specific
   device's backoff state and Android power-saving settings.
5. Update monitoring if the alert fired too late or thresholds were wrong.

---

## Related Runbooks

- [01-backend-outage.md](01-backend-outage.md) — Backend failure → mass disconnect
- [02-vpn-incident.md](02-vpn-incident.md) — VPN reconnect after devices return online
- [03-database-failure.md](03-database-failure.md) — DB recovery → backend restart → device reconnect
