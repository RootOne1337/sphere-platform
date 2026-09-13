# Android Agent

13 September 2026 pilot update: signed APK `9618a57` fixes empty/truncated UTF-8
diagnostic tails and is verified on both LDPlayer instances. In-place upgrades
reconnect automatically, preserve IDs/cache, and return real commands and logs.
[Current artifact](operations/LOCAL-PILOT.md) · [AUD-100 evidence](audits/2026-09-05/APK-UTF8-LOG-TAIL.md).

Developer and operator guide, checked against the audit branch on **11 September
2026**. The audit is ongoing; production readiness and compatibility with every
Android device have not been established. Findings, reproduction evidence and
remaining blockers are in the [audit report](audits/2026-09-05/AUDIT-REPORT.md).

For the separate Windows installation started on 12 September, use the
[local pilot handoff](operations/LOCAL-PILOT.md). Its dev debug APK has a separate
application ID, local enrollment key and discovery URL; normal dev/enterprise
artifacts are not configured for that isolated installation.

## 1. Overview

The Kotlin APK connects managed devices to Sphere Platform, executes DAGs and
input commands, captures screens and manages WireGuard-compatible tunnels.
The main service is declared as `dataSync`; screen capture has a separate
`mediaProjection` service. Watchdogs and foreground declarations are recovery
mechanisms, not an uptime guarantee.

The current build declares **minSdk 26**, **targetSdk/compileSdk 35**. These are
build settings, not proof of operation on every OS/OEM. Root input and the VPN
adapter require privileged device capabilities; an ordinary unrooted phone is
not yet a verified replacement for a prepared emulator. Boot/background/timeout,
permission and power-management behavior needs device runtime testing.

## 2. Architecture

| Component | Current responsibility |
| --- | --- |
| `SphereAgentService` | Starts the dispatcher, network monitor, management WS and config watchdog; closes service resources on destruction |
| `DeviceCommandHandler` | Compatibility facade around `CommandDispatcher` |
| `SphereWebSocketClient` | Management connection, target-bound server auth acknowledgement, reconnect and stale-listener fencing |
| `CommandDispatcher` | Command validation, control target matching, ACKs, journal and DAG dispatch |
| `CommandJournal` | Encrypted durable DAG receipts, duplicate replay and terminal-result retention |
| `DagRunner` / `LuaEngine` | Node routing, loops, retries, control checkpoints and Lua actions |
| `AdbActionExecutor` | Root/device actions; ambiguous pipe delivery is surfaced without automatic resend |
| `StreamingManagerImpl` / `ScreenCaptureService` | MediaProjection/MediaCodec screen capture and binary frame transport |
| `ZeroTouchProvisioner` / `DeviceRegistrationClient` | Configuration discovery and backend device registration |
| `AuthTokenStore` | Management origin, device identity and persisted access/refresh credentials |
| `ConfigWatchdog` / `ServiceWatchdog` / workers | Configuration polling and service recovery attempts |
| `SphereVpnManager` / `KillSwitchManager` | Root `wg-quick` and firewall operations |
| `OtaUpdateService` | APK download, SHA-256 validation and installation request |

Hilt modules are `AppModule`, `NetworkModule`, `StreamingModule` and `LuaModule`
in [the DI directory](../android/app/src/main/kotlin/com/sphereplatform/agent/di).
Source under [the agent directory](../android/app/src/main/kotlin/com/sphereplatform/agent)
is authoritative for component contracts.

## 3. Build Instructions

Use JDK 17 and Android SDK platform 35 with the committed **Gradle 8.9 wrapper**.
The current version catalog pins AGP 8.3.2 and Kotlin 1.9.23. Gradle reports an
AGP/compileSdk compatibility warning in the retained build evidence; toolchain
modernization remains open. Do not suppress a warning as proof of compatibility.

From `android/`:

```bash
./gradlew --no-daemon :app:assembleEnterpriseDebug
./gradlew --no-daemon :app:testEnterpriseDebugUnitTest
# All debug flavors / all unit-test variants, as used by CI:
./gradlew assembleDebug
./gradlew test
```

On Windows use `gradlew.bat`. Set `JAVA_HOME` and `ANDROID_HOME` for the chosen
local JDK and SDK. The enterprise debug artifact is:
`app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk`.

| Variant | Application ID | Provisioning defaults |
| --- | --- | --- |
| Enterprise release | `com.sphereplatform.agent` | Blank server/key/device defaults; provision explicitly |
| Enterprise debug | `com.sphereplatform.agent.debug` | Same enterprise defaults; debug is a distinct installed package |
| Dev debug | `com.sphereplatform.agent.dev.debug` | Development defaults and HTTP permission in build configuration |

These packages have separate app storage. Installing another flavor is not a
credential/journal migration. Release has shrinking/minification enabled; a
debug test result does not validate release shrinking or release installation.

### Signing for release

[The existing Gradle configuration](../android/app/build.gradle.kts) reads:

- `SPHERE_KEYSTORE_PATH` — path to the managed signing keystore;
- `SPHERE_KEYSTORE_PASSWORD` — keystore password;
- `SPHERE_KEY_ALIAS` — alias, default `sphere`;
- `SPHERE_KEY_PASSWORD` — key password.

Provide these through the release environment/secret manager, then run
`./gradlew :app:assembleEnterpriseRelease`. Keep signing material out of Git.
The current build only attaches release signing when the configured store file
exists; a successful build alone is not proof of a signed, installable update.
Verify artifact signing and installed-package compatibility before rollout.

[Android CI](../.github/workflows/ci-android.yml) builds debug flavors, runs unit
tests and uploads `app/build/outputs/apk/**/*.apk`. It does not currently provision
release signing, install an APK or certify a physical-device runtime.

## 4. Configuration

`ZeroTouchProvisioner.discoverConfig()` uses the first accepted source:

1. Managed configuration: `sphere_server_url`, optional `sphere_fallback_server_url`,
   `sphere_api_key`, `sphere_device_id`.
2. `sphere-agent-config.json` in shared external storage, app external files,
   then app internal files, subject to actual storage access.
3. The HTTP configuration endpoint from `BuildConfig.CONFIG_URL`.
4. `BuildConfig.DEFAULT_SERVER_URL` / `DEFAULT_API_KEY` fallbacks.

`SetupActivity` also supports manual setup and the `sphere://enroll` deep link.
`AutoEnrollmentWorker` attempts discovery/registration in the background. Local
files and setup therefore remain supported; no `res/values/config.xml` backend
URL override is used by this configuration chain.

Enterprise `CONFIG_URL` is set from `SPHERE_CONFIG_URL` at build time. Dev defaults
read `SERVER_PUBLIC_URL` from the root `.env` and retain a development config URL.
After AUD-73, HTTP discovery is a cancellable public request: no device credentials,
10-second HTTP deadline and a 64-KiB response bound before parsing. Periodic/forced
watchdog checks share one request; stop and local route changes invalidate its
response. See the [discovery recovery contract](architecture/ANDROID-DISCOVERY-RECOVERY.md)
for lifecycle and configuration; AUD-74 adds the
[saved routes and ACK-gated selection](architecture/ANDROID-SAVED-ROUTES.md).
Distribution/trust of enrollment keys and mutable remote configuration remains
part of the security audit; development defaults are not a production policy.

An illustrative local configuration shape is:

```json
{
  "server_url": "https://management.example",
  "fallback_server_url": "https://management-backup.example",
  "api_key": "<provisioned enrollment credential>",
  "device_id": "<assigned device UUID>"
}
```

Device auto-registration calls `POST /api/v1/devices/register` and persists the
returned device ID, access token and refresh token. Refresh uses
`POST /api/v1/devices/refresh`; the backend binds credentials to an active
device and rotates refresh material. AUD-69/70 add a persisted operation UUID for
recovering a lost response; see the [refresh recovery contract](security/device-refresh-recovery.md). Legacy credentials from before this audit's
migration require re-enrollment. Do not duplicate enrolled app storage across a
fleet: identity and outstanding receipts belong to one device.

## 5. Deployment to Devices

Select an explicit isolated device serial and the intended flavor/package. For a
prepared test device, from `android/` the installation command shape is:

```bash
adb -s <test-device-serial> install -r app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk
```

This is an operator instruction, not a record of a successful installation in
this audit. The audit did not modify the user's existing emulator. Validate
provisioning, root/other capabilities, notification/background behavior and screen
capture permission for the actual device image. Manifest entries alone do not
prove that privileged installation, log reading or persistent execution works.

Deploy compatible backend workers before enforcing explicit control targets in
the APK. Preserve/migrate credentials and command receipts deliberately. See
[the rollout contract](security/task-control-protocol.md) for mixed-version limits.

## 6. OTA Updates

**Pilot status, 13 September:** the server currently has **zero published OTA
releases**. A local `LATEST` APK does not publish a release. Version 10201 / 1.2.1-dev
was installed on both pilot devices via controlled ADB rollout; this does not prove
automatic self-install. Runtime OTA needs only the Android APK and its reachable
management server, not LDPlayer or station ADB. Root must be authorized for the
app itself. [Verified capabilities and outstanding blockers](audits/2026-09-05/ANDROID-UNATTENDED-CAPABILITIES.md).

`OTA_UPDATE` uses an `OtaUpdatePayload` with `download_url`, `version`, `sha256`
and optional `force`. The current implementation validates an HTTPS URL whose
host matches the management server, downloads up to 200 MiB and compares the
SHA-256 digest. It then tries root `pm install` with a bounded wait, falling back
to a `PackageInstaller` session.

The previous guide's application-level `APK_SIGNING_CERT_SHA256` check was not
implemented in this APK service. A checksum from the same command is not an
independent release signature. Package installation outcome, redirect/origin
handling, partial-download cleanup, version policy and recovery across process
loss still need audit. A command ACK is not proof that the new APK booted and
reconnected. No OTA rollout was performed during this audit.

Source: [OtaUpdateService](../android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaUpdateService.kt)
and [payload](../android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaUpdatePayload.kt).

## 7. Command Reference

The management endpoint is **`/ws/android/<device_id>`**. After opening the socket,
the APK sends `{"token":"<access token>"}` as its first text message; the token is
not a query parameter. The socket being locally open does not prove completion
of server-side authorization. Reconnect, refresh and server acceptance must be
verified as separate events.

The backend authenticates before loading the target device and binds the verified
organization to each fresh SQL Session used by task progress, start receipts,
terminal results and device events. `result_ack` is sent only after the owned task's
SQL commit. Under runtime RLS credentials, duplicate results after reconnect preserve
the first terminal outcome and do not count the batch twice. See the
[credential/RLS contract](security/device-credential-bootstrap.md) for migration
grants, session boundaries and remaining delivery risks. These server-side ASGI
regressions do not establish APK process/OS behavior or network failover.

Ordinary commands use the following envelope; timestamps here are illustrative
and senders must supply current UTC epoch seconds:

```json
{
  "type": "TAP",
  "command_id": "<command UUID>",
  "signed_at": 1788717000,
  "ttl_seconds": 60,
  "payload": {"x": 10, "y": 20}
}
```

Replies use `type: command_result`, the same `command_id`, and status `received`,
`running`, `completed` or `failed`, with optional `error` and `result`. The old
`command.execute`/`correlation_id`/`data.cmd` examples do not describe this dispatcher.
See [command models](../android/app/src/main/kotlin/com/sphereplatform/agent/commands/model)
and [CommandDispatcher](../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt)
for exact payload fields. DAG action fields can differ from direct commands
(for example, DAG `key_event.keycode` versus direct `KEY_EVENT.key_code`).

`EXECUTE_DAG` carries `payload.dag` or a cache identity plus a retrievable DAG;
explicit DAG content is authoritative. `payload.timeout_ms` takes precedence over
the DAG timeout. Receipts are persisted before execution; terminal DAG results are
retained until `result_ack` follows the backend PostgreSQL commit. Duplicate
receipts replay the saved outcome. Interrupted execution has an explicit unknown
outcome and is not automatically repeated.

`CANCEL_DAG`, `PAUSE_DAG` and `RESUME_DAG` require `payload.task_id` identifying
the active DAG and a distinct control command ID. Controls are checked before
individual actions/retries, including nested loops. An observed cancel after the
final action gives a failed DAG result. Paused bodies resume or exit on cancel;
node/global timeout budgets keep running. A control ACK records acceptance,
not physical stop. [Full control contract](security/task-control-protocol.md).

The journal has a 512-receipt / 1 MiB cap and rejects new DAGs when full.
Acknowledged receipts are eligible for pruning after seven days from creation;
unacknowledged results remain retained until the backend commit acknowledgement. A loop retains at most 200 diagnostic entries while
continuing its configured actions under explicit iteration/depth/timeout limits.
The receipt and log bounds are not a whole-process memory budget or exactly-once
physical execution guarantee.

Streaming control is handled separately: `start_stream`, `stop_stream`,
`viewer_connected` and `request_keyframe`; live input includes `touch_tap` and
`touch_swipe`. These are not the ordinary command envelope shown above.

## 8. VPN Integration

`VPN_CONNECT` carries plaintext tunnel configuration in `payload.config` and
optionally `payload.endpoint` for the kill-switch setup. Disconnect/reconnect use
`VPN_DISCONNECT` / `VPN_RECONNECT`. `SphereVpnManager` writes app-private config,
invokes root `wg-quick` and checks the interface. This requires actual root/tool
availability and is not a verified userspace VPN implementation for every phone.

Backend lease allocation, router state and APK tunnel state are separate. The
server command publisher remains a stub on the audited path; SQL/mock-router
success does not establish a device tunnel. Follow the
[VPN lease design and residual risks](audits/2026-09-05/VPN-LEASE-DESIGN.md).

## 9. H.264 Streaming

Screen capture runs through `ScreenCaptureRequestActivity`, `ScreenCaptureService`
and `StreamingManagerImpl`, with MediaProjection and MediaCodec. The dispatcher
requests a keyframe when a viewer connects. Presence/pong can work while capture
is broken; test connection and video delivery separately.

Codec backpressure, buffer copying, encoder recovery, viewer churn and device
permission/background transitions remain open runtime work. No verified FPS,
bitrate capacity, per-device RAM/CPU, battery usage or 10–64-emulator host capacity
is available from this audit. Start the future load matrix with idle connections,
then DAG actions, then selected concurrent streams; retain per-device and host
measurements plus failure/reconnect timings.

## 10. Troubleshooting

| Symptom | Inspect first |
| --- | --- |
| Registration/refresh rejected | Management origin, active device/tenant binding, credential migration and API response; redact tokens |
| Socket reconnects continuously | Authorization close/failure, DNS/network changes, current config source and generation-specific logs |
| Duplicate DAG appears stuck | Existing active/durable receipt, busy/full journal and pending backend commit acknowledgement |
| Cancel/pause appears ineffective | Target UUID/control receipt, action checkpoint, current root/Lua call and node/global timeouts |
| Task failed after pipe error | Unknown root delivery; reconcile device state before scheduling a new action |
| Device connected but video absent | Capture permission/service, encoder state and viewer/keyframe flow |
| VPN SQL row exists but no tunnel | Publisher implementation, router inventory, root/wg-quick and actual device interface |
| OTA command accepted but old version runs | Installed package/flavor, signer, installer outcome and post-update enrollment/reconnect |

Do not clear credentials or command journals as a generic reconnect repair:
this can discard identity and unresolved execution evidence. Diagnostic uploads
can contain sensitive data; removal of raw `typeText` logging does not certify
all Lua, shell, historical or uploaded logs.

## 11. Security Notes

The audit has added device/tenant authorization, refresh rotation, origin-bound
automatic HTTP credentials, durable receipts, control targeting/checkpoints and
root unknown-outcome handling. Scope and residual risk are recorded per finding
in the audit report. Remaining priorities include durable server cancellation,
real RLS roles, provisioning trust, OTA recovery, other log surfaces and full
runtime verification. These controls do not certify every endpoint or dependency.

## 12. Verified audit snapshot

**354 enterprise debug JVM tests passed**, with zero failures/errors/skips across
28 suites. Eleven new regressions first failed before the two loop/control fixes:
log-cap action loss, error handling past the cap, coroutine cancellation, wire
cancel/pause in nested bodies, retry/final-action boundaries and durable replay.
Evidence: [loop before](audits/2026-09-05/evidence/android-loop-before.txt),
[loop after](audits/2026-09-05/evidence/android-loop-after.txt),
[controls before](audits/2026-09-05/evidence/android-control-boundaries-before.txt),
[full suite after](audits/2026-09-05/evidence/android-control-boundaries-after.txt).

The combined backend/PC/local-service/deployment suite last passed **1334 tests**,
with **69.31%** backend coverage. It includes 453 PostgreSQL/Redis cases and
15 new post-auth Android runtime-role cases (AUD-61). JVM/MockWebServer and isolated PostgreSQL/Redis
checks exercise real runtime logic but replace device/network boundaries.

Real APK-to-backend runtime remains incomplete: automatic approval review
rejected starting the isolated local API with `blocked by policy`; no workaround
was used. OS/process death, physical-device behavior and fleet capacity remain
unverified. Track the latest PR checks on the actual revision; a build or unit
suite alone does not close these requirements.


### Fleet reconnect policy (AUD-67)

The first retry now waits 1–2 seconds with independent equal jitter; exponential
windows cap at 15–30 seconds. Clean server closes also enter a retry window instead
of reconnecting immediately. Stop and forced reconnect retain their existing wake
channel. These limits describe retry scheduling, not command latency or a recovery
SLO. Three new tests execute the real client loop/backoff with socket doubles and
virtual time; the suite contained 347 tests at AUD-67, 354 at AUD-70 and 362 at AUD-71. Older APK builds retain their
old policy until updated. A secondary endpoint and LAN-first discovery are separate
work; jitter alone is not a backup channel.


## Refresh recovery after response loss (AUD-69/70)

The APK commits `refresh_rotation_id` on the IO dispatcher before calling refresh.
Retries reuse the persisted UUID and original token. Backend migration
`20260910_device_refresh_retry` retains one operation and returns the same unconsumed
successor without extending its expiry. The token tuple and intent removal share one
preference edit; stale responses cannot overwrite re-enrollment or cleared credentials.

Seven new memory/disk/HTTP-boundary cases pass; the suite at AUD-70 was **354 tests / 28
suites**. This is not a physical process-death/keystore test. Deploy migration and
all backend workers before APK; preserve app data and signing identity. Older
servers do not guarantee response recovery. The feature does not recover an
already-lost legacy rotation, initial enrollment, expired refresh credentials or a
second server route.

## Refresh deadlines and cancellation (AUD-71)

Refresh now uses asynchronous OkHttp with cancellation wired to that specific Call.
Its own 10-second deadline returns the stored token and releases the refresh mutex
while cancelling HTTP. Parent cancellation propagates to stop the caller. Callback
parsing closes the bounded response body and cannot save credentials; the active
coroutine checks current state before saving. An uncertain operation retains its ID
for recovery on the next attempt. The shared WS client's timeouts are unchanged.

Eight new JVM cases cover a hung request, stop, late body, outer timeout, 64 parallel
callers with one cancelled waiter, and malformed/oversized/incomplete responses.
Initial reproduction: four failures and one passing control; current enterprise
debug suite: **362 tests / 29 suites**. These are real OkHttp calls with synthetic
interceptors/bodies, without sockets or a hardware fleet. Waiting for the mutex and
blocked preference/keystore IO are not bounded by an HTTP deadline. Physical Android
network/OS behavior remains unmeasured; see the
[full recovery contract](security/device-refresh-recovery.md#тайм-аут-и-остановка-refresh-aud-71).

## Confirmed WebSocket authentication (AUD-72)

Transport open now sends only the token. The APK becomes connected and starts result
replay only after `auth_ok` with the current device ID and numeric protocol version
1. The 20-second WS deadline includes waiting for this acknowledgement; a silent
server cannot leave the APK apparently connected. Invalid acknowledgements and
application data arriving before auth do not reach command execution. Auth close
codes keep their immediate token-refresh path. Ended generations are invalidated
before backoff, including late callback races before coroutine cleanup runs.

The backend emits the acknowledgement after identity/tenant/device checks and
before publishing the socket to command producers. It confirms authentication,
not readiness of every dependency or SQL commitment of a task result.

Initial baseline: 10 failures / 2 controls in 12 new JVM cases, 5 failures / 3
controls in eight non-owner SQL/ASGI cases. The completed Android set adds four
callback/binary regressions: **378 tests / 30 suites** pass. Prior lifecycle tests
now establish server acknowledgement before testing an active channel.

Deploy **all backend workers before APK**, preserving app data and signing identity.
An older backend without `auth_ok` cannot confirm a new APK; it will reconnect on
deadline. [Wire protocol, rollout and evidence](architecture/ANDROID-CONNECTION-PROTOCOL.md).
Saved secondary routes are implemented by AUD-74 below; physical Android sockets
and fleet recovery remain unmeasured.


## 16. Discovery recovery (AUD-73)

The AUD-73 enterprise debug snapshot passed **399 tests / 31 suites**, including
21 new discovery cases. Initial baseline: nine failures / four controls. Public
HTTP, cancellation, single-flight checks, stop/restart and local route revisions
are covered with Robolectric and synthetic transport. AUD-74 extends this with saved
route candidates and ACK-gated selection, below. [Current contract and evidence](architecture/ANDROID-DISCOVERY-RECOVERY.md).

## 17. Saved management routes (AUD-74)

The APK retains primary/fallback URLs and its last selected address. A failed
attempt advances to the next saved route, including token refresh on that route;
neither GitHub nor fresh discovery is required. Selection is accepted only after
the expected device-bound `auth_ok`, before result replay. A config update cannot
disconnect a healthy authenticated socket. Late callbacks and changed local route
revisions cannot promote an obsolete connection.

Configure `fallback_server_url` in provisioning JSON/HTTP config or
`sphere_fallback_server_url` in MDM. Already enrolled agents read route-only MDM or
local files at service start without a bootstrap key. Initial enrollment still
requires a key; local JSON accepts `api_key` or the generator's `enrollment_api_key`.
Successful LAN registration preserves its request address, recording a different
advertised server URL as fallback unless an explicit backup was supplied.

Both addresses must belong to the same installation and credential/task state.
One extra URL does not supply a second backend, database or command protocol.
[Configuration examples, rollout, pinning and persistence limits](architecture/ANDROID-SAVED-ROUTES.md).

**426 JVM tests / 32 suites**, including **27 new route regressions**, pass with
isolated HTTP/WS doubles. Three new PostgreSQL/ASGI cases cover optional config and
lost refresh response recovery across origins; two Python cases exercise the real
fleet config generator. These results do not establish physical OS behavior,
network recovery latency, APK resource use or fleet capacity.

## 18. Background enrollment and current device identity (AUD-75)

Both background workers now register a supplied bootstrap key when auto-registration
is enabled or no valid assigned UUID exists. Generated JSON's flag and null fields
are parsed correctly. A shared worker mutex prevents concurrent registration; an
issued identity retries service activation without another registration after a
missing marker or rejected start request. Missing config and transient HTTP failures
remain retryable. WS reads the assigned ID on each attempt and rejects stale-ID ACK.

**450 JVM tests / 33 suites**, including 22 new worker cases and two WS identity
cases, pass. Android service/root and HTTP boundaries are doubles; this is not an
installed APK or SQL smoke. [Behavior, reproduction, rollout and residual risks](architecture/ANDROID-BACKGROUND-ENROLLMENT.md).
Initial response loss, physical disk/keystore persistence, legacy static setup
concurrency and actual OS/fleet/resource behavior remain open.

## 19. Initial registration HTTP recovery (AUD-76)

Registration now has cancellable asynchronous HTTP with a 10-second request budget;
success bodies are limited to 64 KiB before parsing. Non-success status does not wait
for an error body. Late cancelled callbacks cannot write credentials. Worker timeout
returns retry, while parent cancellation propagates and frees the enrollment mutex.

**465 JVM tests / 34 suites**, with 15 new cases. [Contract, evidence and limits](architecture/ANDROID-BACKGROUND-ENROLLMENT.md).
The HTTP bound does not make device/preference IO bounded; AUD-77 adds one checked registration commit.
Lost server commit responses and real installed APK/fleet recovery remain open.

## Registration state recovery (AUD-77)

Real registration now commits UUID, tokens and routes in one checked preference
edit and serializes issuance with refresh across UI/background callers. Local
state changes fence late replies. Disk failure returns an error and restores
previous memory; it cannot undo server-side credential issuance. Legacy static-key
setup remains separate. **485 JVM tests / 35 suites**, including 20 new cases.
[Contract and remaining initial response-loss/OS limits](architecture/ANDROID-BACKGROUND-ENROLLMENT.md).

## Inspected CI artifact for the first pilot (11 September 2026)

The actual `debug-apk` artifact from [Android run 34528723295](https://github.com/RootOne1337/sphere-platform/actions/runs/34528723295)
at `0da40f1` was downloaded and inspected locally with Android SDK build-tools
35.0.0. Both ZIP CRC checks and APK v2 signature verification pass. Version code:
10200; enterprise version 1.2.0, dev 1.2.0-dev.

| Package | Application ID | APK bytes | min/target SDK |
| --- | --- | ---: | --- |
| dev debug | `com.sphereplatform.agent.dev.debug` | 8,353,013 | 26/35 |
| enterprise debug | `com.sphereplatform.agent.debug` | 8,352,977 | 26/35 |

Both artifacts are debuggable, contain 15 DEX files and no packaged `lib/*.so`
entries. These observations do not establish runtime memory, speed, root tooling
or VPN support. [Hashes, signer fingerprints and artifact provenance](audits/2026-09-05/evidence/apk-0da40f1-inspection.json).
This is an inspected debug artifact, not a release or an installed-device proof.

Before a persistent pilot, select one package and a managed signing identity,
verify update compatibility and preserve app data. Changing flavor creates separate
storage. The current PR workflow does not manage release keys or install/update
the APK; CI debug outputs are suitable for development inspection, with update
compatibility still to be checked. The inspected artifact expires on 9 December
2026 under its current retention policy. Later CI runs are separate artifacts.
