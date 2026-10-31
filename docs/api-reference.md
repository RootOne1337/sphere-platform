# API Reference

> **Sphere Platform** — manual REST API guide

**Base URL:** `https://yourdomain.com/api/v1`
**Interactive docs:** `https://yourdomain.com/api/docs` (Swagger UI)
**OpenAPI snapshot:** [openapi.json](openapi.json). Native FastAPI defaults to
`/openapi.json`; the public gateway must explicitly route that path. Do not infer
schema availability from `/api/docs`: the local gateway returned404 for the
root schema URL during the9October documentation review.

**Historical schema observation, 12 October 2026:** UI/API `ed9d54d0` served 3015 and Tuna at that time.
The then-running API schema matched the then-committed JSON: 185 HTTP operations,
147 paths. This does not identify the current installation or current snapshot.
That snapshot included authenticated exact-channel APK download at
`GET /api/v1/updates/downloads/latest`; `platform=android-canary&flavor=dev`
is the default. The response is a binary APK with private/no-store caching,
download filename and Range support. Operator `device:read` is required;
the agent artifact endpoint retains its separate authentication.
[Installed proof and limits](audits/2026-10-12/APK-DOWNLOAD-AND-LOGIN.md).

**Historical 9 October schema reconciliation:** the then-committed JSON equalled the installed
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
security correctness. See the [API reconciliation register](audits/2026-11-01/API-REFERENCE-RECONCILIATION.md)
for reviewed routes and remaining coverage, and the [audit report](audits/2026-09-05/AUDIT-REPORT.md).

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
API keys are created via `POST /auth/api-keys` and have the format `sphr_{env}_{64hex}` (256-bit entropy).
При использовании общего resolver API-ключ имеет приоритет; отдельные маршруты могут использовать другую зависимость или только Bearer.

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

{ "email": "admin@example.com", "password": "example-password" }
```

If MFA is disabled, the response contains `access_token`, `token_type`, `expires_in`,
`refresh_token` and `user`. If MFA is enabled, it returns `mfa_required: true` and
`state_token` without an access token. Complete that challenge with:

```http
POST /auth/login/mfa
Content-Type: application/json

{ "state_token": "<state-token>", "code": "123456" }
```

Successful login also sets the HttpOnly `refresh_token` cookie at path `/`. Its
transport policy is `Secure; SameSite=None` when `COOKIE_SECURE` is set or the
request scheme is HTTPS; otherwise it is non-Secure with `SameSite=Lax`. The
refresh token is also returned in the response body for fallback transport. Treat
both the cookie and response as credentials. See [session boundaries](security/frontend-sessions.md).

---

### POST /auth/refresh

```http
POST /auth/refresh
Cookie: refresh_token=<refresh-token>
```

The backend rotates the refresh token and returns the same token response shape
as a successful login. It accepts the cookie first, then `X-Refresh-Token`, then
`{"refresh_token": "..."}` in the JSON body. A lost response does not prove that
rotation did not occur; see [session boundaries](security/frontend-sessions.md).

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

Requires a Bearer-authenticated user. Returns `secret` and `qr_code` (base64 PNG);
these are sensitive. The pending setup expires after five minutes. Setup alone
does not enable MFA.

### POST /auth/mfa/verify-setup

```http
POST /auth/mfa/verify-setup
Authorization: Bearer <token>
Content-Type: application/json

{ "code": "123456" }
```

Success returns `200 {"message": "MFA enabled successfully"}`. `DELETE /auth/mfa`
disables MFA for the authenticated user and returns `204` in the handler; the
checked-in OpenAPI declaration lists `200`.

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
  "role": "org_admin",
  "org_id": "uuid",
  "is_active": true,
  "mfa_enabled": false,
  "last_login_at": null,
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

### GET /auth/capabilities

Bearer-authenticated `GET /auth/capabilities` returns `user_id`, `org_id`, `role`
and sorted `permissions` from the current database-backed user role, with
`Cache-Control: no-store`. It is a snapshot for this session, not an authorization
grant for a later operation; the target route performs its own check.

---

## Agent Config — `/config`

> Добавлено в v4.1.0 (TZ-12)

### GET /config/agent

This endpoint may return base configuration without an API key. An optional
`X-API-Key` (enrollment or device key) is validated and may enrich the response
with organization-scoped data; it does not use a JWT to infer the organization.
An invalid supplied key returns 401. The handler accepts `X-Agent-Fingerprint` but
does not use it to select or authorize this response. **Source exposure boundary:**
when file configuration contains `enrollment_api_key`, the handler includes that
credential in its base response even without an API key. Treat the response as
sensitive and restrict access at the deployment boundary. Whether any installed
environment is externally reachable or contains such a key is not established here.
The response uses fields such as `server_url`, `ws_path`, `config_version`,
`environment`, `config_poll_interval_seconds`, `features`, `enrollment_allowed`
and optional `enrollment_api_key` and `org_id`. The schema describes `min_agent_version` as
forcing OTA, but a source search for that field found no such enforcement consumer;
the field is not proof of forced update. Enrollment credentials are
sensitive and must not be published. Source of truth: [router](../backend/api/v1/config/router.py)
and [schema](../backend/schemas/agent_config.py).

---

## Device Registration — `/devices/register`

> Добавлено в v4.1.0 (TZ-12)

### POST /devices/register

Requires an active enrollment API key with `device:register` in `X-API-Key`.
Registration is scoped to the key's organization and accounts for both the
fingerprint and optional instance binding; copying an APK fingerprint to a new
VM does not necessarily identify the same device.

```http
POST /devices/register
X-API-Key: <enrollment-key>
Content-Type: application/json

{
  "fingerprint": "a1b2c3d4e5f6",
  "model": "sdk_gphone64_x86_64",
  "android_version": "13",
  "device_type": "ldplayer"
}
```

The route returns `201` with `device_id`, `name`, `access_token`, opaque
`refresh_token`, `expires_in`, `server_url`, `is_new` and optional binding and
creation fields. `is_new` distinguishes a new record from re-enrollment. Do not
publish either token. After a lost response, reconcile registration/device state
before retrying; the response alone is not proof that the agent is connected. See the [registration schema](../backend/schemas/device_register.py)
and [credential bootstrap](security/device-credential-bootstrap.md).

---

## Devices — `/devices`

### GET /devices

Requires `device:read`. Query parameters are `status` (legacy stored status),
`group_id`, `location_id`, `type`, `search`, `live_status`, `page` and `per_page`
(maximum 5000). Unrecognized legacy `status` values are ignored by the service;
they do not filter the result by status. There is no `tag` query parameter on this
route. For the distinction between stored and live state see [device catalog](operations/DEVICE-CATALOG.md).

`200` is a `DeviceListResponse` with `items`, `total`, `page`, `per_page`, `pages`,
and coverage fields `scope_total`, `status_counts`, `presence_available`, `as_of`.
Item fields include `id`, `name`, `status`, `is_active`, `group_ids`, `location_ids`,
`tags`, `last_heartbeat` and `connected_since`; consult the [schema](openapi.json)
for nullable fields. Presence availability and timestamp do not prove device action.

`connected_since` is nullable and starts at the first accepted pong of the current
WebSocket session; it is cleared when that session is marked offline.

---

### GET /devices/me

Requires `X-API-Key`; the optional `X-Device-Id` selects the device within the
key's organization. Despite the handler docstring promising 404, the source
returns `200` with `null` when no device is resolved; its broad exception handler
also covers lookup failures, so `null` does not prove the device is absent.
This is source behavior, not a measurement of an installed deployment.

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

Get a tenant-owned device by ID; requires `device:read`.

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

### PUT /devices/{id}

Requires `device:write`. Update device name, tags, or group. A non-null `group_id`
replaces current group memberships; omitted or null `group_id` leaves them unchanged.

```http
PUT /devices/{id}
Authorization: Bearer <token>

{ "name": "New Name", "tags": ["updated"], "group_id": "uuid" }
```

---

### DELETE /devices/{id}

Retire the device from active inventory and return `204 No Content`. The handler
preserves the record and referenced history, sets offline and clears device refresh
credentials; this response does not prove that an already-running physical action
stopped. Tenant-owned detail retrieval may still find the inactive record.

**Requires:** `device:delete` permission.

---

### POST /devices/{id}/reboot

> Добавлено в v4.4.0

Требует `device:write`; отправляет команду через WebSocket Command Manager.

```http
POST /devices/{id}/reboot
Authorization: Bearer <token>
```

**Response 200:**
```json
{ "status": "reboot_initiated", "device_id": "uuid" }
```

The shown `reboot_initiated` response indicates an accepted agent receipt, not
proof that reboot has completed. The handler can also return HTTP 200 with an
`error` object when the agent reports failure; inspect the body.

**Ошибки:**
- `404` — устройство не найдено
- `503` — недоступен канал или транспорт команды; это не всегда доказательство, что устройство офлайн

A `504` without agent acknowledgement reports an unknown outcome; inspect the device before retrying.

---

### POST /devices/{id}/shell

Requires `device:write` and an owned device. The live-only command accepts a
`command` string (1–4096 characters), executes through the device agent, and returns
`{"output": "..."}` for a completed result or `{"error": "..."}` for an agent
failure. It is not a host-side `adb shell` invocation. A transport timeout does not
prove that the command had no effect; inspect device state before retrying.

### POST /devices/{id}/logcat

Requires `device:read`. The request accepts `lines` (1–10000, default 500) and
`mode` (default `sphere`). The default requests Sphere logs; the returned object
contains `logcat` on success or `error` on reported agent failure. It is a live
request, not a `202` collection receipt.

### POST /devices/{id}/connect

Requires `device:write` and an assigned workstation. This is a cache-writing
stub returning 204; it is not confirmation that ADB connected.

### GET /devices/{id}/screenshot

Requires `device:read`. This legacy endpoint is a stub that records a request in the cache and returns
`status: screenshot_requested`; it does not return an image URL. For the manual
original PNG contract see [Original Android PNG](#original-android-png).

---

### GET /devices/{id}/status

Requires `device:read`. Returns `DeviceStatusResponse` combining device data with
`live` Redis status; this is not the older flat `device_id`/`ram_usage` example.
A cache read is an observation, not proof that a command completed.

---

### Device observation and agent refresh

- `POST /devices/status/bulk` requires `device:read`, accepts 1–500 string
  `device_ids`, and filters them to owned IDs. `GET /devices/status/fleet` uses
  the active owned inventory. Both return counters from the status cache. In these
  aggregates `online` and `busy` are separate; missing cache entries contribute
  to `offline`. A missing Redis client can therefore produce an offline count
  without confirming devices are offline. This differs from `GET /devices`, whose
  online count includes busy and whose unavailable presence is reported as unknown.
- `POST /devices/{id}/viewers` requires `device:read` and a 32-character lowercase
  hexadecimal session ID plus optional boolean `active`. It updates a card-viewer
  lease and reports availability/counts; this is not proof of stream playback.
- `GET /devices/{id}/stream-sessions` and `/direct-probe-capabilities` require
  `stream:read` and an owned active device. History may return 503 if unavailable;
  capability admission is not proof of relay reachability or device acceptance.
- `POST /devices/refresh` uses the device `refresh_token` cookie, not the user
  refresh endpoint, and returns the rotated device credentials in the response
  body. It accepts an optional `X-Refresh-Request-Id` UUID. Persist the request ID
  before sending: source allows recovery of one unconsumed successor
  with the same original token and ID; a missing/different ID or later rotation
  cannot recover that prior reply. Keep both token and response secret. See
  [device credential bootstrap](security/device-credential-bootstrap.md).

---

## Bulk Actions — `/devices/bulk`

`POST /devices/bulk/action` requires `device:write` and accepts 1–500 `device_ids`,
`action` and optional `params`. The schema permits `reboot`, `connect_adb`,
`disconnect_adb`, `set_group`, `set_tags` and `send_command`; `set_group` requires
`group_id`, and `send_command` requires `command_type`. The response gives
`total`, `succeeded`, `failed` and per-device `results`. Inspect each result.
Per-item failures do not necessarily mean no side effect: a lost reboot receipt
leaves the result unknown. Reboot success means an agent receipt, not a finished
reboot. `connect_adb`,
`disconnect_adb` and `send_command` are cache-writing stubs, not proof of device
execution. `DELETE /devices/bulk` requires `device:delete` and removes records
from the active catalog while preserving history. See [schema](../backend/schemas/bulk.py)
and [service](../backend/services/bulk_service.py). `DELETE /devices/bulk` returns
`{ "deleted": N }` for active owned records retired; malformed, foreign and
already-inactive IDs are not counted. A count alone does not stop physical actions.

---

## Groups — `/groups`

Updated 2 October 2026. Paths below are relative to `/api/v1` and match the
[router](../backend/api/v1/groups/router.py). Requests use the current
organization and listed permission. Group mutations reject a foreign target with
404; the device-list group filter does not separately establish group existence.

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
A move request contains 1–500 `device_ids`; the tag replacement body is
`{"tags":["production"]}` and accepts at most 20 entries, normalized by the schema.

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
draft validation was added in `561d08a`. In the recorded 6 October 2026, 07:35 UTC
observation, API/UI `eb7a7c26` included the separate metadata catalog. This is a
historical installation; consult [current state](operations/CURRENT-STATE.md) and
verify the deployment separately.
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
without DAG bodies. `GET /scripts/{id}/versions` lists the history without DAG bodies by default;
`?include_dag=true` includes them.
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

### Unregistered script execution route

This route is not registered. Use [POST /batches](#post-batches) for wave
submission or [POST /tasks](#post-tasks) for one device. The previous example
with `group_id` and `wave_delay_seconds` did not describe the current API.

---

### Task progress is not batch progress

The registered `/tasks/{task_id}/progress` endpoint describes a single task,
not a batch SSE stream. Poll [GET /batches/{id}](#get-batchesid) for batch status;
see the [Tasks section](#tasks--tasks) for progress and live logs.

---

## VPN — `/vpn`

Contract reviewed: 2026-10-03. Canonical schemas: [OpenAPI](openapi.json).
Operator recovery and execution boundaries: [VPN control outcomes](operations/VPN-CONTROL-OUTCOMES.md).
Profile preflight/import/revision routes and their separate outcomes are described in
[VPN profiles](operations/VPN-PROFILES.md); listing a route does not prove device application.
The `/vpn/admin/keypair` and `/vpn/admin/config-preview` handlers do not declare a
user permission dependency; preview is blocked when `ENVIRONMENT=production` and
`DEBUG=false`. Preview may return sensitive configuration and must be protected.
Gateway or other deployment controls must be verified separately.

### VPN profile catalog and runtime observations

These catalog operations do **not** apply a tunnel. Reads require `vpn:read`;
imports, revisions, archives and preflight require `vpn:write`. Metadata is
organization-scoped and does not include stored configuration ciphertext or keys;
metadata such as endpoint and package IDs can still be sensitive.

| Request | Source contract |
| --- | --- |
| `GET /vpn/providers` | Provider capabilities; not proof of device compatibility. |
| `POST /vpn/profile-preflight` | Inspect one supplied profile without saving or probing the network; maximum request body 96 KiB. |
| `GET /vpn/profiles` | Paged catalog with `page`, `page_size`, `include_archived`, `search`. |
| `POST /vpn/profiles` | Save encrypted profile using client `request_id`; returns a persistence receipt, `apply_allowed=false`, `execution_confirmed=false`. |
| `GET /vpn/profiles/imports/{request_id}` | Read an owned import receipt; 404 only means not observed in that SQL snapshot. |
| `POST /vpn/profiles/batch/preflight` | Inspect 1–100 unique request IDs; body capped at 4 MiB, no save or application. |
| `POST /vpn/profiles/batch` | Save valid items in one transaction with per-item request IDs; response receipts preserve input order. |
| `POST /vpn/profiles/batch/status` | Read receipts for 1–100 unique IDs with `vpn:read`; null does not prove cancellation or failed write. |
| `GET /vpn/profiles/{id}` and `/revisions` | Read metadata or paged immutable revision metadata. |
| `POST /vpn/profiles/{id}/revisions` | Save a new revision using `request_id` and `expected_revision`. |
| `POST /vpn/profiles/{id}/archive` | Archive with `expected_revision`; does not disconnect an existing tunnel. |
| `GET /vpn/runtime` | Paged owned-device Android observation; accepts `page`, `page_size`, `search`, `group_id`. `fresh`, `stale`, `unknown` describe bounded sample/session evidence, not independent proof of end-to-end traffic. |

A timed-out import can still commit. Reconcile the same request IDs and do not
infer failure from a missing snapshot; raw profile data and metadata must be
handled as sensitive. The full schemas,
idempotency and operational limitations are in [VPN profiles](operations/VPN-PROFILES.md)
and [VPN Web guide](operations/VPN-WEB-GUIDE.md).

### GET /vpn/peers

Optional filters are `status` and `device_id`. Returns an array of peers owned by
the organization, not an `items/total` envelope.
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

## n8n integration — `/n8n`

Webhook registry routes use `get_current_user` (Bearer user dependency); the
investigated router does not add a separate permission check to their CRUD. Tenant
ownership is checked against the current user. Effective database policies and
deployment access controls must also be verified.

| Request | Source contract |
| --- | --- |
| `POST /n8n/webhooks` | `name`, HTTP(S) `url`, nonempty `events`; optional `tags` and `secret`. Returns 201 and the plaintext secret once; only its hash is stored. |
| `GET /n8n/webhooks` | `{items,total}` for active registrations only. Disabled records disappear from this list but are not deleted. |
| `GET /n8n/webhooks/{id}` | Owned detail; the secret is not returned. |
| `PATCH /n8n/webhooks/{id}` | Changes `name`, `events`, `tags`, `is_active`; a known owned ID can be re-enabled. URL and secret are not patch fields. |
| `DELETE /n8n/webhooks/{id}` | Deletes an owned registration. The handler returns 204 while the current OpenAPI declaration lists 200. |
| `POST /n8n/tasks` | Requires `script:execute`; `device_id`, `script_id`, optional `priority`, `webhook_url`. Returns a 201 task identity/status, not physical execution. |
| `GET /n8n/tasks/{id}` | Uses `get_current_user` with an owned task check; returns id, status, device_id, script_id. The router does not separately declare `script:read` here. |

A repository search found no call to the registry service's `dispatch_event` in
backend source. Registration therefore does not establish an active event delivery
path. If that service is invoked, its signing key is the UTF-8 bytes of the hex
SHA-256 digest of the issued secret, rather than the raw secret; see the
[operator guide](operations/USER-ADMIN-GUIDE.md#вебхуки--webhooks).

The per-task `webhook_url` is a **separate callback mechanism**: the task result
handler starts an in-process delivery with retries, without passing a signing
secret. Its payload uses `event_type: task.completed` even when `success=false`;
consumers must inspect `success`. Callback delivery or processing is not durable
or confirmed by the task receipt. After a lost task-create response, reconcile
before creating another task. Avoid placing secrets in URLs or logs.

---

## Discovery — `/discovery`

`POST /discovery/scan` requires `device:write`. The request requires `subnet` and
`workstation_id`, and accepts `port_range`, `timeout_ms`, `auto_register`, and
optional `group_id`. **`auto_register` defaults to true**; set it explicitly to
`false` for a scan that must not create device records. The schema normalizes a
network of at most 65,536 addresses, limits timeout to 100–5000 ms, and takes a
pair of inclusive ports (default 5554–5584). The response reports `scanned`,
`found`, `registered`, `devices` and `duration_ms`. `scanned` is calculated as
address count × port count, even when the agent returns no result; it is not a
receipt proving every address/port was contacted. A network scan
and registration do not prove an Android agent is connected or ready for control.
The server currently sends `discover_adb`, while the PC-agent dispatcher does not
implement that command; failures can be converted to an empty result. An empty list
therefore does not establish that no devices exist. See [PC agent](pc-agent.md) and
[request and response schemas](../backend/schemas/discovery.py).

---

## Users — `/users`

`GET /users` and `POST /users` require an administrator, organization owner or
platform administrator. Creation uses `email`, `password` and `role`; it creates
a user in the caller's organization. For non-super-admins the list/detail is
filtered to that organization; the handler's `super_admin` branch removes that
application-level list filter. Effective database policies are deployment-dependent.
`GET /users/{id}` reads a user subject to the same role and scope checks.
`PUT /users/{id}/role` changes a role subject
to owner/platform-admin and target-role checks. `PATCH /users/{id}/deactivate`
disables a user; self-deactivation and removal of the last active owner are
blocked. The deactivate handler returns `204` although OpenAPI declares `200`.
There is no documented DELETE/reactivation route here. The full contract
and receipt boundaries are in [user access](operations/USER-ACCESS.md).

---

## API Keys — `/auth/api-keys`

`GET /auth/api-keys` lists organization keys whose `is_active` is true, without
the raw secret, and requires `api_key:read`. Expired entries can still have
`is_active=true`; the list is not a proof that a key authenticates. `POST /auth/api-keys` requires `api_key:write`; a request contains
`name` and may specify `permissions`, `expires_at` and `key_type`. Delegated
permissions must be held by the caller; omitted permissions default to an empty
list and omitted `expires_at` to no expiry. The `201` response contains `id`, `name`,
`key_prefix`, `raw_key`, `permissions`, `expires_at` and `created_at`; `raw_key`
is displayed once and has the `sphr_{env}_{64hex}` format. Store it as a secret.
`DELETE /auth/api-keys/{id}` requires `api_key:write` and returns `204` in the
handler, although OpenAPI declares `200`.
See [schemas](../backend/schemas/auth.py) and [router](../backend/api/v1/auth/router.py).

---

## Audit Log — `/audit/logs`

`GET /audit/logs` requires `audit:read` and returns an organization-scoped
`AuditLogPage`: `items`, `total`, `page`, `per_page`, `pages`. Parameters are
`action`, `resource_type`, `user_id`, `status`, `q`, `from`, `to`, `page`, and
`per_page` (maximum 100). Items use `user_id`, `ip_address`, `old_value`,
`new_value`, and `meta`; do not depend on the earlier `actor_email` or `remote_ip`
example. `GET /audit/logs/export` requires the same permission and returns CSV,
limited to 5000 rows, with truncation indicated by `X-Audit-Truncated`. See
[investigation and export](operations/AUDIT-INVESTIGATION.md).

---

## Health — `/health`

`GET /health` is the public basic process response, `{"status":"ok","version":"4.0.0"}`
in this source; it is not a dependency report. `GET /health/healthz` is liveness;
`GET /health/readyz` checks dependencies and can return 503; `GET /health/full`
returns component diagnostics and can return 503. `GET /health/build` exposes a
validated build revision or `unknown`. These source contracts do not prove the
health or identity of an installed environment. The separately registered
`GET /health/ready` is described in [main.py](../backend/main.py).

---

## WebSocket — `/ws`

### WS /ws/device/{device_id}

Bidirectional command channel between backend and Android Agent.

**Auth:** `?token=<access_token>` query parameter.

```
wss://yourdomain.com/ws/device/uuid?token=eyJ...
```

**Message format (JSON text or binary for stream frames):**

See [Architecture — WebSocket Architecture](architecture.md#6-websocket-architecture) for protocol-specific sources; this overview is not a complete wire-message reference.

---

## Rate Limits

The checked-in [nginx configuration](../infrastructure/nginx/nginx.conf) defines
an `/api/` request zone of `100r/s` per `$binary_remote_addr` with `burst=50`
and `nodelay`. Its WebSocket locations separately limit concurrent connections:
100 for `/api/v1/ws/` and 200 for `/ws/`. Actual client identity depends on the
proxy chain and effective configuration; deployed values can differ.

Separately, the login service checks five requests per IP per 60 seconds and
returns 429 when exceeded. Do not assume every limiter emits the same status or
`Retry-After`/`X-RateLimit-Reset` headers. See [auth service](../backend/services/auth_service.py)
and [login handler](../backend/api/v1/auth/router.py).

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
`input_params`, `wave_size`, `wave_delay_seconds`. Service объединяет выбранные
устройства и сразу создаёт `QUEUED` run для каждого; параметры волн сохраняются в
`wave_config`, но их применение для задержки admission в исследованном backend не
обнаружено. Не рассчитывайте на поэтапный запуск только по этим полям. `201`
подтверждает созданный intent, а не завершение Android-действия. Steps фиксируются
в run snapshot; повтор после потери ответа может создать новый run или batch.

GET /pipelines/runs принимает `pipeline_id`, `device_id`, `status`,
`active_only`, `page`, `per_page`; состояние выполнения читается по run_id.
Pause/resume/cancel возвращают сохранённое состояние, не подтверждение физической
остановки. Pause допускается для RUNNING/WAITING, resume — для PAUSED; при ещё
занятом executor или неизвестном исходе шага resume возвращает 409. Cancel может
оставаться незавершённым, пока активный child не завершён. После неизвестного
ответа перечитайте run перед повтором. Input_schema пока сохраняется как
описание, без валидации входа исполнителем; глобальные max_retries пока не
реализуют повтор всей цепочки. [Ограничения и восстановление](operations/PIPELINE-DEFINITIONS.md).

Пути `/execute`, `/stop`, `/clone`, `/{id}/stats`, `/{id}/validate` и вложенные
`/{id}/runs` отсутствуют в текущем Pipeline API. Старые примеры этих операций
были планом, а не реализованным контрактом; использовать их нельзя.

---

## Schedules — `/schedules`

Read routes require `schedule:read`; mutations require `schedule:write`. The
[router](../backend/api/v1/schedules/router.py), [schemas](../backend/schemas/schedule.py)
and [service](../backend/services/scheduler/schedule_service.py) define the source contract.

- `GET /schedules` filters by `is_active`, `target_type`, `page`, `per_page` (max 200).
- `POST /schedules` requires `name`, `target_type`, exactly one of `cron_expression`,
  `interval_seconds` (60–86400), `one_shot_at`, and at least one device selector:
  `device_ids`, `group_id`, or `device_tags`. For `script`/`pipeline` targets the
  corresponding ID is required. Parameters are `input_params`, not `variables`.
  For cron, an unrecognized timezone falls back to UTC in the calculation; verify
  the intended IANA timezone and returned `next_fire_at`. A successful `201` returns
  `ScheduleResponse`, including `is_active`,
  `next_fire_at`, `last_fired_at` and `total_runs`.
- `GET /schedules/{id}` reads; `PATCH /schedules/{id}` partially changes; `DELETE`
  returns `204` and deactivates the schedule rather than deleting the row.
- `POST /schedules/{id}/toggle?active=false` sets an explicit desired state using
  a required query parameter, not a JSON `enabled` body.
- `POST /schedules/{id}/fire-now` sets `next_fire_at` to now and returns the
  schedule; it is not a receipt that execution happened. `GET /schedules/{id}/executions`
  returns the paginated execution history with `fire_time`, `actual_time`, counts
  and batch identifiers. There is no registered `POST /schedules/{id}/dry-run`.

A saved schedule or requested fire is not evidence that a scheduler is running,
that a target was reached, or that the resulting task completed. After a lost
mutation response, read back the schedule and execution history before retrying.

## Game Accounts — `/game-accounts`

`account:read` is required for reads and `account:write` for changes. `GET
/game-accounts` supports `game`, `status`, `device_id`, `server_name`, `search`,
`sort_by`, `sort_dir`, `page`, `per_page`; the response is a paginated
`GameAccountListResponse`. Fields include `login`, `game`, `status`, `server_name`,
`device_id` and timestamps. See [schemas](../backend/schemas/game_accounts.py).

`POST /game-accounts` requires `game`, `login`, `password`; `nickname` is optional
and is not automatically generated by this service. `GET /game-accounts/{id}`
returns details; `?show_password=true` also requires `account:credentials:read`
and sets `Cache-Control: no-store`. Handle secrets according to the
[credentials contract](security/account-credentials.md). `PATCH /game-accounts/{id}`
updates fields. `DELETE /game-accounts/{id}` returns 204 from the handler, although
the checked-in OpenAPI snapshot declares 200. Import, assign and release are
separate POST endpoints; do not treat assignment as proof of login on a device.

## Event Triggers — `/event-triggers`

`pipeline:read` permits reads; `pipeline:write` is required for changes. `GET
/event-triggers` filters by `is_active`, `event_type_pattern`, `pipeline_id`,
`page`, `per_page` (max 200). Items contain `event_type_pattern`, `pipeline_id`,
`input_params_template`, `is_active`, cooldown and counters, not generic
`condition` and `action` objects.

`POST /event-triggers` requires `name`, `event_type_pattern` and `pipeline_id`;
the owned pipeline is checked. Optional JSON object `input_params_template`,
`cooldown_seconds` and `max_triggers_per_hour` default to `{}`, 60 and 100;
zero hourly limit means no limit. `GET /event-triggers/{id}` reads the rule,
`PATCH /event-triggers/{id}` updates it, and `DELETE /event-triggers/{id}` hard
removes it with 204. `POST /event-triggers/{id}/toggle?active=true` requires an
explicit query boolean. The PATCH handler skips fields explicitly set to null;
null therefore does not clear the description. A stored rule does not prove event
delivery or pipeline execution; after an uncertain mutation read back the rule. See [router](../backend/api/v1/event_triggers/router.py) and
[schema](../backend/schemas/event_trigger.py).

## Pipeline Settings — `/pipeline-settings`

These are organization settings, not a list of key/value records. `GET
/pipeline-settings` requires `pipeline:read`, returns `PipelineSettingsResponse`,
and may create and commit default settings if none exist. `PATCH /pipeline-settings`
requires `pipeline:write` and partially updates settings. The four `POST
/pipeline-settings/toggle/{orchestration|scheduler|registration|farming}` routes
accept `{"enabled": true|false}` and require `pipeline:write`. There is no
registered `POST /pipeline-settings` or `DELETE /pipeline-settings/{id}`. Status,
servers and nickname routes are listed in the [router](../backend/api/v1/pipeline_settings/router.py).
`GET /pipeline-settings/status` also calls `get_or_create` and commits. Its
`registrations_completed`, `registrations_failed` and `bans_detected` are schema
defaults of zero in this handler, not measured completed/failed/ban counters. The
nickname check requires `pipeline:read`; generation requires `pipeline:write`. Persisting
settings does not prove automation has run. Re-read settings after an uncertain write.

## Account Sessions — `/account-sessions`

Reads require `session:read`; changes require `session:write`. `GET
/account-sessions` accepts `account_id`, `device_id`, `end_reason`, `active_only`,
`sort_by`, `sort_dir`, `page`, `per_page`. The paginated item has `started_at`,
`ended_at`, `end_reason` and `meta`, not the old `status`/`metadata` fields.
`POST /account-sessions` requires `account_id` and `device_id`; `GET
/account-sessions/{id}` reads one. `POST /account-sessions/{id}/end` requires a
JSON `end_reason` (one of `completed`, `banned`, `captcha`, `error`, `manual`,
`rotation`, `timeout`, `device_offline`); the method is POST, not PUT. A missing or
already ended owned active session returns 404; 404 following a lost response does
not establish which attempt ended it. Re-read the session. An unrecognized list
`end_reason` is ignored by the service rather than producing an empty result. See
[router](../backend/api/v1/account_sessions/router.py) and
[schema](../backend/schemas/account_sessions.py). A database record does not prove
that a real game login or logout occurred.

## Device Events — `/device-events`

Reads require `event:read`, writes `event:write`. `GET /device-events` filters by
`device_id`, `event_type`, `severity`, `account_id`, `processed`, `search`,
`sort_by`, `sort_dir`, `page`, `per_page`; it has no `since`/`until` parameters.
Items contain `occurred_at`, `data`, `severity` and `processed` rather than the old
`payload` example. `GET /device-events/{id}` reads one and `GET
/device-events/stats` gives aggregate counts. `POST /device-events` creates an
event with required `device_id` and `event_type`, optional `severity` (default
`info`), `message`, `data` and related IDs. An unrecognized list `severity` is
ignored by the service rather than producing an empty result. `POST
/device-events/{id}/processed` returns 204 in the handler although the snapshot
declares 200. Marking processed is an application record, not proof of a
device-side action. See [router](../backend/api/v1/device_events/router.py).

---

## Batches — `/batches`

These paths are under `/api/v1`. Verified against the batch router/schema on
7 September 2026; the API has no GET collection route or POST cancel route.

### POST /batches

Requires `script:execute`; accepts `script_id` and 1–1000 `device_ids` plus
unique `device_ids` and optional `wave_size` (1–100, default 10), `wave_delay_ms` (default 5000),
`jitter_ms` (default 1000), `priority` (1–10, default 5), `name`, `webhook_url`
and `stagger_by_workstation` (default true). The service commits a batch and pinned wave plan before returning 202. An independent
startup worker discovers pending plans and advances the persisted wave cursor; it
is not started separately for each request. A 202 is admission of the plan, not a
receipt for execution on every device. Source recovery depends on the worker,
database and correctly configured tenant lookup being available.

Wave submission creates QUEUED task intents; it does not mean devices completed
execution. `failed` includes rejected device slots (for example missing, foreign
or already busy devices), plus failed/timed-out tasks. Final task results determine
COMPLETED/FAILED/PARTIAL when all requested slots have an outcome. A database
error aborts the current wave; prior committed waves remain. The worker retries
pending admission using the stored cursor. Invalid plans enter `review_required`;
a lost database commit acknowledgement is not evidence the wave failed. Inspect
the plan and receipts before any new batch.

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
202 with the batch record plus `online_devices`. Unlike `POST /batches`, its
request schema does not define or enforce `expected_current_version_id`; the
selected version is nevertheless pinned when the plan is created.

### GET /batches/{id}

Requires `script:read`. Returns the tenant-scoped batch record with status,
`total`, `succeeded`, `failed`, `wave_config`, timestamps and optional `notes`.
It also exposes `admission_state`, `next_wave_index`, `next_wave_at` and
`admission_receipts`; receipts identify admitted or rejected device slots and task
IDs but are not terminal task results. Read individual tasks for execution state.

### DELETE /batches/{id}

Requires `script:execute`. Returns 204 after the caller commits cancellation.
Unknown/foreign batch returns 404; COMPLETED, PARTIAL, FAILED and CANCELLED
batches return 409. The server serializes cancellation with in-flight wave
admission, then locks eligible tasks and the batch before validation and queue
effects. Later waves re-read tenant/status after this transaction fence and do
not create tasks after cancellation. QUEUED tasks become CANCELLED with UTC
`finished_at`; ASSIGNED tasks receive a durable cancellation request and remain
active until a terminal device result. RUNNING tasks retain the batch endpoint's
finish-current-work policy.

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
creation does not acknowledge physical device execution. The handler commits before
reloading the response; a lost response or later read failure can follow a commit.
Reconcile the task before submitting another execution.

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

## OTA release metadata — `/updates`

All paths in this section are relative to `/api/v1`. The checked-in handler
uses a file-backed release catalog; its HTTP metadata does not establish the
state of another deployment.

- `GET /updates/` requires `device:read`, accepts optional `platform` and
  `flavor`, and returns `releases` and `total`. `POST /updates/` requires
  `super_admin` and returns 201 with registered metadata. For a managed artifact
  the handler verifies file existence, size and SHA-256; for an external URL it
  requires HTTPS but does not fetch or verify that external file.
- `GET /updates/latest` reads `platform`, `flavor`, `version_code` and requires
  an `X-API-Key` header. Its token is evaluated by the Android WebSocket
  authenticator or the scoped OTA recovery path. It returns availability and
  release metadata, not proof of installation. `GET /updates/artifacts/{sha256}`
  uses a Bearer credential with those authentication paths and serves a published
  managed artifact. These routes are distinct from the operator download below.
- `GET /updates/downloads/latest` requires `device:read`, defaults to the
  `android-canary/dev` channel and serves the latest managed APK. Missing channel
  returns 404, an external latest artifact 409 and unavailable/invalid data 503.
  The binary response includes private/no-store caching and SHA-256/version headers.
- `POST /updates/recovery` requires `super_admin`, an owned active device, a
  published managed SHA-256 and a duration of 60–3600 seconds. A committed grant
  can return `wake_published` or `awaiting_connection`; neither establishes receipt
  or install. `POST /updates/recovery/{device_id}/dispatch` requires the matching
  `command_id`, returns 202 and re-wakes the same grant without extending it.
  `GET /updates/recovery/{device_id}` requires `device:read` and returns state,
  sanitized active grant and result history. `DELETE` requires `super_admin`,
  optionally checks `command_id` and returns 204. Revocation does not establish
  cancellation of an installation already underway. Re-read status after a lost
  response instead of creating a duplicate grant.
- `DELETE /updates/{release_id}` requires `super_admin`: the handler returns 204
  on deletion and 404 if absent, while OpenAPI declares 200. The release creation
schema accepts `version_name` up to 128 characters; the addressed recovery grant
and frontend receipt validators cap it at 100. Names above 100 therefore cannot be
assumed compatible with that workflow. See [publication](operations/OTA-PUBLICATION-AND-APK-CHECKS.md)
and [addressed OTA](operations/OTA-ADDRESSED-UPDATES.md). A metadata response does
not prove device installation.

---

## Streaming — `/streaming`

The registered controls are `POST /streaming/{device_id}/start`, `/stop`, and
`/keyframe` with `stream:control`; each checks device ownership and sends a live
command. Their `*_requested` receipt does not confirm agent execution, frame receipt
or browser playback. A transport error may leave delivery unknown; reconcile before
repeating. `GET /streaming/{device_id}/status` requires `stream:read` and observes
the local stream bridge. In this handler `viewer_connected` mirrors `is_streaming`,
not a separate viewer observation; when the bridge is absent, `drop_ratio` is 0.0,
not evidence that no frames were lost. This source behavior does not establish
the state of an installed runtime. Quality routes are separately listed in the
[endpoint catalog](api-endpoints.md). The former `/streaming/start`, `/stop`, and
`/sessions` paths are not registered in the checked-in snapshot.

## Monitoring — `/monitoring`

`GET /monitoring/metrics` requires `monitoring:read` and returns JSON with current
CPU load, cgroup RAM, Redis and network observations; it is not a Prometheus text
endpoint. `GET /monitoring/nodes` uses the same permission; `GET
/monitoring/fleet-coverage` requires `device:read` and separately gates VPN data.
`POST /monitoring/alerts` logs the submitted Alertmanager payload; the router does
not declare a user permission dependency and does not implement the future Fleet
Events broadcast. There are no registered `/monitoring/health` or
`/monitoring/pool-stats` routes in the snapshot. Consult the
[router](../backend/api/v1/monitoring/router.py) and deployment access controls.

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
