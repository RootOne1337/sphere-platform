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

The baseline in this table was collected read-only, before the later frontend-only
pilot rollout documented below. At baseline time no container, tunnel, backend,
APK, or remote emulator was restarted or updated.

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
failures/errors; enterprise retained one intentional skip. Afterward, the dev suite
was rerun while building a pilot-compatible candidate. Both artifacts use version
code 10214 and passed APK Signature Scheme v2 verification. The pilot candidate is
`1.2.14-dev`, package `com.sphereplatform.agent.pilot.debug`; the enterprise debug
variant is `1.2.14`, package `com.sphereplatform.agent.debug`. Both use the local
debug certificate whose SHA-256 is
`3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`.

The pilot candidate's package ID and signer match the current local pilot baseline
APK (`1.2.9-dev` / 10209), and its version code is higher. The remotely installed
APK version has not been observed. Its manifest records 630 dev unit tests, zero
failures/errors, one skipped test, and `installed: false`, `published_to_ota: false`.
The candidate and its manifest remain in the ignored
`.local-pilot/apk/` directory. The enterprise APK is a separate debug artifact.
Neither is a release-signed build or a fleet rollout.

| Artifact | Package | Version | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `.local-pilot/apk/SphereAgent-pilot-candidate-1.2.14-dev-552362f.apk` | `com.sphereplatform.agent.pilot.debug` | `1.2.14-dev` / 10214 | 8,413,081 | `0419f5ee8e966d0a45da91752e593e1ff5303cfd9034b62f9d4878c0ba130d1a` |
| `android/app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk` | `com.sphereplatform.agent.debug` | `1.2.14` / 10214 | 8,437,112 | `ac231d46d423508f8ac6639b1c16e269f35860dd9dba353a4d9b70abd64062e7` |

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

## Follow-up runtime check — 2026-09-24

A later rolling 30-minute sample recorded 463 refresh HTTP 401 responses and 9
refresh HTTP 200 responses at the public gateway. Backend logs contained 483
`android_ws: invalid_token` events, all associated with one anonymized device
identity, plus 143 successful authentications and 97 old-connection evictions.
Gateway request logs do not carry the device ID or a shared request ID, so the
refresh and WebSocket counts cannot be joined one-to-one. These recurring rejects
keep the stale-client/re-enrollment defect operationally relevant; the remote APK
version is still unknown, so deployment of the 1.2.14 candidate is unproven.

The same investigation found seven short viewer sessions in an earlier 30-minute
sample: seven gateway HTTP 101 upgrades and seven backend connect/disconnect pairs.
All gateway close timestamps were within 2 ms, and the owner confirmed a batch
start followed by a batch stop after seeing a blank image. The pattern is
consistent with intentional UI closure and is not evidence of a Cloudflare timeout.
A 60-minute correlation by anonymized device ID matched all seven gateway targets
to backend viewer events; one target also appeared in the `invalid_token` events.
That overlap may explain this target's auth/reconnect instability, but not the
near-simultaneous viewer closes. Details and limits are recorded in
[the first-frame follow-up](../2026-09-20/STREAM-FIRST-FRAME.md).

The local pilot frontend was rebuilt from clean source revision `48c9480` and
replaced to deploy the existing browser keyframe-retry fix. It is healthy and
returns HTTP 200 on the tested routes. Backend image `ff87b56dbbd7`, Cloudflare,
APK/OTA catalog, and remote emulators were left unchanged. This frontend rollout
does not validate the Android refresh fix or prove remote frame delivery; both
remain open acceptance gates.

## Follow-up: stream-only remote failure — 2026-09-24

The operator supplied a Fleet Matrix capture showing seven registered endpoints:
two tiles had images, while five remained in the first-frame wait/no-signal state.
This is evidence of a frame-delivery gap for those viewer sessions, not evidence
that the five Android agents were offline.

### What the current pilot proves

Read-only inspection of the pilot config endpoint returned HTTP 200. Its primary
agent route is a public DNS endpoint and it has no configured fallback route. The
APK uses its persisted/configured route list; it does not automatically choose a
LAN address because it happens to be near the server. Existing installations may
still have older persisted routes, so the config response describes new provisioning
and does not prove the route used by every current device.

For `2026-09-23T22:52:50Z` through `23:07:50Z`, the public gateway recorded 315
closed Android WebSocket upgrades with status `101`. Their connection-lifetime
median was 0.33 seconds and p90 was 72.171 seconds. There were no new viewer
upgrades in that exact later interval; already-open viewer sessions are not counted
as new upgrades. Backend logs in the same 15-minute query returned 74 successful
agent authentications and stream-resume events, 242 `invalid_token` events all for
one anonymized device identity, and 74 receive-loop warnings. There were no
`device_not_found` or auth-timeout events. Backend authentication occurs after the
`101` upgrade, so the 242 credential rejections are application-level failures,
not Cloudflare failing the WebSocket handshake. The 74-vs-315 totals differ because
the public access log records at socket close and the rolling windows are not a
shared request/session join. Device IDs remain omitted from this report.

A `101` confirms only the WebSocket handshake; these logs do not measure binary
frame bytes or prove that a browser decoded one. A separate Cloudflared metrics
snapshot showed one HA connection, nine concurrent requests, 15 cumulative request
errors, and 152,122 cumulative requests. Those counters have no session-level frame
attribution; the 15 errors cannot be tied to a video session. Cloudflared emitted
no log lines in the preceding 30-minute query. This is insufficient to blame or
exonerate Cloudflare for video loss, while the 242 auth rejections are a confirmed
independent connection problem.

A later redacted join for `2026-09-23T23:02:39Z` through `23:17:39Z` found five
unique Android identities in the public gateway and the same five identities in
backend successful-auth logs. The one identity with `invalid_token` events also
had 252 public-gateway WebSocket upgrades and 238 backend token rejections in that
window. This confirms that the observed clients, including the rejected identity,
were using the same public ingress and that its token failures occurred after the
WebSocket upgrade. It weakens the claim that Cloudflare categorically cannot carry
the application's stream/control WebSocket, but it still does not prove binary
video delivery for any specific tile: the screenshot has not been joined to these
redacted IDs and neither gateway nor auth logs record frame bytes.

The running backend image is tagged `ff87b56dbbd7`. The repository contains the
idle Redis Pub/Sub polling fix in `fa099aa`; ancestry and the running image's
source confirm it already uses `get_message(timeout=1.0)`. Therefore the previously
identified idle-subscriber reconnect loop is not missing from this backend image.
The checked-in integration regression
`test_static_screen_does_not_restart_capture_after_redis_read_timeout` covers this
case, but it requires disposable local PostgreSQL and Redis services and was not
run against the live pilot.

### Confirmed APK defect and fix

Backend reconnect recovery intentionally sends `start_stream` followed by
`viewer_connected` when an authenticated Android WebSocket reconnects while a
viewer is waiting. Before this change, the APK unconditionally opened
`ScreenCaptureRequestActivity`, even if capture was already active. The capture
service then stopped the working encoder and MediaProjection before trying to
start a replacement. Thus ordinary reconnect recovery could tear down a valid
stream and require another Android capture grant. This is a confirmed source-level
reconnect/idempotency defect and a plausible contributor to the remote first-frame
failure; current remote device telemetry does not prove it was the only cause.

The APK now ignores duplicate starts while `StreamingManager` is active, and the
capture service independently refuses to stop an active projection if a duplicate
start reaches it. A fresh start still opens the permission flow when capture is
inactive. The regression was run against the old dispatcher first and failed:
`Context.startActivity` was called for an already active stream. After the fix, all
15 `CommandDeliveryTest` cases, the capture-service idempotency test, and all seven
`StreamingCaptureLifecycleTest` cases passed in the dev flavor. Full dev and
enterprise unit suites then passed 633 tests each, with zero failures/errors and
one intentional enterprise skip. The pilot candidate is built separately below;
it has not been published or installed on remote devices.

### Disconnect logging correction

The same sample contained 74 receive-loop warnings whose error text was
`Cannot call "receive" once a disconnect message has been received`. The Android
route reads raw ASGI WebSocket events but previously handled only text and binary
messages. On a peer close, Starlette returns a `websocket.disconnect` event; the
loop ignored it, called `receive()` again, then logged the resulting local
RuntimeError as a WebSocket receive failure. That warning is emitted after the
socket has already closed and does not identify which peer or network component
closed it.

The route now treats `websocket.disconnect` as terminal, logs the close code at
info level, and continues normal session cleanup without a second receive call.
Regression tests verify one read for a disconnect and transparent delivery of a
normal application event. `tests/test_ws/test_android_ws_handlers.py` passed all
23 cases; it emitted two existing deprecation warnings outside this change.

### Verified pilot APK candidate

The post-commit pilot build is
`.local-pilot/apk/SphereAgent-pilot-candidate-1.2.15-dev-4c057c5.apk` with a
private build manifest alongside it. The APK reports package
`com.sphereplatform.agent.pilot.debug`, version `1.2.15-dev` / code `10215`, and
8,411,445 bytes. Its SHA-256 is
`7efc954d2895a60abce31cfbffea2f5d354bea1d1a884e588efbb2a7c43f5202`; APK
Signature Scheme v2 verification passed, and the signer matches the previously
recorded pilot signer. Its embedded `GIT_SHA` is `4c057c5`. The manifest records
633 passing dev tests, 633 passing enterprise tests, one intentional enterprise
skip, `installed: false`, and `published_to_ota: false`. This is a locally built
debug pilot candidate, not a release-signed production artifact or remote rollout.

Android's official MediaProjection guidance requires a new user-consented capture
session on Android 14+ for each projection session. Reconnect handling must
therefore preserve an active grant instead of attempting a silent projection
restart. See [Android 14 behavior changes](https://developer.android.com/about/versions/14/behavior-changes-14)
and the [Cloudflare Tunnel FAQ](https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/)
and [WebSockets guidance](https://developers.cloudflare.com/network/websockets/).

### Acceptance still required

This source fix does not yet prove that the remote cohort displays video. The
running Android version and saved route on those remote instances are unknown.
The server-side `stream resumed` event and visible Android capture notification do
not prove encoder output, socket queue acceptance, backend binary-frame receipt,
Redis publish, viewer send, browser receive, or decode. A one-device remote canary
must record those stages under one redacted session correlation ID, along with
installed APK version and route class, before a 32-device update. Keep the existing
pilot services and remote fleet unchanged until that evidence is collected.

Cloudflare documents full WebSocket support, but also documents idle-connection
closures and edge/server restarts. The pilot's public route is therefore a valid
transport candidate but is not independently exonerated: only correlated frame
counters or a controlled A/B path test on owned infrastructure can localize loss.
