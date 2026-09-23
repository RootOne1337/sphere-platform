# AUD-162 · Refresh-auth loop and remote stream outage

**24 September 2026 · P1 availability · Android source fix under verification; remote acceptance OPEN.**

[Fleet operations register](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) ·
[Prior initial-frame race](../2026-09-23/ANDROID-INITIAL-FRAME-RACE.md) ·
[Clone identity contract](../2026-09-20/CLONE-BINDING-V2.md)

## Finding

The current pilot logs show a repeating Android authorization failure that can keep
an affected device offline: the device-token refresh endpoint rejects the stored
refresh credential, but the APK falls back to its old access token and tries the
same credentials again. This is a confirmed source-level recovery defect and a
strong explanation for the reported online/offline flapping on the affected identity.
The logs do not prove that every remote clone shares this identity or that this is
the only cause of every disconnect.

The same sample does **not** establish where the missing video frame is lost. Android
WebSocket and viewer WebSocket upgrades succeeded, but an HTTP `101` proves only the
WebSocket handshake. The sampled Android encoder/queue metrics had no active series.
There is therefore no frame-level evidence to blame Cloudflare, the ISP, the browser
decoder, or Android capture for the current remote session.

## Runtime evidence

Read-only observation of the local pilot stack; no container, tunnel, backend, APK,
or remote emulator was restarted or updated for this audit.

| Evidence | Observed value | What it proves |
| --- | --- | --- |
| Backend image | Pilot backend image built from `ff87b56`; container healthy, zero restarts, about five hours of uptime at inspection | The runtime was not restarting during the check. Its source commit is an ancestor of the checked-out branch; no backend source change is needed for the Android token recovery fix. |
| Public gateway, 2-hour UTC window ending 2026-09-23 20:57 | `POST /api/v1/devices/refresh`: 1,929 × `401`, 24 × `200`; `/ws/android`: 2,215 × `101`; `/ws/stream`: 53 × `101`; device registration: 1 × `201` | Refresh is repeatedly rejected while both WebSocket routes can complete transport upgrade. `101` is not application authentication or video proof. |
| Backend application events, same window | 1,956 `android_ws: invalid_token`; 256 `auth passed`; 172 `Evicting old connection`; 256 `stream resumed for reconnected agent`; 52 viewer connect/disconnect pairs | There is sustained invalid-token retry activity, plus repeated replacement of existing authenticated sessions. The access logs lack a shared request/session correlation ID, so they cannot prove which refresh response caused each WebSocket rejection. |
| Anonymized identity grouping | Seven device-ID prefixes were represented in the selected events; one identity prefix accounts for all 1,956 invalid-token events and also had successful auth events | At least one identity is repeatedly rejected. Prefixes and raw identifiers are intentionally omitted from this committed report. This alone cannot distinguish a stale token from multiple cloned processes using one ID. |
| Backend stream metrics, point-in-time read | Zero samples for FPS, encoder frames/bytes, and Android WebSocket queue attempts/accepted/rejected | No active session telemetry was available at that instant. This is not proof that no frame was ever produced. |
| Local emulators | Only local devices are visible to this workspace's ADB; they are not the remote LDPlayer station | Local emulator state cannot verify which APK version or Android crash buffer is present on the remote machines. |

The gateway `401` and backend `invalid_token` totals are separate measurements, not a
one-to-one join. They differ by 27 events in this window. Device identifiers and
request credentials are not copied into this report.

## Root cause and recovery path

In `AuthTokenStore.getFreshTokenLocked`, a refresh `401` was treated like a temporary
network error. The generic exception path returned `getToken()`, which is the same
access token already rejected by the server. Then
`SphereWebSocketClient` handled WebSocket auth rejection by setting only the access
token expiry to zero, retaining the rejected refresh token, and retrying after a
short delay. Together these paths can create an endless refresh/`invalid_token`
loop.

The existing recovery path can re-enroll without erasing device assignment. Before
each WebSocket connection the client calls `InstanceRegistrationGuard`. When no
device access token remains, the guard resolves the saved zero-touch configuration
and obtains a fresh registration. Device ID, instance binding, and management routes
must stay in preferences until that registration is committed.

## Fix

`AuthTokenStore` now classifies refresh HTTP `401` as a terminal credential rejection.
The backend refresh route uses `401` for a missing or invalid device refresh
credential. HTTP `403` is not classified as credential loss: gateway policy and the
enrollment endpoint's missing `device:register` permission can return `403`, so
clearing credentials on that response would be unsafe. A `403` follows the existing
fallback for policy/ingress diagnosis. On `401`, the APK durably removes only access
token, refresh token, refresh-rotation ID,
and expiry, then returns no token. The next connection attempt enters the existing
registration guard. If local preference persistence fails, the current process also
fails closed and does not reuse the rejected token. If another registration replaced
the credentials while the request was in flight, the fix preserves and uses that
newer pair.

Temporary timeouts, network errors, malformed responses, and server `5xx` still use
the pre-existing transient fallback. That avoids turning an outage into mass
re-enrollment; it also means those transient paths need separate rate/backoff
observation if the server remains unavailable for a long time.

## Regression and validation

The new MockWebServer regression was run against the old implementation first. It
failed because a rejected access token was returned instead of `null`. After the
fix, the focused dev-flavor `AuthTokenStoreTest` passed. Tests verify that `401`
clears the rejected pair and a second caller sends no second refresh request; device
ID, clone binding and server URL remain intact; and a failed preference commit cannot
return the rejected token. A separate test verifies `403` preserves the token pair.
The existing HTTP `500` fallback regression remains in the same class.

Full dev and enterprise Android unit suites each passed 630 tests, with zero
failures/errors; enterprise retained one intentional skip. Both debug APK variants
assembled successfully as version 1.2.14 / 10214, and APK Signature Scheme v2
verification passed. Their package IDs are `com.sphereplatform.agent.dev.debug` and
`com.sphereplatform.agent.debug`; both use the local debug certificate whose
SHA-256 is `3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`.
The APK file SHA-256 values are recorded below. These are local debug packages, not
release-signed APKs; they are not published to the OTA catalog, installed on remote
devices, or accepted as a fleet rollout.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `android/app/build/outputs/apk/dev/debug/app-dev-debug.apk` | 8,437,232 | `e6cc790611c382f66a452ee08319cedbe5316715a8f16d4f487b60c7b68a65ab` |
| `android/app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk` | 8,437,112 | `ac231d46d423508f8ac6639b1c16e269f35860dd9dba353a4d9b70abd64062e7` |

Reproducible full-matrix command:

```powershell
cd android
./gradlew.bat --no-daemon `
  :app:testDevDebugUnitTest :app:testEnterpriseDebugUnitTest `
  :app:assembleDevDebug :app:assembleEnterpriseDebug
```

## Stream boundary and next acceptance

The stream status REST handler currently derives both `is_streaming` and
`viewer_connected` from local viewer presence. Its response is not a frame receipt.
The production stream path has separate Android encoder/queue, backend receive and
publish, viewer-send, and browser-decode boundaries; this incident sample does not
join those boundaries with one session identifier. Existing AUD-151/AUD-161 fixes
are source changes and do not establish that the running remote APK includes them.

Before a fleet update, a one-device canary must provide one correlated session record
with: installed APK version and signer; refresh result and Android-auth result;
encoder frames/bytes; Android WebSocket queue attempts/accepts/rejects; backend
received and viewer-sent frame counts; browser received and decoded frames; and
last-frame age. The canary must also show that refresh `401` stops repeating,
automatic enrollment retains one device identity, the device stays online through
a reconnect, and the viewer decodes a new keyframe. Only after this passes should a
small clone batch be updated. Do not use a `101`, stream icon, viewer-presence status,
or APK download response as a substitute for a decoded frame.

**Residual risks:** re-enrollment currently updates a matched device's metadata and
sets `is_active = true`; the backend does not distinguish an expired refresh token
from a token belonging to a deliberately disabled device (both can result in `401`).
Thus this recovery path can reactivate a disabled device if its enrollment key remains
valid. Decide whether administrative disable must be terminal before production; if
so, add a distinct server response and client recovery state before enabling this
automatic path in production. Remote APK versions and crash buffers are not available
to this workspace; current remote frame loss is not localized; the remaining 172
old-session evictions are not attributed to duplicate clones versus normal reconnect
overlap; and the deployed pilot still uses a Quick Tunnel without an independent
media-path comparison. The source fix reduces the known terminal-token reconnect
loop, but no remote recovery or 32-device readiness claim is made here.
