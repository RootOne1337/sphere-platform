# Android presence and APK release audit — 26 September 2026

## Current release and device checkpoint — 26 September 2026, 16:59 UTC

This checkpoint supersedes the older snapshots below for APK source and the two
Android emulators attached to the audit workstation. It does **not** claim a
current observation of the remote fleet or the public pilot catalog.

| Evidence source | Observed state | What it proves |
| --- | --- | --- |
| `android/version.properties` on PR #19 | `1.2.28 / 10228` | Source candidate for the PackageInstaller-result fix; source version only until the post-commit APK is fingerprinted. |
| `adb` PackageManager, `emulator-5554` | Last observed `1.2.23-dev / 10223` at 15:58 UTC | No newer device query was run in this review. |
| `adb` PackageManager, `emulator-5556` | Last observed `1.2.27-dev / 10227` at 15:58 UTC | No newer device query was run in this review. |
| `.local-pilot/apk/manifest.json` | `1.2.9-dev / 10209`, SHA-256 `b4bf3f319f92e1f3ac24b7d68dffdc6f6d93a113ad59b10b132ea8f60e641078` | The local promoted-artifact pointer is stale relative to source; it is not proof of the public pilot's current catalog. |
| Remote devices | Not sampled during this review | Online/connecting UI state does not establish APK version or successful OTA. |

The exact `1.2.27-dev` candidate was built from `d9e5c63`, SHA-256
`e9f156b15e42a6db4e2c612835bf068ac788ca7ee512b6f5132f7c11af13fe40`, and kept
as a local-only debug artifact. It has **not** been promoted to the OTA catalog,
uploaded to GitHub Releases, or rolled out remotely. The Android worker polls on
startup/authenticated reconnect and every six hours, but it can only install an
artifact already published in the server's matching `android/dev` catalog; a
successful check or a green CI run is not an installation receipt.

The `1.2.28 / 10228` source candidate adds a fix to the Android
`PackageInstaller` fallback result path. It has not been promoted to the pilot
catalog or rolled out. The previous `1.2.27` file is not this build and must not
be reused as the new candidate.

For this reason, the currently available evidence does not support saying that
remote devices have received `1.2.27`, or that their update/recovery path works.
Release acceptance must correlate, per device ID: reported version/build after
the next authenticated heartbeat; the exact catalog version and SHA-256; OTA
check/download/checksum/install outcomes; and a post-install heartbeat. Stream
acceptance additionally requires capture/encoder/video-frame ingress, viewer
delivery and browser-decoded-frame counters. Keep the current fleet and mass OTA
at **NO-GO** until those receipts are collected.

## Scope and historical live snapshot

This check covers Android APK identity/version, the active pilot OTA catalog,
the backend Android WebSocket disconnect path, and the last retained remote
video-packet evidence. Sphere's device client in this workflow is the Android
APK on an emulator or phone. A PC Agent is not a prerequisite or part of this
diagnosis.

**Historical live correlation: 26 September 2026, 00:59 UTC (not current). Fleet rollout: NO-GO.** The
pilot API reports 15 device records: `010/011/022/023` are `online`, seven
(`012/013/014/016/017/019/020`) are `connecting`, and four (`015/018/021/024`)
are offline or lack a live status key. The operator identifies `010/011` as
local and `022/023` as remote. The user sees remote image and click control on
`022/023`; backend runtime counters independently record ingress and viewer-send
video frames for both. Both report APK `1.2.22-dev / 10222`, and both answered
application-level heartbeat/PING. This confirms a working remote stream path
through the current Cloudflare ingress for these two devices; it does not prove
browser FPS/continuity, fleet-wide stability, or a successful fallback-route
switch.

The seven `connecting` records have no fresh heartbeat or reported APK version.
Server logs show recurring authenticated WebSocket connections followed mostly
by close `1005`; the targeted probe for `019` published PING to one subscriber
but received no command receipt within eight seconds. Here
`connecting` means that authentication/subscribe happened but the APK did not
complete application-level heartbeat readiness. The precise client-side reason
is still unknown; the available evidence does not prove Cloudflare is the cause.

The checked-out APK candidate remains `1.2.23 / 10223`; local canary `5554` runs
it and control `5556` remains on `1.2.22-dev / 10222`. The promoted pilot alias
and default `android/dev` OTA channel still point to `1.2.9-dev / 10209`, while
`android-canary/dev` points to `1.2.19-dev / 10219`. The candidate is debug-signed
and includes private development enrollment material, so it remains local and
is not a fleet release. A signed discovery v25 with independent LocalTunnel
fallback is published, but gateway logs show no Android WebSocket using it;
fallback delivery and failover remain unverified. A PostgreSQL presence-sync
fix is implemented locally and passes its targeted regression tests, but is not
deployed. No APK build or OTA channel was changed in this pass.

## Findings

### AUD-2026-09-26-01 — P1 availability: stale worker disconnect can clobber a reconnect

**Affected path:** Android WebSocket cleanup in
`backend/api/ws/android/router.py` and Redis presence in
`backend/services/device_status_cache.py`.

**Root cause:** each Uvicorn worker owns a process-local `ConnectionManager`.
An old socket can still be the local worker's current socket after the device
has reconnected through another worker. Its cleanup therefore succeeds in that
worker, while the shared Redis key already belongs to the new session. The old
implementation performed an unconditional Redis read followed by a write to
`offline`; that could overwrite the new session's `connecting` or `online`
status. The cleanup also released the device task lock and published an offline
event without checking which session owned Redis presence.

**Evidence / reproduction:** before the fix, the stale-session regression
failed: an `old-session` disconnect changed a Redis record owned by
`new-session` to `offline`. The new concurrent regression opens a Redis WATCH
transaction in one client, commits a reconnect from a second client sharing the
same FakeRedis server, and then lets the stale write execute. Redis invalidates
the stale transaction; the cache re-reads ownership and preserves the new
session. The regression passes after the change.

**Fix:** `mark_offline(device_id, session_id)` atomically watches the presence
key and only writes `offline` when the stored WebSocket session still matches.
The Android handler releases the task lock and emits `device.offline` only when
that ownership-checked transition succeeds. A missing/corrupt presence key is
not replaced by a session-scoped stale disconnect.

**Regression tests:**

- `test_stale_session_disconnect_does_not_overwrite_newer_session`
- `test_concurrent_reconnect_wins_disconnect_watch_race`
- `test_current_session_disconnect_marks_only_its_session_offline`
- Existing Android WebSocket, connection manager and heartbeat tests.

**Validation:** the affected backend set passed **70 tests**, including the
two-client WATCH race; Ruff passed for all changed Python files. The fix was
deployed to the isolated `sphere-pilot-20260911` backend on 25 September at
20:11 UTC as image `sphere-pilot-20260911-backend:7722d50`; the container became
healthy and local/public readiness returned HTTP 200. The rollout preserved all
37 other containers and the 12-file OTA inventory, with zero active stream
viewers before or after. This proves the new image is running in that pilot; it
does not prove the remote fleet has stopped flapping.

**Post-deploy observation:** a read-only Redis summary at 20:31 UTC found 14
tracked status records: 2 `online` with heartbeat younger than 45 seconds and 12
`connecting` with no heartbeat. The two reporting devices identify as
`1.2.22-dev`; the other twelve have no version because they have sent no
heartbeat. A structured-log summary over the preceding ten minutes found 142
successful Android auth events across 12 device IDs, 99 old-connection
evictions, 99 closes with code `4001`, and 41 disconnects with code `1005` across
12 IDs. No `invalid_token` or `auth_error` events appeared. The initial rollout
script reported zero reconnecting IDs because its regex did not match JSON's
quoted `"device_id"` key; that counter is invalid and is not used as evidence.
The later JSON-field summary is the corrected measurement. This directly shows
repeated reconnect/eviction churn after the backend restart, but does not prove
the presence race is the sole cause.

**Residual risk:** this fix does not make the process-local connection registry
shared, and does not prove task execution recovery across a reconnect. The
current pilot has multiple Uvicorn workers. The 12 degraded records and repeated
disconnects remain open; cross-worker reconnect/load acceptance is still
required.

### AUD-2026-09-26-02 — P1 release readiness: APK candidate is not in the OTA channel

**Verified version facts (read-only checks):**

| Source | Observed version | Meaning |
| --- | --- | --- |
| `android/version.properties` | `1.2.23`, code `10223` | Current source version after the session-replacement protocol fix; dev builds append `-dev`. |
| `emulator-5554` PackageManager | `1.2.23-dev`, code `10223` | Addressed `adb install -r` canary; process remained alive after launch. |
| `emulator-5556` PackageManager | `1.2.22-dev`, code `10222` | Installed local Android package. |
| `.local-pilot/apk/manifest.json` and `LATEST-SphereAgent-pilot.apk` | `1.2.9-dev`, code `10209` | Last promoted local pilot artifact, not the current source candidate. |
| Running `sphere-pilot-20260911` catalog, `android/dev` | max `1.2.9-dev`, code `10209` | Main automatic OTA channel. |
| Same catalog, `android-canary/dev` | max `1.2.19-dev`, code `10219` | Canary channel; not the default `android/dev` query. |
| Previous private candidate JSON/APK | `1.2.22-dev`, code `10222`, source `5365de4` | Earlier candidate, not promoted. |
| Current private candidate JSON/APK | `1.2.23-dev`, code `10223`, source `2168c33` | Exact source-pinned debug candidate; SHA-256 `b3eefd9ebaa569e822254ba6dd7439572db1147fde1782758496d31a044318c1`; not promoted. |

The Android `UpdateCheckWorker` asks for the exact pair
`platform=android&flavor=dev` and ignores releases whose version code is not
greater than the installed code. Consequently, this pilot cannot discover
1.2.23 through normal automatic catalog update. The report that both local
devices were on 1.2.22 was true before the canary install; it did not mean that
artifact was published or that remote devices installed it. After the addressed
canary update, a transient snapshot reported three fresh heartbeats. At
21:05:48 UTC only two records were online: one 1.2.23 and one 1.2.22. The other
twelve were connecting without a reported version; their APK versions cannot
be confirmed.

**Why the candidate was not promoted:** the 1.2.23 artifact is `devDebug`,
debug-signed and marked `debuggable`; its build metadata records an embedded
private development enrollment credential. It has only passed one local canary
install/launch and heartbeat check, not a remote canary, extended soak, signed
production release or update-recovery drill. Publishing it as a stable release
or fleet-wide automatic update would expose the development credential and
roll out an unaccepted debug artifact. This audit did not alter the OTA catalog
or publish the APK.

**Affected artifacts:** ignored local files under `.local-pilot/apk/`; the
pilot's persistent `updates/releases.json`; `android/app/build.gradle.kts`;
`android/app/src/main/kotlin/com/sphereplatform/agent/workers/UpdateCheckWorker.kt`.
The source version itself is not stale. The missing part is a safe, verified
promotion from candidate to the matching OTA channel.

**Required release fix:** create a release artifact with the intended signing
identity and non-shared enrollment bootstrap, verify package/version/signature
and runtime behavior on one canary, then promote it to `android/dev` only after
the rollout policy is explicit. Keep the debug candidates private. Add a
promotion check that compares the artifact metadata, catalog entry and release
channel before marking any APK as latest. Until that process exists, the
catalog and the filename `LATEST-SphereAgent-pilot.apk` can diverge from the
source version by design and must not be described as the same thing.

**Residual risk:** an Android process must be running, enrolled and able to
reach the server to check or receive an update. OTA is not an independent
recovery channel for a device that cannot start the APK or reach the only
configured service.

### AUD-2026-09-26-03 — P1 operational issue: remote sessions reach the viewer without image NAL units

**Evidence:** retained backend stream counters from 25 September, approximately
18:35–19:35 UTC, show a local session forwarding about 1.9 MB with IDR and P
frames. Several remote sessions forwarded roughly 5.1–5.3 KB each: SPS/PPS
parameter sets were counted, but IDR and non-IDR picture frames were zero.
For those sessions, backend Redis publish and viewer-send counters tracked the
same small ingress volume, with one viewer subscribed. Thus the browser had no
picture frames to decode in that sample. This evidence does not establish
whether the remote APK capture/encoder produced no picture frames or whether
they were lost before reaching backend ingress; it does not rule out the
Android-to-server tunnel leg.

Only two device-log upload directories were present in the backend observation
and they belonged to local devices. The remote Android capture and encoder
stages therefore cannot be independently checked from that sample. The
Android system's visible MediaProjection notification proves capture consent
started, not that a VCL/IDR frame reached the server.

**Status:** OPEN. No tunnel provider is declared the root cause. The next
diagnostic gate is a single remote canary with correlated APK counters for
capture frames, encoder frames, H.264 VCL NALs, queued/sent bytes and an upload
receipt, matched to backend ingress and browser decoded-frame evidence. This
must identify the first stage whose counter stops increasing before changing
the ingress provider or the APK's streaming implementation.

### AUD-2026-09-26-04 — P2 reconnect churn: session replacement reuses the auth rejection code

**Root cause:** `ConnectionManager.connect` closed an older, already
authenticated socket with code `4001` and reason
`replaced_by_new_connection`. The Android client treats every `4001` as
`invalid_token`, clears its token cache and starts the fresh-token path. A normal
session replacement was therefore interpreted as an authentication failure.
The latest pilot sample contained 99 old-connection evictions and 99 close
events with `4001`, while no `invalid_token` or `auth_error` events were logged.
There were also 41 closes with `1005`. This matches the code path and shows how
repeated replacement can add avoidable authentication work; it does not explain
all transport closes or prove that Cloudflare is the root cause.

**Reproduction:** before the change, the backend replacement test failed because
the old socket received `4001` instead of a distinct session-replacement code.
The Android integration regression also failed on the legacy
`4001 + replaced_by_new_connection` pair after a valid auth acknowledgement:
the client called `clearTokenCache()`. After the fix, the backend uses `4009`;
the Android client recognizes the legacy replacement reason so a rolling
upgrade or an older backend cannot misclassify it as an auth failure.

**Fix and regression tests:** `ConnectionManager` now uses `4009` for a normal
session replacement. `SphereWebSocketClient` excludes the explicit legacy
replacement reason from `4001` auth handling. Tests cover backend close-code
selection, legacy replacement without token invalidation, and genuine invalid
token rejection. The focused backend and Android test runs passed after the fix.

**Status / residual risk:** all PR CI checks passed and backend `2168c33` is
deployed to the isolated pilot. Between 20:43:56 and 20:54:05 UTC, logs recorded
95 old-session evictions with `4009`, none with `4001`, and 44 closes with `1005`.
The earlier 3-online/11-connecting snapshot was transient: at 21:05:48 UTC Redis
again contained 2 online and 12 connecting records. Only the two local APK
versions were reported (1.2.22 and 1.2.23). The 1.2.23 local canary kept the same
process PID for a 181-second window (12/12 process samples; no package-specific
crash-buffer entries). The previous description of an eight-minute post-deploy
sample was incorrect: its requested log lookback exceeded the new container's
age. Use the explicit observation boundaries above instead.
Reconnect churn and remote heartbeat recovery remain open for the degraded fleet;
remote video/control is confirmed only on `022/023` and remains unverified for
the other remote devices.

### AUD-2026-09-26-05 — P1 OTA correctness: PackageInstaller commit was reported as completion

**Scope and trigger:** Android installations that use the non-root
`PackageInstaller` fallback. Rooted LDPlayer devices normally use `su pm install`
instead, so this finding does not by itself explain their stream or heartbeat
state. It matters for ordinary Android phones and any emulator where root install
is unavailable or denied.

**Evidence / deterministic source reproduction:** at PR parent `fd92cf1`,
`OtaUpdateService.installViaPackageInstaller()` called `session.commit()` and
returned without waiting for the PackageInstaller status callback. The existing
`InstallReceiver` logged `STATUS_SUCCESS` / failure, but did not hand the result
back to the OTA caller. `performUpdate()` therefore completed after session
submission, and periodic OTA returned `Result.success()`; manual `OTA_UPDATE`
then emitted `{status: "download_complete"}` and the command dispatcher marked
it `completed`. Android's PackageInstaller contract treats commit as an
asynchronous operation; `STATUS_PENDING_USER_ACTION` explicitly requires user
approval and `STATUS_SUCCESS` is the completed install result ([PackageInstaller](https://developer.android.com/reference/android/content/pm/PackageInstaller),
[Session.commit](https://developer.android.com/reference/android/content/pm/PackageInstaller.Session#commit(android.content.IntentSender))).
This is a code-path proof, not a claim that this fallback was observed failing
on a particular remote device.

**Root cause:** OTA conflated "the OS accepted a package session" with "the OS
installed the target APK." The receiver and the worker had no shared durable
session result, version verification, or distinct pending-user-action outcome.

**Fix:** `InstallStatusStore` persists callback status scoped to the active
session ID and ignores stale session callbacks. `PackageInstallerResultAwaiter`
waits up to 120 seconds for the OS result, requires the installed PackageManager
version to reach the requested version after `STATUS_SUCCESS`, and turns failure
or callback timeout into an OTA failure. The receiver attempts to present the OS
approval intent when provided, catches and records any launch failure, records
only numeric status/session data, and queues a network-constrained diagnostic
upload with up to two minutes of jitter.
The root path also verifies the installed version after `pm install` reports
success. Periodic checks treat pending user approval as a handled state rather
than retrying into repeated approval prompts; the status is not reported as an
installed APK.

**Regression tests and validation:**

- `PackageInstallerResultAwaiterTest`: remains pending until callback; verifies
  actual installed version; consumes status delivered before the waiter starts;
  rejects a success callback with an old installed version; distinguishes
  pending user action; preserves a failure status; ignores an old session
  callback; checks timeout and connected-network diagnostic scheduling.
- `OtaUpdateServiceRecoveryTest`: OTA does not complete while the simulated
  installer result is still pending.
- `UpdateCheckWorkerTest`: pending user action does not schedule a prompt loop;
  transport/install failures still request WorkManager retry.
- Full `devDebug` and `enterpriseDebug` unit suites: 678 tests each, zero
  failures/errors, one skipped each. `assembleDevDebug`,
  `assembleEnterpriseDebug`, and `lintDevDebug` passed. These are local build
  and Robolectric results, not a device installation or remote rollout proof.

**Affected files:** `OtaUpdateService.kt`, `InstallReceiver.kt`,
`InstallStatusStore.kt`, `PackageInstallerResultAwaiter.kt`,
`OtaUserActionRequiredException.kt`, `LogUploadWorker.kt`,
`UpdateCheckWorker.kt`, and the three corresponding Android test classes.

**Residual risk / release gate:** Android still controls whether unattended
installation is allowed. On a standard non-root phone, this flow cannot silently
bypass Android's approval UI. `STATUS_PENDING_USER_ACTION` is returned
immediately as `ota_install_requires_user_action`; if the OS provides no callback
at all, the awaiter times out after two minutes. This review did not install
the candidate on Android 14+, test approval UX on a physical phone, query remote
APK versions, publish the candidate to the OTA catalog, or verify remote
diagnostic upload. Per-device OTA acceptance still requires catalog SHA-256,
download/checksum/install outcome and a post-install heartbeat reporting at
least `10228`.

### AUD-2026-09-26-06 — P2 build validation: Android Gradle Plugin is older than compileSdk support

**Evidence:** local `assembleDevDebug`, `assembleEnterpriseDebug`, and
`lintDevDebug` completed, but Gradle emitted that the repository uses Android
Gradle Plugin `8.3.2`, which was tested through `compileSdk 34`, while this app
targets `compileSdk 35`. The Android SDK command-line tooling also warned that
it only understands SDK XML through version 3 while the installed SDK emits
version 4.

**Impact and status:** this did not fail the current build or tests, and no
runtime defect is demonstrated. It reduces confidence in toolchain validation
for API 35 and can surface compatibility problems on a later build-tool update.
Keep it as a release-engineering follow-up; do not interpret today's green local
tasks as proof that this unsupported toolchain combination is vendor-validated.

**Required follow-up:** upgrade AGP/Gradle/Kotlin as a separate change to a
compatible, officially tested combination, then rerun both Android flavors,
lint, APK metadata/signature checks, and CI before production promotion.

## Focused incident follow-up

The [remote control-path diagnosis](REMOTE-CONTROL-PATH-DIAGNOSIS.md) supersedes
transient fleet counts above and records the later success for remote `022/023`,
the still-unresponsive `connecting` group, observed ingress, reconnect timing,
historical tunnel evidence, and the separate PostgreSQL enum failure. It confirms
partial remote stream/control recovery for two devices, not fleet-wide recovery.

## Validation boundary

This pass did not publish an OTA release, perform a remote ADB operation, or
change the APK. Remote streaming and click control were observed on `022/023`
through Cloudflare, while the larger `connecting` group remains unresolved.
The 1.2.23 APK canary is installed only on `emulator-5554`; `5556` remains the
1.2.22 control, and remote `022/023` report `1.2.22-dev / 10222`. Backend
`2168c33` is running in isolated project `sphere-pilot-20260911`; frontend is
`fc65b55`. The targeted PostgreSQL sync fix passes locally but is not deployed.
The guarded rollout kept 37 other containers and all 12 OTA files unchanged,
with zero stream viewers before/after and HTTP 200 local/public readiness. Older
`sphere-platform` and `sphere-tunnel` projects were not used as test targets.
