# API Reference

> **Sphere Platform v4.7** — REST API

**Base URL:** `https://yourdomain.com/api/v1`
**Interactive docs:** `https://yourdomain.com/api/v1/docs` (Swagger UI)
**OpenAPI spec:** `https://yourdomain.com/api/v1/openapi.json`

---

## Authentication

All endpoints (except `/auth/login`, `/health`, and `/config/agent`) require a Bearer token or API Key.

```http
# JWT Bearer token
Authorization: Bearer <access_token>

# API Key (приоритет над JWT при наличии обоих)
X-API-Key: sphr_<env>_<64hex>
```

Tokens are obtained via the login endpoint and refreshed via `/auth/refresh`.
API keys are created via `POST /api-keys` and have the format `sphr_{env}_{64hex}` (256-bit entropy).
При одновременной передаче Bearer JWT и X-API-Key — API-ключ имеет приоритет.

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
| `per_page` | int | Items per page (default: 50, max: 5000) |

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

### POST /devices/{id}/reboot

> Добавлено в v4.4.0

Отправка команды перезагрузки устройства через WebSocket Command Manager.

```http
POST /devices/{id}/reboot
Authorization: Bearer <token>
```

**Response 200:**
```json
{ "status": "rebooting", "device_id": "uuid" }
```

**Ошибки:**
- `404` — устройство не найдено
- `503` — агент оффлайн (нет WS-соединения)

Timeout-fallback: устройство может перезагрузиться до ACK (3с grace period).

---

### POST /devices/{id}/shell

> Добавлено в v4.4.0

Выполнение shell-команды на устройстве через WebSocket.

```http
POST /devices/{id}/shell
Authorization: Bearer <token>

{ "command": "adb shell getprop ro.build.display.id" }
```

**Response 200:**
```json
{
  "exit_code": 0,
  "stdout": "UP1A.231005.007",
  "stderr": ""
}
```

**Requires:** `device:command` permission.

---

### POST /devices/{id}/logcat

> Добавлено в v4.4.0

Запрос на сбор logcat с устройства (UPLOAD_LOGCAT команда).

```http
POST /devices/{id}/logcat
Authorization: Bearer <token>

{ "lines": 1000, "filter": "SphereAgent" }
```

**Response 202:**
```json
{ "status": "collecting", "device_id": "uuid" }
```

Логи загружаются агентом и доступны через `GET /logs/{device_id}`.

---

### GET /devices/{id}/screenshot

> Добавлено в v4.4.0

Снятие скриншота устройства.

```http
GET /devices/{id}/screenshot
Authorization: Bearer <token>
```

**Response 200:**
```json
{
  "screenshot_url": "https://storage.example.com/screenshots/uuid.png",
  "timestamp": "2026-03-04T10:00:00Z"
}
```

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
  "version": "4.2.0",
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

## Pipelines — `/pipelines`

> Добавлено в v4.2.0 (TZ-12)

Пайплайны объединяют скрипты, условия, задержки и HTTP-вызовы в управляемые
цепочки с персистенцией состояния и возможностью вложенного запуска.

**Требуемые разрешения:** `pipeline:read`, `pipeline:write`, `pipeline:execute`.

### GET /pipelines

Список пайплайнов организации с пагинацией.

```http
GET /pipelines?status=active&page=1&per_page=50
Authorization: Bearer <token>
```

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `status` | `draft\|active\|archived` | Фильтр по статусу |
| `search` | string | Поиск по имени |
| `page` | int | Номер страницы (default: 1) |
| `per_page` | int | Элементов на странице (default: 50) |

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Onboarding Pipeline",
      "description": "Автоматическая настройка устройства",
      "status": "active",
      "version": 3,
      "steps": [...],
      "created_at": "2026-02-28T10:00:00Z",
      "updated_at": "2026-02-28T12:00:00Z"
    }
  ],
  "total": 8,
  "page": 1,
  "per_page": 50
}
```

---

### POST /pipelines

Создание нового пайплайна.

```http
POST /pipelines
Authorization: Bearer <token>

{
  "name": "Onboarding Pipeline",
  "description": "Автоматическая настройка нового устройства",
  "steps": [
    {
      "id": "s1",
      "type": "run_script",
      "config": { "script_id": "uuid", "timeout_seconds": 300 }
    },
    {
      "id": "s2",
      "type": "condition",
      "config": { "expression": "steps.s1.exit_code == 0", "on_true": "s3", "on_false": "s5" }
    },
    {
      "id": "s3",
      "type": "delay",
      "config": { "seconds": 10 }
    },
    {
      "id": "s4",
      "type": "http_request",
      "config": { "method": "POST", "url": "https://hooks.example.com/done", "body": {} }
    },
    {
      "id": "s5",
      "type": "notify",
      "config": { "channel": "webhook", "url": "https://hooks.example.com/fail" }
    }
  ]
}
```

**Response 201:**
```json
{ "id": "uuid", "name": "Onboarding Pipeline", "status": "draft", "version": 1, ... }
```

**Requires:** `pipeline:write`

---

### GET /pipelines/{id}

Получение пайплайна по ID.

---

### PATCH /pipelines/{id}

Обновление пайплайна. Автоматически инкрементирует `version`.

```http
PATCH /pipelines/{id}
{ "name": "Updated Name", "steps": [...] }
```

**Requires:** `pipeline:write`

---

### DELETE /pipelines/{id}

Удаление пайплайна. Returns `204 No Content`.

**Requires:** `pipeline:write`

---

### POST /pipelines/{id}/execute

Запуск пайплайна на устройствах.

```http
POST /pipelines/{id}/execute
Authorization: Bearer <token>

{
  "device_ids": ["uuid1", "uuid2"],
  "group_id": "uuid",
  "variables": { "env": "staging" }
}
```

**Response 202:**
```json
{
  "run_id": "uuid",
  "pipeline_id": "uuid",
  "status": "running",
  "total_devices": 2,
  "started_at": "2026-02-28T10:00:00Z"
}
```

**Requires:** `pipeline:execute`

---

### POST /pipelines/{id}/stop

Принудительная остановка выполнения пайплайна.

---

### POST /pipelines/{id}/clone

Клонирование пайплайна (создаёт копию со всеми шагами).

**Response 201:**
```json
{ "id": "new-uuid", "name": "Onboarding Pipeline (копия)", "status": "draft", "version": 1 }
```

---

### GET /pipelines/{id}/runs

История запусков пайплайна.

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "pipeline_id": "uuid",
      "status": "completed",
      "total_devices": 50,
      "success_count": 48,
      "fail_count": 2,
      "started_at": "2026-02-28T10:00:00Z",
      "finished_at": "2026-02-28T10:05:00Z",
      "duration_ms": 300000
    }
  ],
  "total": 12
}
```

---

### GET /pipelines/{id}/runs/{run_id}

Детали конкретного запуска с пошаговыми результатами.

---

### GET /pipelines/{id}/stats

Статистика запусков пайплайна (success rate, avg duration).

**Response 200:**
```json
{
  "total_runs": 45,
  "success_rate": 0.96,
  "avg_duration_ms": 180000,
  "last_run_at": "2026-02-28T10:05:00Z"
}
```

---

### POST /pipelines/{id}/validate

Валидация конфигурации пайплайна без запуска.

**Response 200:**
```json
{ "valid": true, "warnings": [] }
```

**Response 422:**
```json
{ "valid": false, "errors": ["Step s3 references non-existent step s99"] }
```

---

### Типы шагов (Step Types)

| Type | Config | Description |
|------|--------|-------------|
| `run_script` | `script_id`, `timeout_seconds` | Запуск DAG-скрипта на устройстве |
| `run_pipeline` | `pipeline_id` | Вложенный запуск другого пайплайна |
| `http_request` | `method`, `url`, `headers`, `body` | HTTP-вызов внешнего API |
| `condition` | `expression`, `on_true`, `on_false` | Условная логика (if/else) |
| `delay` | `seconds` | Задержка между шагами |
| `parallel` | `steps[]` | Параллельное исполнение подшагов |
| `set_variable` | `key`, `value` | Установка переменной контекста |
| `notify` | `channel`, `url`, `message` | Отправка уведомления (webhook/email) |
| `approval` | `approvers[]`, `timeout_hours` | Ожидание ручного подтверждения |

---

## Schedules — `/schedules`

> Добавлено в v4.2.0 (TZ-12)

Cron-планировщик для автоматического запуска пайплайнов по расписанию.
Поддерживает стандартные cron-выражения, таймзоны и политики конфликтов.

**Требуемые разрешения:** `schedule:read`, `schedule:write`.

### GET /schedules

Список расписаний организации.

```http
GET /schedules?enabled=true&page=1&per_page=50
Authorization: Bearer <token>
```

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Nightly Cleanup",
      "pipeline_id": "uuid",
      "cron_expression": "0 3 * * *",
      "timezone": "Europe/Moscow",
      "enabled": true,
      "conflict_policy": "skip",
      "next_run_at": "2026-03-01T03:00:00+03:00",
      "last_run_at": "2026-02-28T03:00:00+03:00"
    }
  ],
  "total": 5
}
```

---

### POST /schedules

Создание расписания.

```http
POST /schedules
Authorization: Bearer <token>

{
  "name": "Nightly Cleanup",
  "pipeline_id": "uuid",
  "cron_expression": "0 3 * * *",
  "timezone": "Europe/Moscow",
  "conflict_policy": "skip",
  "variables": { "env": "production" },
  "device_ids": ["uuid1"],
  "group_id": "uuid"
}
```

**Conflict policies:**

| Policy | Описание |
|--------|----------|
| `skip` | Пропустить запуск, если предыдущий ещё выполняется |
| `queue` | Поставить в очередь и запустить после завершения текущего |

**Response 201:**
```json
{ "id": "uuid", "name": "Nightly Cleanup", "enabled": true, ... }
```

**Requires:** `schedule:write`

---

### GET /schedules/{id}

Получение расписания по ID.

---

### PATCH /schedules/{id}

Обновление расписания (cron, timezone, pipeline, conflict_policy).

**Requires:** `schedule:write`

---

### DELETE /schedules/{id}

Удаление расписания. Returns `204 No Content`.

---

### POST /schedules/{id}/toggle

Включение/отключение расписания.

```http
POST /schedules/{id}/toggle
{ "enabled": false }
```

---

### GET /schedules/{id}/executions

История выполнений расписания.

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "schedule_id": "uuid",
      "pipeline_run_id": "uuid",
      "status": "completed",
      "triggered_at": "2026-02-28T03:00:00Z",
      "finished_at": "2026-02-28T03:05:00Z"
    }
  ],
  "total": 30
}
```

---

### POST /schedules/{id}/dry-run

Предварительный расчёт следующих N запусков без реального выполнения.

```http
POST /schedules/{id}/dry-run
{ "count": 5 }
```

**Response 200:**
```json
{
  "next_runs": [
    "2026-03-01T03:00:00+03:00",
    "2026-03-02T03:00:00+03:00",
    "2026-03-03T03:00:00+03:00",
    "2026-03-04T03:00:00+03:00",
    "2026-03-05T03:00:00+03:00"
  ]
}
```

---

## Game Accounts — `/game-accounts`

### GET /game-accounts

List game accounts with filtering and pagination.

| Param | Type | Description |
|-------|------|-------------|
| `game` | string | Filter by game name |
| `status` | string | Filter by status (`active`, `banned`, `idle`) |
| `device_id` | uuid | Filter by assigned device |
| `page` | int | Page number |
| `per_page` | int | Items per page |

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "nickname": "string",
      "game": "string",
      "server": "string",
      "status": "active",
      "device_id": "uuid",
      "created_at": "datetime",
      "updated_at": "datetime"
    }
  ],
  "total": 100,
  "page": 1,
  "per_page": 50
}
```

### POST /game-accounts

Create a new game account. If `nickname` is omitted, a random one is generated.

### GET /game-accounts/{id}

Get game account details.

### PUT /game-accounts/{id}

Update game account fields.

### DELETE /game-accounts/{id}

Delete a game account.

---

## Event Triggers — `/event-triggers`

### GET /event-triggers

List configured event triggers.

| Param | Type | Description |
|-------|------|-------------|
| `event_type` | string | Filter by event type |
| `enabled` | bool | Filter by enabled status |
| `page` | int | Page number |
| `per_page` | int | Items per page |

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "string",
      "event_type": "string",
      "condition": "object",
      "action": "object",
      "enabled": true,
      "created_at": "datetime"
    }
  ],
  "total": 10,
  "page": 1,
  "per_page": 50
}
```

### POST /event-triggers

Create a new event trigger rule.

### GET /event-triggers/{id}

Get trigger details.

### PUT /event-triggers/{id}

Update trigger configuration.

### DELETE /event-triggers/{id}

Delete a trigger.

### POST /event-triggers/{id}/toggle

Enable or disable a trigger.

---

## Pipeline Settings — `/pipeline-settings`

### GET /pipeline-settings

List pipeline settings.

| Param | Type | Description |
|-------|------|-------------|
| `pipeline_id` | uuid | Filter by pipeline |

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "pipeline_id": "uuid",
      "key": "string",
      "value": "any",
      "updated_at": "datetime"
    }
  ],
  "total": 5,
  "page": 1,
  "per_page": 50
}
```

### POST /pipeline-settings

Create or update a pipeline setting.

### DELETE /pipeline-settings/{id}

Delete a pipeline setting.

---

## Account Sessions — `/account-sessions`

### GET /account-sessions

List active account sessions.

| Param | Type | Description |
|-------|------|-------------|
| `account_id` | uuid | Filter by game account |
| `device_id` | uuid | Filter by device |
| `status` | string | Filter by status (`active`, `ended`, `error`) |
| `page` | int | Page number |
| `per_page` | int | Items per page |

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "account_id": "uuid",
      "device_id": "uuid",
      "started_at": "datetime",
      "ended_at": "datetime|null",
      "status": "active",
      "metadata": "object"
    }
  ],
  "total": 50,
  "page": 1,
  "per_page": 50
}
```

### POST /account-sessions

Start a new account session.

### GET /account-sessions/{id}

Get session details.

### PUT /account-sessions/{id}/end

End an active session.

---

## Device Events — `/device-events`

### GET /device-events

List device lifecycle events.

| Param | Type | Description |
|-------|------|-------------|
| `device_id` | uuid | Filter by device |
| `event_type` | string | Filter by event type (`connect`, `disconnect`, `error`, `command`, `heartbeat`) |
| `since` | datetime | Events after this timestamp |
| `until` | datetime | Events before this timestamp |
| `page` | int | Page number |
| `per_page` | int | Items per page |

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "device_id": "uuid",
      "event_type": "string",
      "payload": "object",
      "created_at": "datetime"
    }
  ],
  "total": 1000,
  "page": 1,
  "per_page": 50
}
```

### GET /device-events/{id}

Get event details.

---

## Batches — `/batches`

### GET /batches

List batch operations.

| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter by batch status (`pending`, `running`, `completed`, `failed`) |
| `page` | int | Page number |
| `per_page` | int | Items per page |

### POST /batches

Create a new batch operation targeting multiple devices.

```json
{
  "device_ids": ["uuid", "uuid"],
  "action": "execute_script",
  "params": {
    "script_id": "uuid"
  }
}
```

### GET /batches/{id}

Get batch operation status and per-device results.

### POST /batches/{id}/cancel

Cancel a running batch.

---

## Tasks — `/tasks`

### GET /tasks

List tasks with filtering and pagination.

| Param | Type | Description |
|-------|------|-------------|
| `device_id` | uuid | Filter by device |
| `status` | string | Filter by status (`pending`, `running`, `completed`, `failed`, `cancelled`) |
| `type` | string | Filter by task type |
| `page` | int | Page number |
| `per_page` | int | Items per page |

### GET /tasks/{id}

Get task details including execution logs.

### POST /tasks/{id}/cancel

Cancel a pending or running task.

### POST /tasks/{id}/retry

Retry a failed task.

---

## Streaming — `/streaming`

### POST /streaming/start

Start a streaming session for a device.

### POST /streaming/stop

Stop an active streaming session.

### GET /streaming/sessions

List active streaming sessions.

---

## Monitoring — `/monitoring`

### GET /monitoring/health

System health check endpoint.

### GET /monitoring/metrics

Prometheus-compatible metrics endpoint.

### GET /monitoring/pool-stats

Database and Redis connection pool statistics.

---

## Pagination

All list endpoints support:

| Param | Default | Max | Description |
|-------|---------|-----|-------------|
| `page` | `1` | — | Page number |
| `per_page` | `50` | `5000` | Items per page |

Response always includes `{ "items": [...], "total": N, "page": N, "per_page": N }`.

> **v4.6.0:** `per_page` max увеличен с 200 до 5 000 для поддержки массовых
> операций и нагрузочных тестов. Рекомендуется использовать значения ≤ 200
> для стандартных UI-запросов.
