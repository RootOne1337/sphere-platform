<div align="center">

# Sphere Platform

**Enterprise Android Device Management & Remote Control Platform**

[![CI Backend](https://github.com/RootOne1337/sphere-platform/actions/workflows/ci-backend.yml/badge.svg)](https://github.com/RootOne1337/sphere-platform/actions)
[![CI Android](https://github.com/RootOne1337/sphere-platform/actions/workflows/ci-android.yml/badge.svg)](https://github.com/RootOne1337/sphere-platform/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-4.0.0-brightgreen.svg)](VERSION)

[Documentation](docs/) · [API Reference](docs/api-reference.md) · [Deployment Guide](docs/deployment.md) · [Changelog](CHANGELOG.md)

</div>

---

## Overview

Sphere Platform is a production-ready system for managing, monitoring, and automating large fleets of Android devices over a secure VPN. It provides real-time H.264 streaming, a script automation engine with DAG execution, and deep integration with n8n for workflow automation.

### Key Capabilities

| Capability | Description |
|-----------|-------------|
| **Fleet Management** | Register, group, tag, and monitor hundreds of Android devices |
| **Remote Control** | Real-time H.264 video stream + ADB command execution |
| **Script Automation** | DAG-based scripts with wave/batch execution across device groups |
| **VPN Tunneling** | AmneziaWG (obfuscated WireGuard) per-device tunnels with IP pool |
| **n8n Integration** | Native n8n nodes for no-code workflow automation |
| **PC Agent** | Host-side ADB bridge for USB-connected device discovery |
| **Monitoring** | Prometheus + Grafana dashboards, structured logging, alerting |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Internet / LAN                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS / WSS
                    ┌──────▼──────┐
                    │   nginx      │  TLS termination, rate limiting
                    │  (reverse    │  static assets
                    │   proxy)     │
                    └──────┬───────┘
          ┌────────────────┼──────────────────┐
          │                │                  │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌───────▼──────┐
   │  FastAPI    │  │  Next.js 15 │  │  n8n         │
   │  Backend    │  │  Frontend   │  │  Workflows   │
   │  :8000      │  │  :3000      │  │  :5678       │
   └──────┬───────┘  └─────────────┘  └──────────────┘
          │
   ┌──────┴──────────────────────────┐
   │                                  │
   ▼                                  ▼
PostgreSQL 15              Redis 7 (cache + pub/sub)
(primary data store)       (WS sessions, device status,
                            task queue broker)
          │
   ┌──────▼──────────────────────────────┐
   │          WebSocket Layer             │
   │  ConnectionManager + PubSubRouter   │
   └──────┬──────────────────────────────┘
          │  Secure WebSocket (wss://)
   ┌──────┴───────────────────────────────┐
   │                                       │
   ▼                                       ▼
Android Agent                      PC Agent
(on-device APK)                    (Windows/Linux host)
  - H.264 streaming                  - ADB bridge
  - AmneziaWG VPN                    - Device discovery
  - Command handler                  - LDPlayer manager
  - OTA updates                      - Telemetry
```

> Full architecture documentation: [docs/architecture.md](docs/architecture.md)

---

## Quick Start

### Prerequisites

- Docker Desktop 4.x+ with Compose V2
- 4 GB RAM minimum (8 GB recommended)
- Ports 80, 443, 5432 (dev only), 6379 (dev only) available

### 1 — Clone and generate secrets

```bash
git clone https://github.com/RootOne1337/sphere-platform.git
cd sphere-platform
python scripts/generate_secrets.py          # writes .env.local
```

### 2 — Start the stack

```bash
# Development (with hot-reload)
docker compose -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.override.yml up -d

# Verify all services are healthy
docker compose ps
```

### 3 — Run migrations and bootstrap admin

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/create_admin.py
```

### 4 — Open the UI

| Service | URL |
|---------|-----|
| Web UI | http://localhost |
| API Docs (Swagger) | http://localhost/api/v1/docs |
| API Docs (ReDoc) | http://localhost/api/v1/redoc |
| Grafana | http://localhost:3001 |
| n8n | http://localhost:5678 |

Default super-admin: set via `create_admin.py` (you choose credentials at first run).

---

## Project Structure

```
sphere-platform/
├── backend/                # FastAPI application
│   ├── api/v1/             # REST endpoints (auth, devices, scripts, vpn, …)
│   ├── core/               # Config, RBAC, JWT, dependencies
│   ├── models/             # SQLAlchemy ORM models
│   ├── schemas/            # Pydantic request/response schemas
│   ├── services/           # Business logic layer
│   ├── tasks/              # Celery async tasks
│   ├── websocket/          # ConnectionManager + PubSubRouter
│   └── monitoring/         # Prometheus metrics, health
│
├── frontend/               # Next.js 15 App Router
│   ├── app/(auth)/         # Login page
│   ├── app/(dashboard)/    # Dashboard, Devices, Scripts, Stream, VPN
│   ├── components/         # Reusable UI components (shadcn/ui)
│   ├── hooks/              # React Query data hooks
│   └── lib/                # Axios client, Zustand auth store
│
├── android/                # Android Agent (Kotlin + Hilt)
│   └── app/src/main/       # Services, VPN, Streaming, Commands, DI
│
├── pc-agent/               # PC Agent (Python asyncio)
│   └── agent/              # ADB bridge, discovery, telemetry, WS client
│
├── n8n-nodes/              # Custom n8n integration nodes
│
├── infrastructure/
│   ├── nginx/              # nginx.conf + SSL
│   ├── postgres/           # init.sql, RLS policies, audit policies
│   ├── redis/              # Redis config
│   ├── monitoring/         # Prometheus, Grafana dashboards, Alertmanager
│   └── traefik/            # Alternative: Traefik reverse proxy config
│
├── alembic/                # Database migrations
│   └── versions/           # Migration scripts
│
├── tests/                  # Pytest test suite
├── scripts/                # Utility scripts (secrets, admin bootstrap)
├── .github/                # CI/CD workflows, PR template, CODEOWNERS
└── docs/                   # This documentation
```

---

## Tech Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Framework | FastAPI 0.109 + Uvicorn |
| ORM | SQLAlchemy 2.0 async |
| Database | PostgreSQL 15 |
| Cache / Broker | Redis 7.2 |
| Auth | JWT HS256 (access + refresh) + TOTP MFA |
| Task Queue | Celery + Redis |
| Metrics | Prometheus + structlog |
| Migrations | Alembic |

### Frontend
| Component | Technology |
|-----------|-----------|
| Framework | Next.js 15 (App Router) |
| State | Zustand + TanStack Query v5 |
| UI | shadcn/ui + Radix UI + Tailwind |
| Charts / DAG | Recharts + @xyflow/react |
| Auth | JWT refresh rotation |

### Mobile
| Component | Technology |
|-----------|-----------|
| Language | Kotlin |
| DI | Hilt (Dagger) + WorkManager |
| Streaming | MediaProjection + MediaCodec (H.264) |
| VPN | AmneziaWG (wg-quick) |
| Transport | OkHttp3 WebSocket |

### Infrastructure
| Component | Technology |
|-----------|-----------|
| Reverse Proxy | nginx |
| Containers | Docker Compose V2 |
| CI/CD | GitHub Actions |
| Monitoring | Prometheus + Grafana + Alertmanager |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System design, data flow, component diagrams |
| [API Reference](docs/api-reference.md) | REST endpoints, request/response schemas |
| [Deployment Guide](docs/deployment.md) | Docker, production, staging, scaling |
| [Configuration](docs/configuration.md) | All environment variables reference |
| [Security](docs/security.md) | Auth, RBAC, encryption, threat model |
| [Developer Guide](docs/development.md) | Local setup, testing, coding standards |
| [Android Agent](docs/android-agent.md) | APK build, deployment, update procedure |
| [PC Agent](docs/pc-agent.md) | Installation, ADB bridge, LDPlayer integration |
| [Runbooks](docs/runbooks/) | Incident response and operational procedures |
| [ADR](docs/adr/) | Architecture Decision Records |
| [Contributing](CONTRIBUTING.md) | How to contribute, branch strategy, PR process |
| [Security Policy](SECURITY.md) | Vulnerability reporting process |
| [Changelog](CHANGELOG.md) | Release history |
| [ADR](docs/adr/) | Architecture Decision Records |
| [Runbooks](docs/runbooks/) | Operational incident response runbooks |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide.

```bash
# Fork, clone, create branch
git checkout -b feat/SPHERE-XXX-short-description

# Install pre-commit hooks
pre-commit install

# Run tests before pushing
cd backend && pytest -x
```

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
