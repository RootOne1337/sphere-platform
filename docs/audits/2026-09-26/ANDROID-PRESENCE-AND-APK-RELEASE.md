# Android presence and APK release audit — 26 September 2026

## Scope and current decision

This check covers Android APK identity/version, the active pilot OTA catalog,
the backend Android WebSocket disconnect path, and the last retained remote
video-packet evidence. Sphere's device client in this workflow is the Android
APK on an emulator or phone. A PC Agent is not a prerequisite or part of this
diagnosis.

**Fleet rollout: NO-GO.** The checked-out APK source and private candidate are
`1.2.23 / 10223`; canary `5554` now runs that candidate and reports a fresh
heartbeat. Control `5556` remains on `1.2.22-dev / 10222`. The latest aggregate
at 21:05:48 UTC has 12 records in `connecting` without a fresh heartbeat, so their installed
versions remain unknown. The promoted pilot alias and default `android/dev` OTA
channel still point to `1.2.9-dev / 10209`; `android-canary/dev` points to
`1.2.19-dev / 10219`. The 1.2.23 candidate is debug-signed and includes a
private development enrollment credential, so it remains local and is not a
fleet release. Backend fixes `7722d50` and `2168c33` are live in the isolated
pilot, but presence remains degraded and remote video is unresolved.

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
Reconnect churn, remote heartbeat recovery, and remote video delivery remain open.

## Focused incident follow-up

The [remote control-path diagnosis](REMOTE-CONTROL-PATH-DIAGNOSIS.md) supersedes
transient fleet counts above and records a local/remote small-command comparison,
reconnect timing, historical tunnel evidence, and the separate PostgreSQL enum
failure. It does not declare the remote transport repaired.

## Validation boundary

This pass did not publish an OTA release, perform a remote ADB operation, or
claim that remote streaming is fixed. The 1.2.23 APK canary is installed only
on `emulator-5554`; `5556` remains the 1.2.22 control. Backend `2168c33` is
running in isolated project `sphere-pilot-20260911`; frontend is `fc65b55`.
The guarded rollout kept 37 other containers and all 12 OTA files unchanged,
with zero stream viewers before/after and HTTP 200 local/public readiness. Older
`sphere-platform` and `sphere-tunnel` projects were not used as test targets.
