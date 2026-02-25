# API Reference

> **Sphere Platform v4.1** — REST API

**Base URL:** `https://yourdomain.com/api/v1`
**Interactive docs:** `https://yourdomain.com/api/v1/docs` (Swagger UI)
**OpenAPI spec:** `https://yourdomain.com/api/v1/openapi.json`

---

## Authentication

All endpoints (except `/auth/login`, `/health`, and `/config/agent`) require a Bearer token.

```http
Authorization: Bearer <access_token>
```

Tokens are obtained via the login endpoint and refreshed via `/auth/refresh`.

### Error responses

| Code | Meaning |
|------|---------|
| `401` | Missing or invalid token |
| `403` | Insufficient permissions |
| `404` | Resource not found |
| `422` | Validation error |
| `429` | Rate limit exceeded |
| `500` | Internal server error |

---

## Auth — `/auth`

### POST /auth/login

```http
POST /auth/login
Content-Type: application/json

{
  "email": "admin@example.com",
  "password": "securepassword",
  "totp_code": "123456"    // required if MFA enabled
}
```

**Response 200:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "uuid",
    "email": "admin@example.com",
    "role": "super_admin",
    "org_id": "uuid"
  }
}
```

Refresh token is set as `HttpOnly` cookie `sphere_refresh`.

---

### POST /auth/refresh

```http
POST /auth/refresh
Cookie: sphere_refresh=<refresh_token>
```

**Response 200:**
```json
{
  "access_token": "eyJ...",
  "expires_in": 1800
}
```

---

### POST /auth/logout

```http
POST /auth/logout
Authorization: Bearer <token>
```

Revokes the refresh token. Returns `204 No Content`.

---

### POST /auth/mfa/setup

```http
POST /auth/mfa/setup
Authorization: Bearer <token>
```

**Response 200:**
```json
{
  "secret": "BASE32SECRET",
  "qr_uri": "otpauth://totp/Sphere:user@example.com?secret=BASE32SECRET&issuer=Sphere",
  "backup_codes": ["xxxx-xxxx", "xxxx-xxxx"]
}
```

---

### POST /auth/mfa/verify

```http
POST /auth/mfa/verify
Authorization: Bearer <token>

{ "code": "123456" }
```

Returns `200 { "mfa_enabled": true }` on success.

---

### GET /auth/me

```http
GET /auth/me
Authorization: Bearer <token>
```

**Response 200:**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "username",
  "role": "org_admin",
  "org_id": "uuid",
  "mfa_enabled": false,
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

## Agent Config — `/config`

> Добавлено в v4.1.0 (TZ-12)

### GET /config/agent

Получение конфигурации для агента. **Не требует авторизации** (soft-auth: если передан токен — используется `org_id` из JWT, иначе — конфиг по умолчанию).

```http
GET /config/agent
```

**Response 200:**
```json
{
  "server": {
    "wsUrl": "wss://sphere.example.com/ws",
    "apiUrl": "https://sphere.example.com/api/v1",
    "environment": "production"
  },
  "agent": {
    "heartbeatIntervalMs": 30000,
    "reconnectMaxRetries": 10,
    "logLevel": "INFO"
  },
  "features": {
    "autoRegister": true,
    "autoUpdate": true,
    "telemetryEnabled": true,
    "vpnAutoConnect": false
  },
  "provisioning": {
    "namingPattern": "sphere-{org}-{seq}",
    "defaultTags": ["auto-registered"],
    "defaultGroupId": null
  }
}
```

Конфигурация загружается из `agent-config/environments/{env}.json` и кэшируется в Redis (TTL 300s).

---

## Device Registration — `/devices/register`

> Добавлено в v4.1.0 (TZ-12)

### POST /devices/register

Идемпотентная авторегистрация устройства по composite fingerprint. При повторном вызове с тем же fingerprint возвращает существующее устройство.

```http
POST /devices/register
Content-Type: application/json

{
  "fingerprint": "a1b2c3d4e5f6...sha256hash",
  "device_info": {
    "model": "sdk_gphone64_x86_64",
    "android_version": "13",
    "sdk_version": 33,
    "manufacturer": "Google",
    "display": "TP1A.220624.014"
  },
  "agent_version": "1.2.0"
}
```

**Response 200 (существующее устройство):**
```json
{
  "device_id": "uuid",
  "name": "sphere-dev-0042",
  "is_new": false,
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Response 201 (новое устройство):**
```json
{
  "device_id": "uuid",
  "name": "sphere-dev-0043",
  "is_new": true,
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Логика дедупликации:**
- Поиск по `device.fingerprint @> '{"hash": "<fingerprint>"}'` (JSONB containment)
- Если устройство найдено — обновляет `device_info`, генерирует новые токены
- Если не найдено — создаёт устройство с авто-именем `sphere-{org_prefix}-{sequence}`

**Не требует авторизации** (создаёт токены в процессе регистрации).

---

## Devices — `/devices`

### GET /devices

List devices with optional filtering and pagination.

```http
GET /devices?status=ONLINE&group_id=uuid&tag=production&page=1&per_page=50
Authorization: Bearer <token>
```

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `status` | `ONLINE\|OFFLINE\|BUSY\|ERROR` | Filter by status |
| `group_id` | UUID | Filter by device group |
| `tag` | string | Filter by tag |
| `search` | string | Search by name or serial |
| `page` | int | Page number (default: 1) |
| `per_page` | int | Items per page (default: 50, max: 200) |

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Device-001",
      "serial": "emulator-5554",
      "status": "ONLINE",
      "tags": ["production", "group-a"],
      "group_id": "uuid",
      "org_id": "uuid",
      "last_seen": "2026-02-23T10:00:00Z",
      "vpn_ip": "10.100.0.5",
      "battery_level": 87,
      "android_version": "13"
    }
  ],
  "total": 142,
  "page": 1,
  "per_page": 50
}
```

---

### POST /devices

Register a new device.

```http
POST /devices
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Device-001",
  "serial": "emulator-5554",
  "tags": ["production"],
  "group_id": "uuid"
}
```

**Response 201:**
```json
{ "id": "uuid", "name": "Device-001", ... }
```

**Requires:** `device:write` permission.

---

### GET /devices/{id}

Get a single device by ID.

---

### PATCH /devices/{id}

Update device name, tags, or group.

```http
PATCH /devices/{id}
Authorization: Bearer <token>

{ "name": "New Name", "tags": ["updated"], "group_id": "uuid" }
```

---

### DELETE /devices/{id}

Delete a device. Returns `204 No Content`.

**Requires:** `device:delete` permission.

---

### GET /devices/{id}/status

Get real-time device status from Redis cache.

**Response 200:**
```json
{
  "device_id": "uuid",
  "status": "ONLINE",
  "battery_level": 87,
  "cpu_usage": 23.4,
  "ram_usage": 45.1,
  "last_heartbeat": "2026-02-23T10:00:00Z"
}
```

---

## Bulk Actions — `/bulk`

### POST /bulk/devices/action

Execute bulk action on multiple devices.

```http
POST /bulk/devices/action
Authorization: Bearer <token>

{
  "device_ids": ["uuid1", "uuid2"],
  "action": "assign_group",
  "params": { "group_id": "uuid" }
}
```

**Supported actions:**

| Action | Params | Description |
|--------|--------|-------------|
| `assign_group` | `group_id` | Move devices to group |
| `remove_group` | — | Remove from current group |
| `add_tag` | `tag` | Add tag to devices |
| `remove_tag` | `tag` | Remove tag from devices |
| `set_status` | `status` | Force-set status |
| `reboot` | — | Send reboot command |

**Requires:** `device:bulk_action` permission.

---

## Groups — `/groups`

### GET /groups

List all device groups in the organization.

### POST /groups

```http
POST /groups
{ "name": "Production Fleet", "description": "All production devices" }
```

### GET /groups/{id}/devices

List devices in a group (same response format as `GET /devices`).

### POST /groups/{id}/devices

Add devices to a group.

```http
{ "device_ids": ["uuid1", "uuid2"] }
```

---

## Scripts — `/scripts`

### GET /scripts

List scripts with pagination.

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Auto Login",
      "description": "Automated login script",
      "dag": { "nodes": [...], "edges": [...] },
      "created_at": "2026-02-23T10:00:00Z",
      "updated_at": "2026-02-23T10:00:00Z"
    }
  ],
  "total": 12,
  "page": 1,
  "per_page": 50
}
```

---

### POST /scripts

Create a new script with a DAG definition.

```http
POST /scripts
Authorization: Bearer <token>

{
  "name": "Auto Login",
  "description": "Tab the login button and enter credentials",
  "dag": {
    "nodes": [
      { "id": "n1", "type": "action", "data": { "cmd": "adb shell input tap 540 960" } },
      { "id": "n2", "type": "delay",  "data": { "ms": 500 } },
      { "id": "n3", "type": "action", "data": { "cmd": "adb shell input text username" } }
    ],
    "edges": [
      { "source": "n1", "target": "n2" },
      { "source": "n2", "target": "n3" }
    ]
  }
}
```

---

### POST /scripts/{id}/execute

Execute a script on a set of devices or a device group.

```http
POST /scripts/{id}/execute

{
  "device_ids": ["uuid1", "uuid2"],
  "group_id": "uuid",          // alternative to device_ids
  "wave_size": 50,             // devices per wave
  "wave_delay_seconds": 5      // delay between waves
}
```

**Response 202:**
```json
{
  "batch_id": "uuid",
  "total_devices": 100,
  "total_waves": 2,
  "status": "PENDING"
}
```

---

### GET /tasks/{batch_id}/progress

Server-Sent Events stream for execution progress.

```http
GET /tasks/{batch_id}/progress
Accept: text/event-stream
Authorization: Bearer <token>
```

Events:
```
event: task.complete
data: {"device_id":"uuid","exit_code":0,"duration_ms":1234}

event: batch.done
data: {"batch_id":"uuid","success":98,"failed":2,"total":100}
```

---

## VPN — `/vpn`

### GET /vpn/peers

List VPN peers for the organization.

**Requires:** `vpn:read` permission.

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "device_id": "uuid",
      "device_name": "Device-001",
      "vpn_ip": "10.100.0.5",
      "public_key": "base64pubkey==",
      "status": "assigned",
      "last_handshake": "2026-02-23T09:55:00Z"
    }
  ],
  "total": 142
}
```

---

### POST /vpn/peers

Provision a new VPN peer for a device.

```http
POST /vpn/peers

{ "device_id": "uuid" }
```

Allocates an IP from the pool, generates WireGuard keypair, stores encrypted config.

**Requires:** `vpn:write` permission.

---

### DELETE /vpn/peers/{id}

Revoke a VPN peer and release the IP back to the pool.

---

### GET /vpn/pool/stats

Pool utilization statistics.

**Response 200:**
```json
{
  "total": 65534,
  "allocated": 142,
  "available": 65392,
  "utilization_pct": 0.22
}
```

---

### GET /vpn/health

VPN subsystem health check.

**Response 200:**
```json
{
  "status": "ok",
  "checks": {
    "vpn_service": { "status": "ok" },
    "wg_router": { "status": "ok", "latency_ms": 4 }
  }
}
```

---

## Discovery — `/discovery`

### POST /discovery/scan

Trigger ADB device discovery on a connected PC Agent workstation.

```http
POST /discovery/scan

{ "workstation_id": "uuid" }
```

**Response 200:**
```json
{
  "devices": [
    { "serial": "emulator-5554", "state": "device", "model": "sdk_gphone64_x86_64" },
    { "serial": "192.168.1.100:5555", "state": "device", "model": "Pixel_6" }
  ],
  "workstation_id": "uuid",
  "scanned_at": "2026-02-23T10:00:00Z"
}
```

---

## Users — `/users`

**Requires:** `user:read` or `user:write` permissions.

### GET /users

List users in the organization.

### POST /users

Create a new user (invite to org).

```http
{
  "email": "newuser@example.com",
  "username": "newuser",
  "password": "TempPass123!",
  "role": "device_manager"
}
```

### PATCH /users/{id}

Update user role or status.

### DELETE /users/{id}

Remove user from organization. Returns `204 No Content`.

---

## API Keys — `/api-keys`

### GET /api-keys

List API keys for the current user.

### POST /api-keys

Create a new API key.

```http
{ "name": "CI/CD Pipeline", "expires_at": "2027-01-01T00:00:00Z" }
```

**Response 201:**
```json
{
  "id": "uuid",
  "name": "CI/CD Pipeline",
  "key": "sk_live_xxxxxxxxxxxx",   // only shown once
  "expires_at": "2027-01-01T00:00:00Z"
}
```

### DELETE /api-keys/{id}

Revoke an API key.

---

## Audit Log — `/audit`

**Requires:** `audit:read` permission.

### GET /audit

```http
GET /audit?user_id=uuid&action=device.delete&from=2026-01-01T00:00:00Z&page=1&per_page=100
```

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "actor_id": "user-uuid",
      "actor_email": "admin@example.com",
      "action": "device.delete",
      "resource_type": "device",
      "resource_id": "device-uuid",
      "remote_ip": "1.2.3.4",
      "created_at": "2026-02-23T10:00:00Z",
      "metadata": { "device_serial": "emulator-5554" }
    }
  ],
  "total": 1234
}
```

---

## Health — `/health`

### GET /health

```http
GET /health
```

No auth required.

**Response 200:**
```json
{
  "status": "ok",
  "version": "4.1.0",
  "environment": "production",
  "checks": {
    "database": {
      "status": "ok",
      "latency_ms": 2
    },
    "redis": {
      "status": "ok",
      "latency_ms": 1
    }
  }
}
```

---

## WebSocket — `/ws`

### WS /ws/device/{device_id}

Bidirectional command channel between backend and Android Agent.

**Auth:** `?token=<access_token>` query parameter.

```
wss://yourdomain.com/ws/device/uuid?token=eyJ...
```

**Message format (JSON text or binary for stream frames):**

See [Architecture — WebSocket Architecture](architecture.md#6-websocket-architecture) for full message type reference.

---

## Rate Limits

Default limits (configured in nginx):

| Endpoint group | Limit |
|---------------|-------|
| `/auth/login` | 10 req/min per IP |
| `/auth/refresh` | 60 req/min per IP |
| `/api/v1/*` | 300 req/min per JWT user |
| `/ws/*` | No limit (long-lived connections) |

Rate limit errors return `429 Too Many Requests` with header:
```
Retry-After: 60
X-RateLimit-Reset: 1740308400
```

---

## Pagination

All list endpoints support:

| Param | Default | Max | Description |
|-------|---------|-----|-------------|
| `page` | `1` | — | Page number |
| `per_page` | `50` | `200` | Items per page |

Response always includes `{ "items": [...], "total": N, "page": N, "per_page": N }`.
