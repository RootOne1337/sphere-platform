# ADR-002 — Use AmneziaWG for Device VPN Tunnels

**Status:** Accepted  
**Date:** 2024-02-01  
**Deciders:** Infrastructure Lead, Android Team Lead, CTO  

---

## Context

Sphere Platform must provide encrypted, remotely-manageable VPN tunnels between
the backend server and each Android device. Requirements:

1. Tunnel must survive device network changes (mobile data → WiFi)
2. Traffic must be obfuscated to resist DPI (Deep Packet Inspection) in censored
   network environments (customer geography includes restrictive regions)
3. Per-device IP addressing for targeted ADB routing
4. Rapid connect/disconnect via API
5. Kill-switch capability to prevent data leakage

---

## Decision Drivers

- **DPI resistance**: standard WireGuard UDP fingerprint is easily blocked in restrictive networks
- **Mobile network roaming**: VPN must handle IP address changes without manual reconnection
- **Performance**: low CPU overhead on Android devices with limited battery budgets
- **API controllability**: backend must programmatically manage peer configs
- **Android support**: client library must be available for Android

---

## Considered Options

### Option A — Standard WireGuard

WireGuard is the modern high-performance VPN protocol with a minimal kernel module.

**Pros:**
- Excellent performance (kernel-level on Linux)
- Mature tooling (`wg-quick`, `wireguard-tools`)
- Android client app and wg-android library available
- Simple key-based authentication

**Cons:**
- Highly recognizable UDP fingerprint — trivially blocked by restrictive firewalls
  and DPI appliances
- Not viable for customer deployments in certain target markets

### Option B — AmneziaWG (AmneziaVPN WireGuard fork)

AmneziaWG extends WireGuard with traffic obfuscation. It adds:
- Configurable junk packet injection (`Jc`, `Jmin`, `Jmax` parameters)
- Init packet size scrambling (`S1`, `S2`)
- MAC header obfuscation (`H1`–`H4`)

The Android `amneziawg-android` library provides a drop-in replacement for
`wireguard-android`.

**Pros:**
- All WireGuard performance characteristics preserved
- Obfuscation parameters fully configurable per-peer
- `wireguard-tools` compatible (`wg-quick` still works)
- Active maintenance by the AmneziaVPN team
- Opens access to target markets with restrictive networks

**Cons:**
- Less widespread than vanilla WireGuard
- Requires `amneziawg-go` userspace implementation on certain Android versions
  where `wg-quick` kernel module is unavailable
- Server must run AWG kernel module or `amneziawg-go` instead of standard `wireguard`

### Option C — OpenVPN

Mature, widely deployed VPN solution.

**Pros:**
- Excellent cross-platform support
- TCP mode can bypass some firewalls

**Cons:**
- Certificate management significantly more complex than WireGuard key pairs
- Much higher CPU overhead on Android (OpenSSL encryption stack)
- Slower connection establishment
- Difficult to manage per-device configs programmatically
- TCP-over-TCP performance collapse is a known issue in lossy networks

### Option D — Tailscale (managed WireGuard)

**Pros:**
- Zero-config mesh networking
- Built-in key rotation

**Cons:**
- Dependency on Tailscale's external coordination server — unacceptable for
  on-premise deployments with data sovereignty requirements
- Cannot expose per-device IP addresses in our address space
- Not self-hostable without significant Headscale setup

---

## Decision

**Chosen: Option B — AmneziaWG**

The DPI resistance capability is a hard requirement for a significant portion
of our customer base. AmneziaWG provides this while maintaining full WireGuard
compatibility, identical performance characteristics, and a viable Android
integration path.

Junk packet parameters are configurable per-deployment, allowing tuning for
specific network environments without code changes.

---

## Consequences

### Positive

- Devices work in restrictive networks (China, Russia, corporate DPI appliances)
- Same key management as vanilla WireGuard — no new PKI infrastructure needed
- Backend VPN manager can generate peer configs programmatically (`wg genkey`, `wg pubkey`)
- Kill-switch via `iptables SPHERE_KILLSWITCH` chain prevents data leakage when tunnel is down
- Self-healing reconnection handles mobile network roaming transparently

### Negative / Trade-offs

- Server must ship with `amneziawg-dkms` kernel module (handled in Docker image)
- Android integration requires `amneziawg-android` library instead of standard `wireguard-android`
- Obfuscation adds ~5–15% overhead to packet processing (acceptable on modern hardware)
- AWG is less battle-tested than vanilla WireGuard at enterprise scale

### IP Pool Management

We use a dedicated `/16` subnet (`10.100.0.0/16`) for device VPN IPs.
IP assignment is managed in Redis for fast allocation and release.
A reconciliation job on backend startup syncs Redis state with the database.

---

## Links

- [AmneziaVPN GitHub](https://github.com/amnezia-vpn/amneziawg-go)
- [backend/services/vpn_manager.py](../../backend/services/vpn_manager.py)
- [docs/configuration.md — VPN section](../configuration.md#vpn--amneziawg)
- [ADR-003: Redis Pub/Sub for WebSocket](ADR-003-redis-pubsub-websocket.md)
