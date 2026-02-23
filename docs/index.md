# Sphere Platform — Documentation

Welcome to the Sphere Platform documentation.

Sphere is a production-grade Android device management platform with real-time
remote control, VPN tunneling, automation scripting, and H.264 streaming.

---

## Quick Navigation

### For Operators

| Document | Description |
|----------|-------------|
| [Deployment Guide](deployment.md) | Install Sphere on your server (Docker Compose) |
| [Configuration Reference](configuration.md) | All environment variables and their meaning |
| [Runbooks](runbooks/README.md) | Step-by-step incident response procedures |

### For Developers

| Document | Description |
|----------|-------------|
| [Development Guide](development.md) | Local setup, conventions, testing |
| [API Reference](api-reference.md) | Full REST + WebSocket API documentation |
| [Architecture Overview](architecture.md) | System design, data flows, DB schema |

### For Security & Compliance

| Document | Description |
|----------|-------------|
| [Security Architecture](security.md) | Auth, RBAC, encryption, threat model |
| [Security Policy](../SECURITY.md) | Vulnerability reporting and response SLA |

### Component Deep-Dives

| Document | Description |
|----------|-------------|
| [Android Agent](android-agent.md) | Build, deploy, configure Android agent APK |
| [PC Agent](pc-agent.md) | Install and operate the Windows/Linux PC agent |

### Architecture Decisions

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](adr/ADR-001-fastapi-over-django.md) | FastAPI over Django | Accepted |
| [ADR-002](adr/ADR-002-amneziawg-vpn.md) | AmneziaWG VPN | Accepted |
| [ADR-003](adr/ADR-003-redis-pubsub-websocket.md) | Redis Pub/Sub for WebSocket | Accepted |
| [ADR-004](adr/ADR-004-dag-script-engine.md) | DAG-based Script Engine | Accepted |
| [ADR-005](adr/ADR-005-hilt-android-di.md) | Hilt for Android DI | Accepted |

---

## Platform Overview

```
┌──────────── Sphere Platform v4.0 ────────────────┐
│                                                   │
│  Web UI (Next.js 15)                              │
│    └─ REST + WebSocket ─► FastAPI backend         │
│                               │                  │
│         ┌─────────────────────┤                  │
│         │                     │                  │
│   PostgreSQL 15           Redis 7.2               │
│   (primary store)         (cache + pub/sub)       │
│                                                   │
│  Android Devices ◄──── WireGuard VPN ────────────│
│  (Kotlin Agent)          AmneziaWG                │
│      │                       │                   │
│      └── H.264 stream ───────┘                   │
│      └── WebSocket ──────────┘                   │
│                                                   │
│  PC Agent (Python) ──── ADB ──── Android Devices  │
│                                                   │
│  n8n Integration ──── REST API ──► Backend        │
└───────────────────────────────────────────────────┘
```

---

## Key Concepts

### Multi-tenancy

Sphere is fully multi-tenant. Every resource (devices, groups, scripts, users)
belongs to an **Organization**. PostgreSQL Row-Level Security enforces tenant
isolation at the database layer.

### RBAC

Seven roles in two hierarchies:

| Role | Scope |
|------|-------|
| `super_admin` | Cross-organization platform administration |
| `org_admin` | Full organization management |
| `operator` | Device operations and script execution |
| `developer` | Script development and testing |
| `viewer` | Read-only access |
| `api_key` | Programmatic integrations |
| `pc_agent` | PC agent service account |

### Devices

An Android device runs the Sphere Agent APK. After registration, it:
1. Opens a persistent WebSocket connection to the backend
2. Optionally establishes an AmneziaWG VPN tunnel
3. Responds to commands (adb_exec, screenshot, stream_start, vpn_connect, etc.)

### Scripts

Automation scripts are DAG-defined workflows that execute commands across device
fleets. Steps within a script can be parallelized via wave-batch execution.

### VPN

Each device gets a unique VPN IP from the `10.100.0.0/16` pool. This enables
targeted ADB routing and guarantees private addressing even when devices move
between networks.

---

## Getting Help

- **GitHub Issues** — bugs and feature requests
- **Contributing** — see [CONTRIBUTING.md](../CONTRIBUTING.md)
- **Security** — see [SECURITY.md](../SECURITY.md)

---

*Generated for Sphere Platform v4.0.0*
