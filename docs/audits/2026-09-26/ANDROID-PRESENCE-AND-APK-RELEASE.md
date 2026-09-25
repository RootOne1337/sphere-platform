# Android presence and APK release audit — 26 September 2026

## Scope and current decision

This check covers Android APK identity/version, the active pilot OTA catalog,
the backend Android WebSocket disconnect path, and the last retained remote
video-packet evidence. Sphere's device client in this workflow is the Android
APK on an emulator or phone. A PC Agent is not a prerequisite or part of this
diagnosis.

**Fleet rollout: NO-GO.** The source and two attached local emulators are at
1.2.22-dev, but that candidate is not the promoted APK and is absent from the
running pilot OTA catalog. The last promoted local APK alias and the main OTA
channel are both still 1.2.9-dev. Separately, a reproducible cross-worker
disconnect race could overwrite a newer Android session's Redis presence. The
source fix and regression test are recorded below; remote video remains a
separate unresolved issue.

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
two-client WATCH race; Ruff passed for all changed Python files. This validates
the Redis ownership transition in an isolated test. It does not prove the
remote fleet has stopped flapping until the new backend is deployed and its
reconnect behavior is observed.

**Residual risk:** this fix does not make the process-local connection registry
shared, and does not prove task execution recovery across a reconnect. The
current pilot has multiple Uvicorn workers. Reconnect/load acceptance across
workers is still required after deployment.

### AUD-2026-09-26-02 — P1 release readiness: candidate 1.2.22 is not in the OTA channel

**Verified version facts (read-only checks):**

| Source | Observed version | Meaning |
| --- | --- | --- |
| `android/version.properties` | `1.2.22`, code `10222` | Current source version; dev builds append `-dev`. |
| `emulator-5554` PackageManager | `1.2.22-dev`, code `10222` | Installed local Android package. |
| `emulator-5556` PackageManager | `1.2.22-dev`, code `10222` | Installed local Android package. |
| `.local-pilot/apk/manifest.json` and `LATEST-SphereAgent-pilot.apk` | `1.2.9-dev`, code `10209` | Last promoted local pilot artifact, not the current source candidate. |
| Running `sphere-pilot-20260911` catalog, `android/dev` | max `1.2.9-dev`, code `10209` | Main automatic OTA channel. |
| Same catalog, `android-canary/dev` | max `1.2.19-dev`, code `10219` | Canary channel; not the default `android/dev` query. |
| Private candidate JSON/APK | `1.2.22-dev`, code `10222`, source `5365de4` | Built candidate, not promoted to the OTA catalog. |

The Android `UpdateCheckWorker` asks for the exact pair
`platform=android&flavor=dev` and ignores releases whose version code is not
greater than the installed code. Consequently, this pilot cannot discover
1.2.22 through normal automatic catalog update. The report that an emulator is
already on 1.2.22 is true for the two local PackageManager reads; it does not
mean the 1.2.22 artifact is published or that remote devices installed it.

**Why the candidate was not promoted:** the inspected 1.2.22 artifact is
`devDebug`, debug-signed and marked `debuggable`; its build metadata records an
embedded private development enrollment credential. It has not had a remote
canary/runtime acceptance. Publishing it as a stable release or making it the
fleet-wide automatic update would expose the development credential and roll
out an unaccepted debug artifact. This audit did not alter the OTA catalog or
publish the APK.

**Affected artifacts:** ignored local files under `.local-pilot/apk/`; the
pilot's persistent `updates/releases.json`; `android/app/build.gradle.kts`;
`android/app/src/main/kotlin/com/sphereplatform/agent/workers/UpdateCheckWorker.kt`.
The source version itself is not stale. The missing part is a safe, verified
promotion from candidate to the matching OTA channel.

**Required release fix:** create a release artifact with the intended signing
identity and non-shared enrollment bootstrap, verify package/version/signature
and runtime behavior on one canary, then promote it to `android/dev` only after
the rollout policy is explicit. Keep the 1.2.22 debug candidate private. Add a
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

## Validation boundary

This pass did not modify the APK, publish an OTA release, perform a remote ADB
operation, or claim that remote streaming is fixed. The running pilot observed
during the release check was `sphere-pilot-20260911`, backend/frontend image tag
`fc65b55`; older `sphere-platform` and `sphere-tunnel` projects were not used as
test targets. The session-race source change is not considered live until a
controlled deployment and post-deploy reconnect check are recorded.
