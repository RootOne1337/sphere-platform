# Security

> **Sphere Platform v4.6** — Security Architecture & Hardening Guide

---

## Table of Contents

1. [Threat Model](#1-threat-model)
2. [Authentication](#2-authentication)
3. [Authorization (RBAC)](#3-authorization-rbac)
4. [Data Encryption](#4-data-encryption)
5. [Network Security](#5-network-security)
6. [Input Validation](#6-input-validation)
7. [Audit & Logging](#7-audit--logging)
8. [Secret Management](#8-secret-management)
9. [Dependency Security](#9-dependency-security)
10. [Security Checklist](#10-security-checklist)
11. [Vulnerability Response](#11-vulnerability-response)
12. [v4.3–4.6 Security Enhancements](#12-v43-46-security-enhancements)

---

## 1. Threat Model

### Assets

| Asset | Classification | Risk |
|-------|---------------|------|
| Device control (ADB commands) | Critical | Unauthorized commands, data theft |
| VPN peer configs / private keys | Critical | Network exposure, peer impersonation |
| User credentials / JWT secrets | Critical | Account takeover, privilege escalation |
| Device fleet status | Confidential | Business intelligence leakage |
| Audit logs | Confidential | Tamper, cover-tracks |
| Script DAG definitions | Internal | IP theft, malicious script injection |

### Threat Actors

| Actor | Access Level | Primary Risk |
|-------|-------------|--------------|
| Unauthenticated internet user | None | Brute force, injection |
| Authenticated viewer | Low | IDOR, privilege escalation |
| Compromised device agent | Low-medium | Command injection via device events |
| Malicious org admin | High (within org) | Cross-org data access |
| Compromised super_admin | Full | Full platform compromise |

### Out-of-Scope

- Physical device theft
- Android OS vulnerabilities
- WireGuard server infrastructure (external component)

---

## 2. Authentication

### JWT Implementation

- **Algorithm:** HS256 (HMAC-SHA256)
- **Access token TTL:** 30 minutes
- **Refresh token TTL:** 7 days
- **Refresh token storage:** Redis, indexed by `jti`; invalidated on logout
- **Refresh transport:** `HttpOnly; Secure; SameSite=Strict` cookie — not accessible to JavaScript

**Token claims:**
```json
{
  "sub": "<user_uuid>",
  "org_id": "<org_uuid>",
  "role": "org_admin",
  "jti": "<unique_token_id>",
  "iat": 1740301200,
  "exp": 1740303000
}
```

### MFA (TOTP)

- TOTP RFC 6238 compliant
- 30-second window with ±1 step tolerance
- Backup codes: 10 × 8-char alphanumeric, single-use
- Secrets stored as encrypted blobs (Fernet), never in plaintext

### Brute Force Protection

- `/auth/login`: `slowapi` rate limiting — **10 requests/minute per IP**
- Failed login counter in Redis: after 10 failures, account locked for 15 minutes
- Lock event recorded in audit log

### Password Policy

- Minimum 8 characters
- Hashed with `bcrypt` (cost factor 12)
- No plaintext storage anywhere in the system

### API Keys

- Формат: `sphr_{env}_{64hex}` (256-bit энтропия)
- Хранится как bcrypt hash, полный ключ показывается только при создании
- Scoped to user (наследует роль/org_id пользователя)
- Optional expiry date
- **Приоритет над JWT:** при одновременной передаче `Authorization: Bearer` и `X-API-Key` — API-ключ проверяется первым (v4.6.0)
- Revocable at any time

---

## 3. Authorization (RBAC)

### Enforcement Layers

Authorization is enforced at **three independent layers**:

1. **Dependency injection** (`require_permission()`) — in every route handler
2. **Row-Level Security** (PostgreSQL RLS) — at the database level
3. **Tenant middleware** — sets `app.current_org_id` before any handler runs

This defense-in-depth means a bug at any single layer cannot alone grant unauthorized access.

### Permission Check Pattern

```python
@router.delete("/devices/{device_id}")
async def delete_device(
    device_id: UUID,
    current_user: User = Depends(require_permission("device:delete")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

`require_permission()` raises `403 Forbidden` if the user's role is not in the
permission matrix (see [architecture.md](architecture.md#rbac-permission-matrix)).

### Cross-Org Isolation

Every model contains an `org_id` column. RLS policies ensure:

```sql
-- No query can return rows from a different org, even with a direct SQL injection
-- that bypasses the ORM, because RLS is enforced at the DB connection level
POLICY "org_isolation" ON devices
  USING (org_id = current_setting('app.current_org_id')::UUID);
```

The `super_admin` role bypasses RLS only when explicitly needed (dashboard stats),
and all such bypasses are gated behind `require_role("super_admin")`.

---

## 4. Data Encryption

### At Rest

| Data | Method | Key Location |
|------|--------|--------------|
| User passwords | bcrypt (cost=12) | Not reversible |
| TOTP secrets | Fernet symmetric | `VPN_KEY_ENCRYPTION_KEY` |
| VPN peer private keys | Fernet symmetric | `VPN_KEY_ENCRYPTION_KEY` |
| Refresh tokens in Redis | Opaque UUID, not reversible | — |
| PostgreSQL data files | OS-level encryption recommended | Host managed |

**Fernet encryption** (AES-128-CBC + HMAC-SHA256) from `cryptography` library is used
for all symmetric encryption. Keys must be stored separately from the database
(environment variable or secrets manager).

### In Transit

- All external traffic: TLS 1.2+ (nginx enforced)
- WebSocket connections: WSS (WebSocket over TLS)
- Backend ↔ PostgreSQL: plaintext (internal Docker network) — enable `sslmode=require` for multi-host non-Docker deployments
- Backend ↔ Redis: plaintext (internal Docker network) — use TLS stunnel for multi-host

### TLS Configuration (nginx)

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
add_header X-Frame-Options DENY always;
add_header X-Content-Type-Options nosniff always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

---

## 5. Network Security

### Exposed Ports (Production)

| Port | Protocol | Service | Public |
|------|----------|---------|--------|
| 80 | TCP | nginx HTTP → HTTPS redirect | ✓ |
| 443 | TCP | nginx HTTPS | ✓ |
| 51820 | UDP | WireGuard VPN | ✓ (devices only) |
| 5432 | TCP | PostgreSQL | ✗ (internal only) |
| 6379 | TCP | Redis | ✗ (internal only) |
| 8000 | TCP | FastAPI (Uvicorn) | ✗ (nginx only) |
| 3000 | TCP | Next.js | ✗ (nginx only) |
| 9090 | TCP | Prometheus | ✗ (internal only) |
| 3001 | TCP | Grafana | ✗ (VPN/bastion only) |

### Rate Limiting (nginx)

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=300r/m;
limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/m;

location /api/v1/auth/login {
    limit_req zone=auth burst=5 nodelay;
}
location /api/v1/ {
    limit_req zone=api burst=50 nodelay;
}
```

### CORS

CORS is configured in `backend/core/cors.py`. Only the configured `SERVER_HOSTNAME`
and the n8n host are in the allow-list. Wildcard origins (`*`) are **never permitted**.

### VPN Kill Switch (Android)

AmneziaWG tunnels use a hardware-level kill switch:

```
iptables -N SPHERE_KILLSWITCH
iptables -A SPHERE_KILLSWITCH -i lo -j ACCEPT
iptables -A SPHERE_KILLSWITCH -o sphere0 -j ACCEPT
iptables -A SPHERE_KILLSWITCH -d <vpn_endpoint>/32 -j ACCEPT
iptables -A SPHERE_KILLSWITCH -j DROP
iptables -A OUTPUT -j SPHERE_KILLSWITCH
```

This prevents traffic leaks if the VPN tunnel drops.

---

## 6. Input Validation

### Backend

- All request bodies validated by **Pydantic v2** schemas — unknown fields rejected by default
- Path/query parameters validated via FastAPI dependency injection
- UUID path parameters typed as `uuid.UUID` — prevents injection via malformed IDs
- SQL queries use **SQLAlchemy ORM** or explicit parameterized queries — raw SQL is never
  constructed from user input
- Script DAG expressions evaluated in a **sandboxed evaluator** — no `eval()` or `exec()`
  on user input; only a whitelist of operators is supported

### Frontend

- All API responses validated with TypeScript types
- User input fields use React controlled components
- XSS: React JSX auto-escapes all rendered content
- No `dangerouslySetInnerHTML` used anywhere
- Content Security Policy header set by nginx

### Android Agent

- All incoming WebSocket messages validated with Kotlin data class deserialization
- Command allow-list: only pre-defined command types accepted
- ADB commands are passed as argument arrays (no shell substitution) — prevents injection

---

## 7. Audit & Logging

### Audit Log

Every mutating API operation is recorded in `audit_logs`:

```python
# Automatically via AuditMiddleware
{
    "actor_id": current_user.id,
    "actor_email": current_user.email,
    "org_id": current_user.org_id,
    "action": "device.delete",
    "resource_type": "device",
    "resource_id": device_id,
    "remote_ip": request.client.host,
    "user_agent": request.headers.get("user-agent"),
    "metadata": { ... }
}
```

Audit log rows have no DELETE permission in RLS — they are **append-only** at the
database level.

### Security Events Logged

| Event | Log Level |
|-------|-----------|
| Login success / failure | INFO / WARNING |
| MFA setup / verify | INFO |
| Account locked | WARNING |
| JWT validation failure | WARNING |
| Permission denied (403) | WARNING |
| Rate limit exceeded (429) | WARNING |
| Device command sent | INFO |
| VPN peer provisioned / revoked | INFO |
| Bulk action executed | INFO |
| Admin user created | WARNING |

### Log Shipping

In production, pipe structlog JSON output to a log shipper:
```yaml
# docker-compose.production.yml
backend:
  logging:
    driver: "json-file"
    options:
      max-size: "100m"
      max-file: "10"
```

For Loki / Elasticsearch ingestion, use Promtail or Filebeat on the host.

---

## 8. Secret Management

### Development

Use `scripts/generate_secrets.py` to generate `.env.local`. Never commit this file.

### Production

Use a dedicated secrets manager:

| Platform | Solution |
|----------|----------|
| AWS | AWS Secrets Manager + `aws-secretsmanager-caching-python` |
| GCP | GCP Secret Manager |
| Self-hosted | HashiCorp Vault |
| Kubernetes | Kubernetes Secrets + External Secrets Operator |

Example with HashiCorp Vault:
```bash
# Store secrets
vault kv put secret/sphere-platform \
  JWT_SECRET_KEY="..." \
  POSTGRES_PASSWORD="..." \
  VPN_KEY_ENCRYPTION_KEY="..."

# Inject into container via Vault Agent sidecar or envconsul
```

### Secret Scanning

Pre-commit hook (`detect-secrets`):
```bash
# Install
pip install detect-secrets
detect-secrets scan > .secrets.baseline

# Pre-commit check
detect-secrets audit .secrets.baseline
```

---

## 9. Dependency Security

### Automated Scanning

GitHub Actions CI runs:
- `bandit -r backend/` — Python security linter
- `pip-audit` — known CVE scan for Python dependencies
- `npm audit` — CVE scan for Node.js dependencies
- `detect-secrets scan` — secret pattern detection

### Dependency Update Policy

- Security patches: applied within **48 hours** of disclosure
- Minor updates: monthly review cycle
- Major updates: quarterly, with full regression test run

### SBOM

Software Bill of Materials generated in CI:
```bash
pip-audit --format=json --output sbom-backend.json
cd frontend && npm list --json > sbom-frontend.json
```

---

## 10. Security Checklist

Use this for every PR and every deployment:

### Code Review

- [ ] No raw SQL with user-controlled input (use ORM or `bindparam`)
- [ ] No `eval()` or `exec()` with user input
- [ ] No `dangerouslySetInnerHTML` or `v-html` (frontend)
- [ ] All new endpoints protected by `require_permission()`
- [ ] Sensitive data not logged (passwords, tokens, private keys)
- [ ] Foreign keys verified against `org_id` (IDOR prevention)
- [ ] File uploads: MIME type validated, stored outside web root

### Pre-Deploy

- [ ] `bandit -r backend/` passes
- [ ] `ruff check backend/` passes
- [ ] `mypy backend/` passes without errors
- [ ] `pip-audit` shows no critical CVEs
- [ ] `detect-secrets scan --baseline .secrets.baseline` is clean
- [ ] All secrets rotated if any were exposed
- [ ] Database migrations tested on a copy of production data
- [ ] Backup completed before migration

### Production Verification

- [ ] `GET /health` returns 200
- [ ] `GET /api/v1/auth/login` rate limiting active (test: 15 rapid requests → 429)
- [ ] SSL Labs grade A+ on your domain
- [ ] HTTP Security Headers present (`curl -I https://yourdomain.com`)
- [ ] Database ports NOT accessible from internet (`nmap -p 5432 yourdomain.com` → filtered)

---

## 11. Vulnerability Response

See [SECURITY.md](../SECURITY.md) for the full vulnerability disclosure policy.

### Summary

1. Report vulnerabilities to **security@yourdomain.com** (PGP key available on request)
2. Do **not** open public GitHub issues for security vulnerabilities
3. Expected initial response: **24 hours**
4. Expected fix timeline: **7 days** for critical, **30 days** for high/medium

### Severity Classification

| Severity | CVSS | Example | SLA |
|----------|------|---------|-----|
| Critical | 9.0–10.0 | RCE, auth bypass, cross-org data access | 24 hours |
| High | 7.0–8.9 | IDOR, privilege escalation, data leak | 7 days |
| Medium | 4.0–6.9 | XSS, info disclosure | 30 days |
| Low | 0.1–3.9 | Minor info leak, rate limit bypass | 90 days |

---

## 12. v4.3–4.6 Security Enhancements

### v4.3 — Android Agent Watchdog механизмы
- **ConfigWatchdog** — периодический опрос конфига из GitHub Raw (5 мин онлайн / 60с оффлайн)
- **ServiceWatchdog** — AlarmManager keepalive каждые 5 мин
- **Circuit Breaker → Config Hook** — 10+ ошибок → немедленная проверка конфига
- Тройная защита от kill: BootReceiver + START_STICKY + AlarmManager

### v4.4 — Device Inspector + REST команды
- `POST /devices/{id}/reboot` — перезагрузка через WS
- `POST /devices/{id}/shell` — shell-команды (защищено `require_permission("device:command")`)
- `POST /devices/{id}/logcat` — сбор логов
- `GET /devices/{id}/screenshot` — скриншот

### v4.5 — Stale-task detection + Serveo tunnel
- **Stale-task detection** — двухуровневое определение зависших задач:
  1. Устройство оффлайн → задача автоматически TIMEOUT
  2. Абсолютный предохранитель 24ч — защита от забытых задач
- **Serveo SSH Tunnel** — замена Cloudflare Quick Tunnel (WebSocket idle drop через 5–50с)
  - Alpine + openssh-client, ssh -N reconnect loop, ServerAliveInterval=30
  - Домен: `sphere.serveousercontent.com`
- **SPS/PPS/IDR кэширование** в StreamBridge — мгновенный старт для viewer
- **Dynamic server URL** через ConfigWatchdog — APK не требует пересборки

### v4.6 — Нагрузочное тестирование + Android hardening
- **API Key приоритет** — X-API-Key проверяется первым при одновременной передаче с Bearer
- **Android wsLock** — ReentrantLock для потокобезопасной отправки WS-сообщений
- **CPU delta debounce** — игнорирование скачков <3%
- **Reconnect debounce 5с** — защита от reconnect storm
- **MediaCodec guard** — `isEncoding` проверка перед callback
- **CRLF → LF** в Docker entrypoint.sh — устранение exec format error
- **1 231 тест** по всему проекту (94 файла): APK 272, Backend 759, Frontend 132, Load 68
