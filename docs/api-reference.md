# API Reference

> **Sphere Platform** — manual REST API guide

**Base URL:** `https://yourdomain.com/api/v1`
**Interactive docs:** `https://yourdomain.com/api/docs` (Swagger UI)
**OpenAPI snapshot:** [openapi.json](openapi.json). Native FastAPI defaults to
`/openapi.json`; the public gateway must explicitly route that path. Do not infer
schema availability from `/api/docs`: the local gateway returned404 for the
root schema URL during the9October documentation review.

**9October schema reconciliation:** the committed JSON equals the installed
APIbe803773 `app.openapi()` after canonical JSON normalization:182 HTTP operations,
144 paths. Exporting the schema did not run startup hooks or execute HTTP actions.
The snapshot omits WebSocket protocols and does not prove authorization/outcomes.
[Current status and scope](operations/WORK-STATUS.md).

---

The [generated endpoint catalog](api-endpoints.md) and [OpenAPI snapshot](openapi.json)
reflect the registered HTTP contracts and are checked in CI. The Tasks section
was reconciled with application source `5fcf18a` on 2 October 2026. The Scripts
section and optional task/batch version admission condition were reconciled with
source `d2846ef` on 2 October; other Batches details retain their 7 September review.
Locations were reconciled with `db6be05` on 3 October. OTA publication was
reconciled with `facba9a` on 3 October: [metadata/receipt and Android APK checks](operations/OTA-PUBLICATION-AND-APK-CHECKS.md).
The generated snapshot includes draft validation for Script Studio and the additive
metadata-only catalog installed from `eb7a7c26` on 6 October 2026.
See the [endpoint catalog](api-endpoints.md) for current operation/path
counts. Earlier finite schema proofs retain their dated source revisions.
Other manual sections
still need component review; a listed contract does not establish runtime or
security correctness. See the [audit report](audits/2026-09-05/AUDIT-REPORT.md).

## Native capture failure diagnostics

API c1a6e79 on 4 October adds bounded `X-Screenshot-Id`, `X-Screenshot-Elapsed-Ms`,
`X-Screenshot-Failed-Phase` when applicable and `X-Screenshot-Cleanup-Confirmed`
to native capture 502/503/504. Metadata-only `native_screenshot.finished`,
`interactive_rpc.forwarded` and `interactive_rpc.finished` correlate actual
socket write, RPC outcome/progress and cleanup. A socket write does not prove
Android completion; cleanup failure does not replace the original response.
There is no automatic root-command replay. [Actual success/failure evidence](audits/2026-10-04/HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md).

## Original Android PNG

`POST /api/v1/devices/{device_id}/screenshot/native`, manual root APK capture,
requires `device:write` and tenant-owned device. No user shell/path is accepted.
The existing GET screenshot stub is not this contract. Success returns exact
native `image/png`, `no-store`, `nosniff`, attachment, plus `X-Screenshot-Device-Id`,
`Id`, `SHA256`, `Android-SHA256`, `Width`, `Height`, `Requested-At`, `Completed-At`,
`Cleanup-Confirmed` (all prefixed `X-Screenshot-`). The Android-file digest must
match assembled bytes before success; browser checks its own SHA-256 before download.
No video/canvas/re-encoding/resize or DPI metadata rewrite is used.

Bounded PNG5MiB, chunks128KiB, read deadline80s, per-RPC8s, separate cleanup;
per-organization/device lock120s. 429 concurrent capture,502 invalid/partial/hash
mismatch,503 unavailable channel/lock,504 timeout. No automatic/offline replay.
Cleanup=false can accompany a valid file. Captures are scoped private temporary
files; this endpoint does not close the N01 durable DAG artifact-upload gate.
[Contract, actual PH025/PH010 byte proof and preserved failures](audits/2026-10-04/DEVICE-CONTROL-AND-NATIVE-CAPTURE.md).

## Android UI hierarchy snapshot

`POST /api/v1/devices/{device_id}/ui-hierarchy`, no request body, requires
`device:write` and tenant-owned device. It uses existing APK root SHELL to issue
five separate fixed read/UUID-cleanup commands; it accepts no user shell/XML/XPath.
Success is `UiHierarchyResponse`: native width/height/rotation, source,
device/snapshot identity, requested/completed timestamps, cleanup flag and bounded
nodes with parent/depth/positional XPath/full returned attributes/bounds.
Successful response is `Cache-Control: no-store`. Root/UI Automator is required;
Canvas pixels and unsupported nonroot devices do not become inspectable nodes.

Runtime outcomes include409 geometry change,429 concurrent inspection,
502 failed/invalid dump or receipt,503 unavailable transport/lock,504 deadline.
The server has40s read budget; each RPC8s, separate best-effort UUID cleanup.
No background polling/automatic retry/offline replay. Cleanup failure preserves
the original error or returns a valid snapshot with cleanup flag false.
Read-only refers to UI state: a UUID-owned temporary dump is created and deleted.
Tree and video are independent, with a conservative30s UI lease from request start.
See [full contract, tests and actual local/remote Android proof](audits/2026-10-04/UI-HIERARCHY-INSPECTOR.md).

## Authentication

Authentication and authorization are route-specific. The backend uses Bearer
tokens, API keys and dedicated device/enrollment contracts; permission checks
are not fully described by OpenAPI security declarations. Verify the selected
route and its role/tenant requirements instead of applying one global exception list.

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

Refresh token is set as `HttpOnly; Secure; SameSite=None; Path=/` cookie `refresh_token`.

---

### POST /auth/refresh

```http
POST /auth/refresh
Cookie: refresh_token=<refresh_token>
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

With a valid signed Bearer token (including an expired access token), blacklists
the unexpired access token and revokes the supplied refresh token. Supply
`Cookie: refresh_token=...` or `X-Refresh-Token: ...`; cookie takes precedence.
Returns an empty `204 No Content` with the cookie-expiration header. An absent
or invalid Bearer still clears the cookie but does not revoke the SQL token.
Server-side revocation is not confirmed when Redis/PostgreSQL operations fail.
The client must also clear its in-memory/localStorage credentials and private
cached data; see [AUD-48 and remaining session work](audits/2026-09-05/AUDIT-REPORT.md).

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

Конфигурация загружается из `agent-config/environments/{env}.json` и кэшируется в Redis (TTL 300 s).

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
      "last_heartbeat": "2026-02-23T10:00:02Z",
      "connected_since": "2026-02-23T09:58:10Z",
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

`last_heartbeat` is the timestamp of the latest accepted Android pong.
`connected_since` is nullable and starts at the first accepted pong of the
current WebSocket session; it is cleared when that session is marked offline.
Older Redis status entries may omit it until the next agent heartbeat.

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

### GET /devices/{id}/stream-diagnostics

Return the latest authenticated Android stream-stage snapshot. Requires
`device:read`; the handler checks that the device belongs to the caller's
organization before reading its Redis keys.

```http
GET /devices/{id}/stream-diagnostics
Authorization: Bearer <token>
```

The response distinguishes `active_report`, `not_streaming`, `stale`, and
`unavailable`. `active_report` means the APK recently reported an active local
capture session; it does **not** certify server receipt or browser rendering.
The snapshot has a 24-hour Redis TTL and becomes stale after 75 seconds without
a fresh heartbeat. Version 1 agents omit capture/surface fields; version 2 adds
capture, render, encoder-error, throttle-drop and local WebSocket-queue counters.
No raw frames or per-frame database rows are stored. Field definitions and
operator diagnosis steps are in the
[stream observability audit](audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md).

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

Updated 2 October 2026. Paths below are relative to `/api/v1` and match the
[router](../backend/api/v1/groups/router.py). Requests require the current
organization and the listed permission; foreign group IDs return404.

| Request | Permission | Result |
|---|---|---|
| `GET /groups` | `device:read` |200, groups with total/online counts |
| `POST /groups` | `device:write` |201, confirmed group |
| `PUT /groups/{group_id}` | `device:write` |200, confirmed metadata/parent |
| `DELETE /groups/{group_id}` | `device:delete` |204; devices survive, membership is removed, children become roots |
| `GET /devices?group_id=<UUID>` | `device:read` |200, paged members using the existing device catalog |
| `POST /groups/{group_id}/devices/move` | `device:write` |200, `{ "moved": n }`; replaces each owned device's memberships with the path group |
| `GET /groups/tags` | `device:read` |200, distinct normalized tags |
| `PUT /groups/devices/{device_id}/tags` | `device:write` |204, replacement tag list |

```json
{ "name": "Production Fleet", "description": "All production devices", "parent_group_id": null }
```

For PUT, omission preserves an optional field; explicit `null` clears
`parent_group_id`, `description` or `color`. A parent must belong to the same
organization and have a valid ancestor chain. Self/descendant/corrupt ancestry
returns400; an unknown/foreign parent returns404. Validation precedes metadata
writes. Duplicate names or concurrent group writes return409. The client must
refresh and explicitly retry; it must not automatically replay an uncertain write.

Group create/update/delete share a PostgreSQL transaction fence scoped to the
organization. Other organizations proceed independently; commit/rollback releases
the fence. This protocol covers service writes, not arbitrary direct SQL writers
or optimistic version checks. [Hierarchy contract and tests](operations/GROUP-HIERARCHY.md).
Group counters use persisted ONLINE status, not live heartbeat/ONLINE+BUSY totals.

The previous `GET/POST /groups/{id}/devices` examples were unsupported routes.
`MoveDevicesRequest.group_id` is not used by this router: the path owns the target.

---

## Locations — `/locations`

Reconciled with application `db6be05` on 3 October 2026.
[Operator contract](operations/LOCATION-HIERARCHY.md) · [F26 evidence](audits/2026-10-03/LOCATION-HIERARCHY.md).

| Method | Path | Permission | Success |
|---|---|---|---|
| GET | `/locations` | `device:read` | 200, full organization array with direct counters |
| GET | `/locations/{id}` | `device:read` | 200, owned detail |
| POST | `/locations` | `device:write` | 201, created detail |
| PUT | `/locations/{id}` | `device:write` | 200, updated detail |
| DELETE | `/locations/{id}` | `device:delete` | 204; optional query `expected_updated_at` |
| POST | `/locations/{id}/devices` | `device:write` | 200, additive `assigned` count |
| DELETE | `/locations/{id}/devices` | `device:write` | 200, `removed` count |

Create/update metadata: `name`, nullable `description/color/address/latitude/
longitude/parent_location_id`. PUT preserves omitted fields; null explicitly
clears nullable fields. Name cannot be null. Coordinates are finite decimal
numbers within ±90/±180; zero is valid. Parent must be owned, accessible and
acyclic. Unknown request fields return 422. Read/create/update details include
`id/org_id/created_at/updated_at`, direct `total_devices` and `online_devices`.
Counters use persisted online status; they do not sum descendants or prove
current sockets. The response array has no pagination wrapper.

```json
{"name":"Floor","latitude":0,"longitude":0,"parent_location_id":null}
```

For conditional PUT, pass the inspected timezone-aware `updated_at` as body
`expected_updated_at`. DELETE uses the same optional condition in the query,
with normal URL encoding. A stale revision or competing tenant writer returns
409. Old clients without the condition retain compatibility but do not get
stale-draft protection. Missing/foreign target or parent returns 404;
self/descendant/corrupt ancestry returns 400; invalid schema/range/date returns
422. Rejection preserves the existing fields.

Deleting a parent removes its memberships, preserves devices and promotes
immediate children to roots; their memberships remain. The timestamp condition
covers the target row, not an immutable preview of all child/membership changes.
Membership requests use `{"device_ids":["<UUID>"]}`, 1–500 strings; historical
skip behavior for invalid/missing/foreign devices is retained.

---

## Scripts — `/scripts`

Existing version workflows were reviewed against `d2846ef` on 2 October 2026;
draft validation was added in `561d08a`. The current API/UI installation is
`eb7a7c26` (6 October 2026, 07:35 UTC), including the separate metadata catalog.
All routes require an authenticated principal and enforce organization scope.
Read operations require `script:read`, mutations `script:write`; task/batch submission
checks `script:execute` separately.
See [the operator workflow and failure contract](operations/SCRIPT-VERSIONS.md).

### POST /scripts/validate — проверка черновика

`POST /api/v1/scripts/validate`, право `script:read`, тело `{ "dag": <DAG 1.0> }`.
После обычной проверки пользователя/организации сервер нормализует DAG тем же
`DAGScript`, что create/update, проверяет уникальные ID, маршруты, достижимость и
Lua safety. Возвращает `schema_version=1`, `dag`, `dag_hash` (SHA256), `node_count`,
`action_types`, `scope=structure-routes-lua-safety`, `device_execution_verified=false`.
Ошибки DAG дают 422 с location/type/message без исходных input/context.
Проверка не создаёт сценарий, версию, task или команду Android; доступность селектора,
разрешения APK, побочные эффекты и совместимость runtime этим ответом не проверены.
Сохранение использует существующие create/update и optimistic guard
`expected_current_version_id`; 409 требует разрешения конфликта оператором.
[Аудит и этапы Studio](audits/2026-10-06/SCRIPT-STUDIO-FOUNDATION.md).

### GET /scripts/catalog — metadata-only list

`GET /api/v1/scripts/catalog`, permission `script:read`, tenant scope and
`Cache-Control: no-store`. Query parameters: `query`, `state=active|archived|all`,
`page>=1`, `per_page=1..200` (defaults: active, 1, 50). The response contains
`catalog_schema: 1`, `items`, `total`, `page`, `per_page`, `pages`; zero total gives
zero pages, and an empty offset page retains its total. Ordering is
`updated_at DESC, id ASC`; page and count use one SQL snapshot.

Each item contains script/organization IDs, name, description, archive state,
creation/update timestamps, `current_version_id`, `node_count` and `current_version`.
The version contains only ID, `script_id`, version number, lowercase 64-hex `dag_hash`
and creation time. DAG bodies, notes, author and version history are excluded.
An unpublished script has null pointer/version/count; unknown values do not become zero.
Selected published versions with missing or invalid owned metadata return 503:
`{"detail":{"code":"script_catalog_metadata_unavailable"}}`, also with no-store.
Catalog reads neither repair metadata nor compute hashes from DAGs.

The UI requests the pinned source separately using
`GET /scripts/{script_id}/versions/{version_id}` and verifies the selected receipt.
Legacy list/detail/history/CRUD responses remain compatible. Schema, tenant-specific
backfill and clean reconciliation precede enabling the new UI; an application
rollback leaves additive columns intact. See the [operator contract](operations/SCRIPT-CATALOG.md)
and [installation evidence](audits/2026-10-06/SCRIPT-CATALOG-EVIDENCE.json).
This delivery does not establish production p95, browser heap or WAN performance.

### GET /scripts

Paginated active catalog by default. Query parameters: `state=active|archived|all`,
`query`, `page` (at least 1), `per_page` (1–200, default 50). The response contains
`items`, `total`, `page`, `per_page` and `pages`. Each item contains script metadata,
`is_archived`, `current_version_id` and nested `current_version` with its immutable
DAG and SHA-256. The DAG is nested in that version, not at the script root.
Search and pagination apply to the selected archive state and organization.

### GET /scripts/{id} and immutable versions

`GET /scripts/{id}?include_dag=false` returns metadata and all version metadata
without DAG bodies. `GET /scripts/{id}/versions` lists the history.
`GET /scripts/{id}/versions/{version_id}` returns one owned immutable version,
including DAG, hash, version number, author, notes and UTC creation time.
Foreign or missing script/version IDs return 404. History metadata is not yet
paginated; large histories need a separate volume acceptance test.

### POST /scripts

Create a script and immutable v1. This minimal example uses the registered DAG
format and performs no Android actions:

```http
POST /scripts
Authorization: Bearer <token>

{
  "name": "Empty workflow",
  "description": "Finite no-action DAG example",
  "dag": {
    "version": "1.0",
    "name": "Empty workflow",
    "entry_node": "start",
    "nodes": [
      { "id": "start", "action": { "type": "start" }, "on_success": "end" },
      { "id": "end", "action": { "type": "end" } }
    ]
  }
}
```

### Update, rollback and archive

`PUT /scripts/{id}` accepts metadata and an optional DAG; a DAG update creates
a new immutable version. It also accepts `expected_current_version_id`.

`POST /scripts/{id}/versions/{version_id}/rollback` creates a **new** version
with the selected historical DAG; existing versions and tasks remain unchanged.
Opt-in body: `{"expected_current_version_id":"<current-version-uuid>"}`.
Legacy callers may omit the body; a supplied body requires the condition.

`DELETE /scripts/{id}?expected_current_version_id=<current-version-uuid>` archives
the script and returns 204 after commit. History is retained; this does not cancel
tasks. An archive restore endpoint is not registered. Archived update/rollback
returns 409.

Mutation paths hold a tenant-owned row lock through commit. A stale condition or
contested row returns 409 before mutation; foreign ownership returns 404.
Clients must refresh and reconfirm after conflict, and reconcile unknown results
instead of automatically repeating a mutation.

### Admit a task or batch against an inspected version

Both `POST /tasks` and `POST /batches` accept optional
`expected_current_version_id`. When supplied, a shared row lock protects the
current version until admission commits; stale or archived state is refused.
The accepted receipt contains `script_version_id`, which must match the inspected
version. Existing admitted tasks/batches keep their pinned version after rollback.
Callers that omit the condition preserve legacy behavior and do not receive
optimistic stale-selection protection.

### POST /scripts/{id}/execute

This route is not registered. Use [POST /batches](#post-batches) for wave
submission or [POST /tasks](#post-tasks) for one device. The previous example
with `group_id` and `wave_delay_seconds` did not describe the current API.

---

### GET /tasks/{batch_id}/progress

The registered `/tasks/{task_id}/progress` endpoint describes a single task,
not a batch SSE stream. Poll [GET /batches/{id}](#get-batchesid) for batch status;
see the [Tasks section](#tasks--tasks) for progress and live logs.

---

## VPN — `/vpn`

Contract reviewed: 2026-10-03. Canonical schemas: [OpenAPI](openapi.json).
Operator recovery and execution boundaries: [VPN control outcomes](operations/VPN-CONTROL-OUTCOMES.md).

### GET /vpn/peers

Returns an array of peers owned by the organization, not an `items/total` envelope.
Fields: `id`, nullable `device_id`, nullable `assigned_ip`, `status`, `is_active`,
`public_key`, nullable `last_handshake_at`, and `created_at`.
`is_active` requires a recent handshake under 180 seconds. It does not prove
Android command delivery or per-peer RX/TX traffic. Requires `vpn:read`.

### POST /vpn/assign

Body: `device_id` (UUID), optional `split_tunnel` (default true).
Returns `peer_id`, `device_id`, `assigned_ip`, `public_key`, `config`, and `qr_code`.
Configuration and QR content are sensitive; do not include them in logs.
The response confirms a provider assignment, not Android configuration application.
Requires `vpn:write`.

### DELETE /vpn/revoke/{device_id}

Revokes the owned peer using the durable provider lifecycle. Returns 204 only
after the lifecycle completes. A timeout/error may retain a `REVOKING` reservation
and requires reconciliation. Requires `vpn:write`.

### POST /vpn/revoke/bulk

Accepts 1–500 unique UUID `device_ids`. Returns `total`, `succeeded`, `failed`,
and per-device `results` (`device_id`, `success`, nullable `error`). Requires
`vpn:mass_operation`; a false result is not proof that provider side effects
never occurred.

### POST /vpn/rotate

Accepts 1–500 unique UUID `device_ids` and optional `reason` (1–100 characters).
Empty lists no longer mean the whole organization. Unknown fields are rejected.
All active target devices must belong to the organization before any provider IO.
Requires `vpn:mass_operation`.

Returns `total`, `success`, `failed`, `execution_confirmed: false`, and `details`:
`device_id`, nullable `old_ip/new_ip/error`, `outcome` (`configured|rejected|unknown`),
and `revoke_confirmed`. `configured` refers to the provider operation, not the
APK. An unknown result can follow a completed revoke and must not be blindly
retried. A missing assigned peer is rejected without an implicit assignment.

### POST /vpn/killswitch

Body: 1–500 unique UUID `device_ids`, **required** `action` (`enable|disable`),
and optional `method` (`vpnservice|iptables`, default `vpnservice`). Legacy
`enabled` booleans and unknown fields produce 422. The whole selection is
ownership-checked before dispatch. Requires `vpn:mass_operation`.

Returns `action`, `total`, `success`, boolean `results`, per-device `outcomes`
(`submitted|not_sent|unsupported|unknown`), and `execution_confirmed: false`.
The current legacy sender is not connected: owned requests report `unsupported`
without dispatching. `success` counts sender acceptance, not Android execution.

### GET /vpn/pool/stats

Returns `total_ips`, `allocated`, `free`, `active_tunnels`, `stale_handshakes`.
Capacity/free counts refer to the platform pool; allocated/handshake counts
refer to the caller's organization. Requires `vpn:read`.

### GET /vpn/health

The current response is a static service status (`status: ok`,
`checks.vpn_service.status: ok`). It does not probe router reachability or
publish latency. Do not use it as a transport readiness or SLA measurement.
Requires `vpn:read`; measured health coverage remains a separate open finding.

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

**Проверено 3 октября 2026, API `cc28e9b`.** Пути ниже относительны к
`/api/v1`. [Полный операторский контракт](operations/PIPELINE-DEFINITIONS.md)
и [generated OpenAPI](openapi.json) задают точные поля, defaults и bounds.

| Операция | Разрешение | Результат |
| --- | --- | --- |
| GET /pipelines | pipeline:read | Каталог: items, total, page, per_page, pages |
| POST /pipelines | pipeline:write | 201: созданное определение |
| GET /pipelines/{id} | pipeline:read | 200: полное owned определение |
| PATCH /pipelines/{id} | pipeline:write | 200: сохранённое определение |
| DELETE /pipelines/{id} | pipeline:write | 204: мягкая деактивация |
| POST /pipelines/{id}/toggle | pipeline:write | 200: explicit desired active state |
| POST /pipelines/{id}/run | pipeline:execute | 201: queued PipelineRun |
| POST /pipelines/{id}/run-batch | pipeline:execute | 201: PipelineBatch и созданные queued runs |
| GET /pipelines/runs | pipeline:read | Пагинированный журнал запусков |
| GET /pipelines/runs/{run_id} | pipeline:read | 200: состояние, context, step_logs, execution/child/cancel fields |
| POST /pipelines/runs/{run_id}/pause, /resume, /cancel | pipeline:execute | 200: сохранённое состояние управления запуском |

### Каталог и определение

GET /pipelines принимает `is_active` boolean, `tag`, `page` (от 1) и
`per_page` (1–200, default50). Глобального `search` и `status=draft` у этого
каталога нет. Определение возвращает `id`, `org_id`, `name`, `description`,
`steps`, `input_schema`, `global_timeout_ms`, `max_retries`, `version`,
`is_active`, `tags`, `created_by_id`, `created_at`, `updated_at`.

Пример POST /pipelines (только создание, не запуск):

```json
{
  "name": "Finite delay control",
  "description": "A single delay step",
  "steps": [{
    "id": "start",
    "name": "Wait one second",
    "type": "delay",
    "params": { "delay_ms": 1000 },
    "on_success": null,
    "on_failure": null,
    "timeout_ms": 10000,
    "retries": 0
  }],
  "global_timeout_ms": 30000,
  "input_schema": {},
  "max_retries": 0,
  "tags": ["control"]
}
```

Известные type: execute_script, condition, action, delay, parallel,
wait_for_event, n8n_workflow, loop, sub_pipeline. ID уникальны; переходы
ссылаются на существующие шаги или null. Циклы допускаются. Параметры handlers
не получают универсальной semantic validation только от проверки schema.

### Изменение и деактивация

PATCH отправляет только изменённые поля и optional `expected_updated_at` из
просмотренного ответа. Description:null очищает описание; другие поля с null
дают422. Steps ограничены1–100, теги 20. Version увеличивается только при
фактическом изменении steps. При неверном baseline, занятой записи или runtime
edit с nonterminal runs возвращается409 без частичного сохранения.

POST /pipelines/{id}/toggle требует query `active=true|false`; optional
`expected_updated_at` защищает прочитанный baseline. DELETE тоже принимает
optional timestamp condition и только выключает новые admissions. Уже
созданные runs не отменяются. Для существующего run нужен отдельный cancel.

### Запуски

POST /pipelines/{id}/run принимает `device_id` UUID и `input_params` object.
POST /pipelines/{id}/run-batch принимает `device_ids`, `group_id`, `device_tags`,
`input_params`, `wave_size`, `wave_delay_seconds`. 201 подтверждает созданный
intent, а не завершение Android-действия. Steps фиксируются в run snapshot.

GET /pipelines/runs принимает `pipeline_id`, `device_id`, `status`,
`active_only`, `page`, `per_page`; состояние выполнения читается по run_id.
Pause/resume/cancel возвращают новый сохранённый receipt, не разрешение на
blind replay при неизвестном результате. Input_schema пока сохраняется как
описание, без валидации входа исполнителем; глобальные max_retries пока не
реализуют повтор всей цепочки. [Ограничения и восстановление](operations/PIPELINE-DEFINITIONS.md).

Пути `/execute`, `/stop`, `/clone`, `/{id}/stats`, `/{id}/validate` и вложенные
`/{id}/runs` отсутствуют в текущем Pipeline API. Старые примеры этих операций
были планом, а не реализованным контрактом; использовать их нельзя.

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

These paths are under `/api/v1`. Verified against the batch router/schema on
7 September 2026; the API has no GET collection route or POST cancel route.

### POST /batches

Requires `script:execute`; accepts `script_id` and 1–1000 `device_ids` plus
optional `wave_size` (1–100, default 10), `wave_delay_ms` (default 5000),
`jitter_ms` (default 1000), `priority` (1–10, default 5), `name`, `webhook_url`
and `stagger_by_workstation` (default true). The service commits the batch before
launching the independent worker; returns 202 with the batch record. A failed
commit launches no worker. Crash recovery between commit and launch is still open.

Wave submission creates QUEUED task intents; it does not mean devices completed
execution. `failed` includes rejected device slots (for example missing, foreign
or already busy devices), plus failed/timed-out tasks. Final task results determine
COMPLETED/FAILED/PARTIAL when all requested slots have an outcome. A database
error aborts the current wave; prior committed waves remain and recovery is still
manual. Do not blindly replay the whole batch.

`webhook_url` is accepted/stored, but reliable batch completion delivery is not
implemented. The premature callback previously emitted after submission has
been disabled. Poll status until a durable outcome notification mechanism exists.

```json
{
  "script_id": "<script UUID>",
  "device_ids": ["<device UUID>"],
  "wave_size": 10,
  "wave_delay_ms": 5000,
  "jitter_ms": 1000
}
```

### POST /batches/broadcast

Requires `script:execute`; accepts the same wave options and `script_id`, with
no `device_ids`. Resolves online devices in the caller's organization and returns
202 with the batch record plus `online_devices`.

### GET /batches/{id}

Requires `script:read`. Returns the tenant-scoped batch record with status,
`total`, `succeeded`, `failed`, `wave_config`, timestamps and optional `notes`.
This response does not contain a per-device task list.

### DELETE /batches/{id}

Requires `script:execute`. Returns 204 after the caller commits cancellation.
Unknown/foreign batch returns 404; COMPLETED, PARTIAL, FAILED and CANCELLED
batches return 409. The server serializes cancellation with in-flight wave
admission, then locks eligible tasks and the batch before validation and queue
effects. Later waves re-read tenant/status after this transaction fence and do
not create tasks after cancellation. QUEUED/ASSIGNED tasks become CANCELLED with UTC
`finished_at`; RUNNING tasks continue under the existing batch API policy.

SQL cancellation is not proof of physical stop. ASSIGNED may already be in
transit; Redis/commit failure and durable producer recovery remain open.
Late RUNNING task results/timeouts update counters while retaining CANCELLED.
All backend workers must run the updated fence; mixed versions do not provide
this guarantee. See [AUD-43–47 and remaining work](audits/2026-09-05/AUDIT-REPORT.md).

---

## Tasks — `/tasks`

Verified against the task router/schema on 2 October 2026, source `5fcf18a`. Reads require
`script:read`; create/cancel/stop/rerun require `script:execute`. All paths below are
under `/api/v1` and apply the caller's organization boundary.

### GET /tasks

Filters: `device_id`, `script_id`, `batch_id` (UUIDs) and `status` (`queued`,
`assigned`, `running`, `completed`, `failed`, `timeout`, `cancelled`).
`page` defaults to 1; `per_page` defaults to 50 and is limited to **200** here.
Response contains `items`, `total`, `page`, `per_page`, `pages`.
Optional `search` (up to 200 characters), `sort_by` (`created_at`, `status`,
`script_name`, `priority`), `sort_dir` (`asc`, `desc`) and `active_only` are
server-side filters/order. `include_counts=true` adds status counts over the
full filtered tenant history before pagination; counts are server reports.

### POST /tasks

Accepts `script_id`, `device_id`, optional `account_id`, `priority` (1–10,
default 5) and `webhook_url`. Returns 201 with the committed task. Execution
admission validates script version/device/account ownership and current work;
creation does not acknowledge physical device execution.

### GET /tasks/{id}

Returns task identity, lifecycle timestamps, result, error and input parameters.
Related read routes are `/{id}/logs` (stored node logs), `/{id}/progress`
(Redis progress), `/{id}/live-logs` (Redis node entries) and `/{id}/screenshots`
(a structured manifest described below). A Redis progress snapshot does not
prove current physical execution; stored result fields retain their reported scope.

### POST /tasks/{id}/rerun

No request body is needed. For a terminal owned task, returns 201 with a new
independent queued task using its recorded `script_version_id`, `device_id`,
priority, timeout and deep-copied input parameters. Active tasks, unknown legacy
versions and conflicting active work return 409. Script/version/device and any
explicit account context are revalidated against the caller's organization.

Old batch/wave membership, results and lifecycle timestamps are not copied.
This does not restore external Android/account state or confirm execution.
The Sphere web client disables automatic mutation retry after an uncertain response. Reconcile
the new task before making another explicit request; a later request after its
completion can create another execution. [Detailed contract and evidence](audits/2026-10-02/TASK-ARTIFACTS-AND-RERUN.md).

### GET /tasks/{id}/screenshots

Returns `{ "task_id": "uuid", "screenshots": [...] }`. Each deduplicated entry
has `key`, an authenticated relative content `url` or null, and
`unavailable_reason` or null. Unsafe/foreign reported keys have no URL.
This replaces the former string-array response; external consumers must adapt.
An empty manifest means no recorded server keys, not that Android has no image.

### GET /tasks/{id}/screenshots/content?key=...

Rechecks task ownership, task/device namespace and key membership in the stored
result before reading private storage. Returns JPEG/PNG bytes, maximum 5 MiB,
with `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`.
It does not redirect clients to MinIO or expose storage credentials.

Absent tasks/keys/objects return 404; invalid raster content returns 422;
unconfigured or unavailable storage returns 503. Configure the optional
[server storage read account](configuration.md#private-task-screenshot-reads).
Pilot reads remain disabled. Android DAG screenshot upload is still open (N01):
its local file path is not a stored object key.

### DELETE /tasks/{id}

Accepts cancellation of QUEUED/ASSIGNED tasks; returns 204 after the SQL intent
commit. QUEUED can become CANCELLED locally; ASSIGNED remains active until a
terminal device result. RUNNING or terminal states return 409; unknown/foreign
IDs return 404. The row is locked/refreshed before validation. Do not infer a
physical stop from the empty HTTP response.

### POST /tasks/{id}/stop

Accepts QUEUED/ASSIGNED/RUNNING. QUEUED cancellation returns 200 with
`status: stopped`; ASSIGNED/RUNNING returns 202 with `status: cancelling` after
persisting the cancellation request. Both include `task_id`; terminal source
states return 409. Delivery is retried by the existing durable dispatcher.
ASSIGNED/RUNNING finish only after a terminal DAG result, not a control ACK.
The control has a distinct command ID and explicit task target; see the
[control contract](security/task-control-protocol.md).

The router has no POST `/{id}/cancel` or `/{id}/retry` endpoint. Submitting a
new task or using `/{id}/rerun` is new execution and requires reconciling any
earlier unknown outcome.

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

Pagination is endpoint-specific. Check each route; for example, Tasks limits
`per_page` to 200. The following legacy defaults are not a universal contract:

| Param | Default | Max | Description |
|-------|---------|-----|-------------|
| `page` | `1` | — | Page number |
| `per_page` | `50` | `5000` | Items per page |

Several paginated endpoints include `{ "items": [...], "total": N, "page": N, "per_page": N }`; verify the response schema for the selected route.

> **v4.6.0:** `per_page` max увеличен с 200 до 5 000 для поддержки массовых
> операций и нагрузочных тестов. Рекомендуется использовать значения ≤ 200
> для стандартных UI-запросов.


## Расследование журнала аудита — 2 октября2026

`GET /api/v1/audit/logs` и `GET /api/v1/audit/logs/export` используют одни tenant-scoped filters: status/action/user_id/resource_type/q/from/to. Доступ `audit:read`, aware timestamps, literal search и validated bounds. CSV до5000 scalar rows; `X-Audit-Truncated` обозначает неполную выгрузку. [Полный контракт, поля и ограничения](operations/AUDIT-INVESTIGATION.md) · [Finite installed evidence](audits/2026-10-02/AUDIT-INVESTIGATION.md). Generated [OpenAPI](openapi.json) содержит параметры и typed audit page.
