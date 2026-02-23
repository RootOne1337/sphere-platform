# Runbook 02 — VPN Tunnel Failure & Pool Exhaustion

**Severity:** P1  
**Maintainer:** Infrastructure / Backend Team  
**Last Updated:** 2026-01-01  

---

## Overview

This runbook covers failures in the AmneziaWG (WireGuard-based) VPN subsystem,
including: individual tunnel failures, IP pool exhaustion, kill-switch lockout,
and peer connectivity issues.

---

## Symptoms

### Tunnel failure

- Devices show `vpn_status: disconnected` in the dashboard despite `vpn_connect` command succeeding
- ADB commands time out after VPN connect (device network unreachable via VPN IP)
- Backend API returns `{"detail": "VPN tunnel failed to establish"}` for connect requests
- Grafana alert: **VpnTunnelFailureRate** fires

### Pool exhaustion

- Backend API returns HTTP 503: `{"detail": "No available VPN IPs in pool"}`
- Grafana: **VpnPoolUtilization > 90%** alert fires
- `GET /api/v1/vpn/pool-stats` returns `{"available": 0, "assigned": N, "total": N}`

### Kill-switch lockout

- Device connected to VPN but cannot reach any host (including backend)
- `vpn_disconnect` command does not restore connectivity
- ADB log shows `iptables REJECT` for all outgoing traffic

---

## Architecture Reference

```
Backend VPN Manager
│
├─ WireGuard interface: wg0
├─ IP Pool: 10.100.0.0/16 (65534 addresses)
├─ Peer config: /etc/wireguard/peers/<device_id>.conf
│
└─ Kill-switch chain: SPHERE_KILLSWITCH (iptables)
       └─ ACCEPT wg0 traffic
       └─ ACCEPT loopback
       └─ REJECT all other traffic (when kill-switch enabled)
```

VPN state lifecycle:
```
DISCONNECTED → [vpn_connect] → CONNECTING → CONNECTED
CONNECTED    → [vpn_disconnect] → DISCONNECTING → DISCONNECTED
CONNECTED    → [tunnel loss]  → ERROR → [self-heal] → RECONNECTING
```

---

## Diagnosis

### Step 1 — Check VPN service status

```bash
# Is wireguard interface up?
docker compose exec backend wg show wg0

# Check pool stats
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/vpn/pool-stats | jq

# Check VPN health endpoint
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/vpn/health | jq
```

Expected `wg show` output includes active peers, transfer bytes, and last-handshake times.

### Step 2 — Review VPN events

```bash
# Recent VPN errors from backend logs
docker compose logs --no-log-prefix backend | \
  jq 'select(.event | contains("vpn") or contains("VPN"))' | tail -50

# WireGuard kernel logs
journalctl -k | grep -i "wireguard" | tail -20
dmesg | grep -i "wireguard" | tail -20
```

### Step 3 — Check specific device VPN state

```bash
# Get device VPN status
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/devices/<device_id>" | jq .vpn_status

# List all devices with VPN errors
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/devices?vpn_status=error" | jq '.items[].id'
```

### Step 4 — Check IP pool state in Redis

```bash
docker compose exec redis redis-cli
> SMEMBERS vpn:pool:available   # available IPs
> SMEMBERS vpn:pool:assigned    # assigned IPs
> HGETALL  vpn:peer:assignments # device_id → IP mapping
```

### Step 5 — Check WireGuard peer configs

```bash
# List generated peer configs
ls -la /etc/wireguard/peers/ 2>/dev/null || \
  docker compose exec backend ls /etc/wireguard/peers/

# Check a specific peer
docker compose exec backend cat /etc/wireguard/peers/<device_id>.conf
```

---

## Remediation

### Scenario A — Individual tunnel failure (single device)

```bash
# Force-disconnect and reconnect via API
DEVICE_ID="<device_id>"
TOKEN="<admin_token>"

# 1. Force disconnect
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/vpn/peers/$DEVICE_ID/disconnect?force=true"

# 2. Wait 3 seconds
sleep 3

# 3. Reconnect
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "http://localhost:8000/api/v1/vpn/peers/$DEVICE_ID/connect"

# 4. Check tunnel state after 10 seconds
sleep 10
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/devices/$DEVICE_ID" | jq '{id, vpn_status, vpn_ip}'
```

### Scenario B — Mass tunnel failures (10+ devices)

This often indicates a WireGuard interface restart or host reboot.

```bash
# 1. Restart WireGuard interface
docker compose exec backend wg-quick down wg0 || true
docker compose exec backend wg-quick up wg0

# 2. Restart backend (reloads peer configs)
docker compose restart backend

# 3. Trigger re-register from devices via broadcast WebSocket command
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "http://localhost:8000/api/v1/devices/bulk-actions" \
  -d '{"action": "reconnect_vpn", "all_devices": true}'
```

### Scenario C — IP pool exhaustion

#### Immediate relief: reclaim stale assignments

```bash
# Find devices that have an assigned IP but haven't connected in >24h
docker compose exec redis redis-cli HGETALL vpn:peer:assignments | \
  paste - - | while read device_id ip; do
    last_seen=$(curl -s -H "Authorization: Bearer $TOKEN" \
      "http://localhost:8000/api/v1/devices/$device_id" | jq -r .last_seen)
    echo "$device_id $ip $last_seen"
  done
```

```bash
# Force-release stale IP assignment
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/vpn/peers/$STALE_DEVICE_ID/ip-lease"
```

#### Permanent fix: expand IP pool range

In `backend/core/config.py`, increase `VPN_IP_POOL_SIZE` or change the CIDR:

```python
VPN_IP_POOL_CIDR: str = "10.100.0.0/15"   # was /16 (65534), now /15 (131070)
```

Then restart backend to regenerate the pool:

```bash
docker compose exec redis redis-cli DEL vpn:pool:available vpn:pool:assigned
# WARNING: this clears all VP assignments — devices must reconnect
docker compose restart backend
```

### Scenario D — Kill-switch lockout

If a device's kill-switch is active and the VPN tunnel is down, the device
loses all network access, including the ability to reconnect.

**Recovery options (in order of preference):**

**Option 1 — Send disable-killswitch command if device still reachable via ADB USB**

```bash
# Via PC Agent (LAN)
adb -s <device_serial> shell \
  "su -c 'iptables -F SPHERE_KILLSWITCH && iptables -D OUTPUT -j SPHERE_KILLSWITCH 2>/dev/null'"
```

**Option 2 — Reboot device (kill-switch does not persist across reboot by default)**

```bash
adb -s <device_serial> reboot
# Wait for boot (~60s), then reconnect VPN from UI
```

**Option 3 — Factory / ADB shell reset (last resort)**

```bash
adb -s <device_serial> shell settings put global airplane_mode_on 1
adb -s <device_serial> shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true
sleep 5
adb -s <device_serial> shell settings put global airplane_mode_on 0
adb -s <device_serial> shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false
```

### Scenario E — Backend VPN manager crashed / stuck

```bash
# Check for stuck WireGuard config lock
ls -la /var/run/wireguard/ 2>/dev/null
rm -f /var/run/wireguard/wg0.lock  # if stuck

# Restart backend service
docker compose restart backend

# Verify wg0 interface is back
docker compose exec backend wg show
```

---

## Self-Healing Configuration

The backend VPN manager has built-in self-healing. Check its settings:

```bash
# Current config values
docker compose exec backend python -c "
from backend.core.config import settings
print('reconnect_attempts:', settings.VPN_RECONNECT_ATTEMPTS)
print('reconnect_backoff_sec:', settings.VPN_RECONNECT_BACKOFF_SEC)
print('keepalive_interval:', settings.VPN_KEEPALIVE_INTERVAL_SEC)
"
```

Backoff schedule: `1s → 5s → 15s → 60s → 300s` (capped at 5 minutes).

---

## Post-Incident

1. Document which devices were affected and for how long.
2. Review backend logs for the VPN event sequence.
3. Check if IP pool high-watermark was reached.
4. If pool exhaustion was the cause, create a GitHub Issue for CIDR expansion.
5. Update monitoring thresholds if alerts fired too late (or too early).

---

## Related

- [01-backend-outage.md](01-backend-outage.md) — If VPN failure is caused by backend crash
- [04-fleet-offline.md](04-fleet-offline.md) — Mass device disconnect including VPN
- [docs/configuration.md](../configuration.md) — VPN configuration variables
