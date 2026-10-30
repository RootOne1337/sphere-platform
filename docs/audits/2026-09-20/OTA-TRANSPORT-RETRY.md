# AUD-144 / F32-33 · восстановление прерванной OTA-загрузки

**P0 / High · 23 сентября 2026 · source fix and local tests complete; CI and remote acceptance open.**

[Fleet32 preflight](FLEET32-PREFLIGHT.md) · [Clone identity and remote evidence](CLONE-IDENTITY.md) · [Local pilot status](../../operations/LOCAL-PILOT.md) · [Readiness](../../operations/READINESS.md)

## Impact and evidence

The remote LDPlayer cohort contains 20 clones plus two local agents. Historical
remote evidence showed the 20 clones sharing a device identity, while an OTA
download could fail after the ingress returned HTTP 200. The Android transfer
reported HTTP/2 `PROTOCOL_ERROR` and TLS errors; an HTTP status or accepted recovery
command therefore did not prove that the APK body completed. The artifact was
downloaded from a separate diagnostic route by the audit host, but reachability of
that route from the Android station was never established. Raw logs and network
identifiers remain under private `.local-pilot` evidence.

The exact downloader failure was reproduced locally with a response body that
throws `IOException` after transfer begins. Before the fix, `performUpdate` surfaced
that exception after one request and relied on a later WorkManager cycle. This left
an otherwise healthy agent on the old APK until its next scheduled check.

## Root cause

`OtaUpdateService.downloadApk` made a single OkHttp call. It correctly propagated
read failures and the outer update flow deleted incomplete staging data, but it did
not make a bounded immediate retry. HTTP 200 only described response headers; it
did not imply a complete body or a digest-valid artifact.

## Fix

After a transport `IOException`, the APK now performs at most one immediate retry
using an HTTP/1.1 client derived from the configured client. It waits 250 ms before
the fallback. Opening the destination output stream truncates any bytes from the
failed attempt. Further I/O failure returns control to the existing WorkManager
retry/backoff path. The existing maximum-artifact-size checks, cancellation handling,
same-origin policy, SHA-256 validation, serialized install flow, and Android installer
handoff remain in force. HTTP error responses and size violations are not retried.
Logs expose bounded categories (`tls_failure`, `protocol_failure`, `timeout`,
`io_failure`) rather than arbitrary URLs or exception text.

The APK version candidate is **1.2.10 / 10210**. This is required because an agent
already on 1.2.9 / 10209 ignores an OTA artifact with the same or lower version code.
The bump does not publish a catalog entry or install the APK.

## Reproduction and verification

- Before the code change, the new transient-body-reset regression failed on the
  first interrupted response, reproducing the one-shot failure.
- After the change, `OtaUpdateServiceRecoveryTest` passed **11 tests in `dev` and
  11 in `enterprise`**. The successful transient case requires exactly two requests
  and one install. The repeated-reset case stops after two requests, installs
  nothing, and leaves no partial staging file.
- Existing SHA-256 validation and serialized install regressions remain in the same
  test class. Full PR CI on `2cb4a9d` passed: Android APK build/tests, frontend
  tests/types/build, backend/real-service suite, API-doc check, isolated Redis AOF
  acceptance, RLS, lint, security, production-image bootstrap, and Alembic
  single-head. Backend JUnit evidence records **1,997 tests, 0 failures, 0 errors,
  15 skipped**. The isolated Redis probe reports no OOM and successful
  persistence/restart, while its 2 GiB `memory.peak` reaches the configured ceiling;
  this is not 32-stream headroom.
- Local `devDebug` and `enterpriseDebug` packages were independently built and
  inspected with `aapt`: both report versionCode 10210 (`1.2.10-dev` and `1.2.10`).
  CI build also passed. These debug-signed packages are not published OTA artifacts;
  their signer has not been compared with the currently installed pilot APK.
- No APK was installed on the local or remote pilot during this change. The two local
  agents remain on 1.2.9 / 10209; the remote clone identities and update status are
  unconfirmed.

## Residual risk and acceptance gate

The retry can recover a transient body reset and try a route/protocol compatible with
HTTP/1.1. It cannot make a blocked or invalid TLS route reachable, repair DNS/provider
failure, or guarantee that the second attempt succeeds. Two failures return to the
existing scheduled WorkManager recovery. Delivery therefore remains **unaccepted**
until the candidate is built and published to the managed OTA catalog, then installed
on one remote LDPlayer without manual ADB installation and verified by version,
artifact digest, device identity, process/crash baseline, and a decoded live frame.
Only after that single-device path passes should rollout expand by cohort. The 20
remote cards and 32-device test remain **NO-GO** until each instance has a distinct
stable identity and video has a current decodable frame.
