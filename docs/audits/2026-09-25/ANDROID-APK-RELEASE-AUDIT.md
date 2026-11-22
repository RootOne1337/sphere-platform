# Android APK release audit — 25 September 2026

## Decision

**NO-GO for a 20/32-device rollout.** A private pilot APK candidate was built,
verified and kept outside Git. Source tests and static analysis pass, but there
has been no installation, remote-device canary, tunnel-failure drill, physical
Android test or soak on this candidate. The evidence supports a controlled
single-device test after checking the device's root history; it does not support
a production release or a claim that every remote clone will reconnect and
update without intervention.

The APK-only pass did not change the backend, frontend, tunnel, live server,
device state or OTA catalog. It did not install anything on an emulator. Raw
logs and enrollment credentials are intentionally absent from this report.

## Candidate artifact

| Property | Verified value |
| --- | --- |
| Version | `1.2.22-dev`, version code `10222` |
| Variant / package | `devDebug`, `com.sphereplatform.agent.pilot.debug` |
| Source | `5365de4` (`fix(android): harden agent recovery and crash diagnostics`) |
| SHA-256 | `468bd6523220554581635eed86101b3d7b3b87b12beb37d1b7210ef3af74af0e` |
| APK signer certificate SHA-256 | `3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f` |
| Size | 8,417,269 bytes |
| Artifact / metadata | `SphereAgent-pilot-candidate-1.2.22-dev-5365de4.apk` and adjacent JSON under ignored `.local-pilot/apk/` |
| Installed / published | No / no |

`aapt dump badging` verified package/version; `apksigner verify --verbose
--print-certs` passed. The certificate digest matches the previously recorded
pilot signer and the source BuildConfig contains commit `5365de4`. This is a
debug-signed dev artifact, not a production-signed APK. It includes the private
development enrollment credential in its app configuration, so the candidate
must remain private and must not be attached to a public GitHub Release or CI
artifact.

## Findings and fixes

### AUD-APK-01 — P1, fixed in source: rooted startup could mutate the whole OS

In the parent revision `046d4f9`, `SphereApp.onCreate()` called
`RootAutoStart.configure()` on every app process start. The root setup could set
SELinux permissive, apply a broad `supolicy` allow rule, remount system
partitions, write startup hooks and copy the APK into `/system/priv-app`. This
was broader and more persistent than recovering the Sphere package. A user
removing/reinstalling the APK would not necessarily remove those changes.

The current source removes system remounts, SELinux/policy changes, startup file
installation, privileged APK copies, the detached shell daemon and repeated
`set-stopped-state` recovery. Root assistance is limited to this package's
background policy. Boot recovery uses Android receivers, persisted jobs and
WorkManager. A worker no longer issues a second root service start before the
normal service start.

**Evidence / regression:** inspected the prior startup call chain and root
commands; `RootAutoStartPolicyTest` asserts that package setup has no stopped
state reset or system-wide command; the agent service and enrollment tests pass.

**Residual risk:** the candidate can detect some known artifacts from older
versions, but deliberately does not remove them. A particular device's SELinux
mode, init hooks, watchdog files or `/system/priv-app` copy have not been
checked. Reimaging a clean test emulator is safer than treating an APK upgrade
as cleanup of previous root changes. Root managers may also require their own
first-use authorization.

### AUD-APK-02 — P1, fixed in source: Android 14+ foreground-service type did
not match the persistent control channel

The long-lived agent service previously declared `dataSync`, although it holds
the management connection between short synchronization jobs. The manifest
now declares `specialUse` with the foreground-service permission and an
explicit device-management subtype; `SphereAgentService` passes the matching
runtime type on API 34+, while older Android keeps the compatible two-argument
call. The short WorkManager task still uses `dataSync`.

**Evidence / regression:** `SphereAgentForegroundServicePolicyTest` parses the
manifest and checks the permission/subtype, and asserts that the ordinary APK
does not claim system-only `INSTALL_PACKAGES`/`READ_LOGS` or
`android:persistent`. The four build variants compile and pass tests.

**Residual risk:** static tests do not prove foreground start behavior on
Android 14/15 or vendor ROMs. `specialUse` has platform and distribution-policy
requirements; the actual use case and notification behavior need device
acceptance. No 24-hour service soak was run. This foreground-service change
does not bypass Android 14's requirement for user consent for each
MediaProjection capture session on target-34+ devices; unattended capture on
arbitrary physical phones is not promised by this APK pass. See [Android's
MediaProjection behavior](https://developer.android.com/about/versions/14/behavior-changes-14#media-projection-consent).

### AUD-APK-03 — P1, fixed in source: startup Java exceptions were not persisted
and crash evidence was not queued promptly

The crash handler existed but was not installed from the application startup
path. It is now installed in `attachBaseContext`, before Hilt/WorkManager
initialization, writes an app-private Java/Kotlin uncaught-exception record and
delegates to Android's original handler. `LogUploadWorker` includes the bounded
crash tail, retains it after failed or changed uploads, and queues a connected,
unique one-time upload when a persisted crash file is present. The periodic
upload remains as recovery.

**Evidence / regression:** `CrashHandlerTest` invokes an uncaught exception and
checks both persisted evidence and delegation; `LogUploadSchedulingTest`
checks that no empty job is queued and repeated crash scheduling coalesces.

**Residual risk:** upload needs the app process/WorkManager to run, valid
enrollment, network and a reachable configured server. This cannot guarantee a
report for power loss, native abort, kernel/LMK kill, disk failure or a process
that never runs again.

### AUD-APK-04 — P1, partially fixed / system diagnostics remain OPEN: ordinary
APK cannot collect all Android logs

The prior manifest requested `READ_LOGS`, a signature/privileged permission
that ordinary third-party APKs do not receive. The collector also retained a
bounded prefix while reading a subprocess, which could miss the newest tail or
hang on a stuck command. The unsupported permission claim was removed. The
collector now drains to EOF while retaining only the newest 2 MiB, has a
10-second process deadline and a bounded reader. An API-26-incompatible
`List.removeFirst()` in the script LRU was also replaced with `removeAt(0)`.

**Evidence / regression:** manifest policy test checks that `READ_LOGS` is not
declared; `LogcatCollectorTest` checks the bounded newest tail; full source tests
cover the cache eviction limit.

**Residual risk:** the APK runs `logcat` as its app UID and does not elevate the
collector with `su`. Root presence alone therefore does not make native
SIGABRT/tombstone, ANR, LMK, system or other-app buffers remotely visible. The
remote diagnostic contract is Sphere application logs and uncaught Java/Kotlin
exceptions, not “all Android logs.” To collect protected buffers later, add a
separate explicitly authorized root/MDM collector with bounded retention and
redaction, or use host-side ADB during a controlled test.

### AUD-APK-05 — P1, clone identity is fail-closed but not runtime-proven on
LDPlayer clones

`Build.getSerial()` was called from ordinary app code and can fail without
privileged permission; it was removed from the compatibility fingerprint.
Registration uses `InstanceBindingReader`, which reads an emulator VM serial
from `ro.boot.serialno`/`ro.serialno` and refuses ambiguous clone identity
rather than inventing a UUID from copied app data.

**Evidence / regression:** `CloneDetectorTest` covers the non-privileged stable
fingerprint; the existing instance-binding tests cover unavailable/invalid
serial rejection and stable serial hashing; registration guard prevents the
WebSocket from starting before rebind.

**Residual risk:** no current APK was installed on the 20 remote LDPlayer
clones. If LDPlayer copies the same VM serial, hides both properties, or does
not regenerate its virtual serial when cloning, registration will fail closed
instead of producing 20 devices. That must be measured on the actual clone set;
APK-only code cannot safely synthesize a unique hypervisor identity from cloned
`/data`.

### AUD-APK-06 — P1, OTA recovery remains conditional

The APK supports authenticated HTTPS catalog checks, SHA-256 validation,
serialized OTA execution, root `pm install -r` and PackageInstaller fallback.
`OTA_UPDATE` is a targeted WebSocket command, so an online device can be
selected for a pilot update. The periodic catalog endpoint is queried by
platform/flavor/version, not by an independent per-device rollout ring. The
agent must be running, enrolled and able to reach the server to receive either
path. A failed/unreachable agent cannot update itself through this channel.

**Evidence / regression:** existing `OtaUpdateServiceRecoveryTest` covers
interrupted/oversized/checksum-invalid downloads, overlapping updates and retry
after installer failure; `CommandDeliveryTest` covers the OTA command journal.
`UpdateCheckWorker` ignores stale/non-increasing catalog versions.

**Residual risk:** the fallback PackageInstaller session does not establish
that every Android device can install silently. The candidate has
`REQUEST_INSTALL_PACKAGES`; installation without user action depends on root
`su` being available/authorized or the app being a suitable managed-device
installer. The code does not set a universal silent-install capability. There
is no independent recovery updater, local artifact mirror or proven automated
rollback if the agent cannot restart. Android documents a pending-user-action
flow for many PackageInstaller sessions and unattended installs for fully
managed devices; see the [PackageInstaller contract](https://developer.android.com/reference/android/content/pm/PackageInstaller.SessionParams)
and [Android Enterprise dedicated-device guide](https://developer.android.com/work/dpc/dedicated-devices/cookbook).

### AUD-APK-07 — P1, no production release artifact/signing gate

The local artifact is `devDebug`, signed by the pilot debug certificate and
contains a development enrollment credential. Android CI currently builds a
debug APK and uploads it as a workflow artifact; the tagged release workflow
creates a changelog/GitHub Release but does not build, sign or attach an APK.
No production keystore is configured in this environment.

**Residual risk:** there is no reproducible signed production artifact or
release provenance/SBOM attached to a Release. The private candidate is only
for development validation. Do not publish it or treat the debug signer as the
production update identity.

### AUD-APK-08 — P1, current bootstrap has one mutable external route

The locally signed discovery payload is version 24, has a valid RSA signature
and expires on 21 October 2026. The public raw GitHub manifest was fetched and
its signature verified. It advertises one current Quick Tunnel host and no
fallback. Its source branch is `codex/pilot-bootstrap-20260911`, currently the
head of draft `sphere-agent-config` PR #1. The same pilot environment supplies
the dev server endpoint.

**Residual risk:** an unreachable/rotated tunnel prevents current management
and OTA traffic; if GitHub/raw access is also blocked, the APK has no second
signed discovery source. The in-app signed cache helps only while the cached
server remains reachable. Move the signed manifest to a durable mainline source
and configure an independent endpoint/manifest mirror before remote mass
testing. The current candidate was not tested against a server or tunnel.

### AUD-APK-09 — P1, corrected during this pass: Android 27 theme qualifier
blocked the test/build matrix

The first full `gradlew test` run failed in AAPT for all four variants because
the `values-v27` style implicitly inherited a missing `Theme` parent. The main
theme was split into a shared `Theme.SphereAgent.Base`; default and API-27
styles now inherit that base explicitly.

**Evidence / regression:** the failing run is retained in private ignored pilot
logs. After the correction all four variants resource-link, compile and pass
their unit tests. `assembleDevDebug` also succeeds.

## Verification performed

| Check | Result |
| --- | --- |
| `gradlew test` | 660 tests each for `devDebug`, `devRelease`, `enterpriseDebug`, `enterpriseRelease`; 0 failures/errors |
| `gradlew lintDevDebug` | 0 errors, 65 warnings |
| `gradlew assembleDevDebug` | Passed with source SHA `5365de4` |
| APK package/version/signature/hash | Verified with `aapt`, `apksigner` and SHA-256 |
| Signed discovery | Local and remote envelopes verified; config version 24; one source, no fallback |
| Device install / OTA / Android runtime | Not performed |
| Server, Cloudflare or other external service mutation | Not performed |

The 65 lint warnings include the Android Gradle Plugin 8.3.2 warning for
`compileSdk=35` (AGP was tested through 34), 36 dependency update notices, 12
unused-resource notices, a Play-policy warning around battery-optimization
exemption, and smaller API/text/compatibility warnings. They do not fail this
pilot build, but the AGP/release-toolchain warning should be resolved before a
production release.

## Mass-test gates

1. Install this exact candidate on one clean, disposable Android 9 LDPlayer
   instance and confirm package, signer, version, enrollment receipt, online
   state and crash-upload path. Do not use an image known to contain previous
   Sphere system-level root hooks until those hooks are inspected.
2. On the actual clone set, compare VM serials and server device IDs. Require
   20/20 unique bindings and no copied credentials before expanding the wave.
3. Send a per-device OTA command to one connected canary, record download hash,
   signer/package install result, post-update version and reconnect receipt;
   then test one deliberately interrupted download and recovery.
4. Run a controlled connectivity outage in both directions and verify the
   stable route/fallback design. The current single Quick Tunnel route does not
   pass this gate.
5. Configure production signing and a release workflow that builds, signs,
   verifies signer/hash, produces provenance and attaches the artifact. Keep
   this pilot APK private.
6. Before claiming complete remote crash observability, add and test a
   separately authorized system-log collector. Never report native or OS-killed
   process evidence as available from the app-only crash handler.

## Platform references

- [Android `READ_LOGS` permission](https://developer.android.com/reference/android/Manifest.permission#READ_LOGS)
- [Foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [Android 14 MediaProjection consent](https://developer.android.com/about/versions/14/behavior-changes-14#media-projection-consent)
- [PackageInstaller session user-action behavior](https://developer.android.com/reference/android/content/pm/PackageInstaller.SessionParams)
- [Android Enterprise dedicated devices](https://developer.android.com/work/dpc/dedicated-devices/cookbook)
