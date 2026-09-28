# Android APK release-readiness audit

**Проверка:** 28 сентября 2026, Asia/Yekaterinburg
**Область:** Android source, local Gradle outputs, unit tests, release signing and GitHub workflows in PR #19.
**Статус:** source changes under validation; no production APK was signed, published or installed in this audit.

[Current state](../../operations/CURRENT-STATE.md) · [Android agent guide](../../android-agent.md) · [OTA reliability](../../architecture/ANDROID-OTA-RELIABILITY.md) · [Android CI](../../../.github/workflows/ci-android.yml) · [Release workflow](../../../.github/workflows/release.yml)

## Executive finding

The APK source contains substantial reconnect, OTA, screen-capture, task execution and bounded diagnostic code. The release path did not establish that a downloadable artifact was safe to install: CI built only debug APKs, the tag workflow created a GitHub Release without attaching an APK, and Gradle allowed release tasks to succeed while producing unsigned files. Local `apksigner verify` rejected the prior `1.2.34` dev and enterprise release outputs as unsigned. A passing unit-test/build job was therefore not proof of a usable release.

This change set makes release signing fail closed, adds signed release smoke builds to CI with a disposable CI-only key, and makes the production tag workflow build and verify the enterprise package, source version, signing-certificate continuity and SHA-256 before attaching the APK. It also routes remote diagnostic uploads through the APK's already-persisted management-route candidates after transport/server failures, while refusing to fan credentials out after authentication or rate-limit responses.

## Findings and fixes

| Finding | Evidence | Change | Remaining proof |
| --- | --- | --- | --- |
| Release could silently be unsigned | Prior local `assembleDevRelease` and `assembleEnterpriseRelease` produced `*-release-unsigned.apk`; `apksigner verify` failed because the APK had no signing metadata. | Every release-shaped package task now requires all four `SPHERE_KEYSTORE_*` settings and an existing keystore; release build type always selects the release signing config. | CI and local disposable-key smoke verification prove packaging/signing mechanics only, never production-key continuity. |
| CI did not exercise release packaging | `.github/workflows/ci-android.yml` ran debug assembly and tests only. | CI creates a short-lived non-production key, runs all unit-test variants, lint, debug assembly and both signed release smoke variants; it verifies signatures and uploads only debug APKs plus test reports. | A green PR run is still not an install/OTA/physical-device test. |
| Tag release published no APK | `.github/workflows/release.yml` only generated changelog and GitHub Release metadata. | A stable version tag must match `android/version.properties` and point to a commit reachable from `main`; workflow builds only `enterpriseRelease`, verifies package/version and the pinned signer fingerprint, computes SHA-256, then attaches APK and checksum. | The workflow cannot publish until production signing secrets and the expected certificate fingerprint are configured in GitHub. No tag/release was created by this audit. |
| Remote diagnostic upload depended on only the active server URL | `LogUploadWorker` used `getServerUrl()` even though `AuthTokenStore.connectionRoutesSnapshot()` holds the signed primary, last authenticated and fallback routes. | The worker tries distinct saved routes after I/O failure, 404 or 5xx; 401/403/429 do not trigger another credential-bearing request. Persisted crash evidence is still deleted only after a successful response. | Route fallback is unit-tested. Actual backend reachability and delayed WorkManager delivery still need an enrolled remote canary. |
| Source version did not advance for the candidate | `android/version.properties` was `1.2.34 / 10234`, same as the last recorded remote reports. | Candidate source version is advanced to `1.2.35 / 10235`; it is not yet a signed downloadable artifact or OTA catalog entry. | Check that the production signing certificate matches installed packages before installing; then verify OTA catalog and installed package hash on a small canary. |
| Android toolchain was older than declared platform SDK, and a naive modernization broke builds | Prior catalog pinned AGP 8.3.2/Kotlin 1.9.23/KSP 1.9.23-1.0.19 with compileSdk 35; retained output warned AGP was validated only through API 34. Trialing Kotlin 2.1.20 + KSP 2.1.20-2.0.1 with existing Hilt 2.51.1 reproducibly failed all four variants in KSP with `KSTypeArgument.type ... STAR null`, matching the reported [KSP star-projection issue](https://github.com/google/ksp/issues/2463). | Keep the proven Kotlin/KSP pair and update AGP to the latest 8.7 patch, 8.7.3, which supports API 35 with the committed Gradle 8.9 ([AGP 8.7 notes](https://developer.android.com/build/releases/agp-8-7-0-release-notes)). Do not ship the failed combination. A coordinated Hilt/KSP2 migration is deferred: [Dagger's guide](https://dagger.dev/dev-guide/ksp.html) marks KSP support stable only from Dagger 2.60+/KSP 2.3.9+, and the 2.59 release line changes the Hilt Gradle plugin's AGP requirement ([Dagger releases](https://github.com/google/dagger/releases)). | Re-run the full tests/build after the conservative toolchain selection. The old Kotlin/KSP pair still has a modernization follow-up; upgrading it requires its own tested dependency matrix, not a blind version bump. |

## APK capabilities and practical limits

The APK includes a device-bound identity and version report, registration/rebind, management WebSocket reconnect and route recovery, bounded local Sphere logs, best-effort upload of app-visible logs and Java/Kotlin crash records, persisted task receipts, WorkManager recovery, OTA download hash checks, MediaProjection/H.264 capture, and a constrained DAG/Lua executor. This is not unrestricted remote shell, arbitrary Android telemetry, or a proof that every asynchronous operation completed. Review the [Android agent guide](../../android-agent.md) for the component contracts and limits.

Diagnostics are intentionally bounded. Ordinary app processes cannot reliably read other applications' logs, kernel output, privileged crash buffers, native tombstones, LMK decisions or all ANR traces. `READ_LOGS` is privileged. Java/Kotlin uncaught exceptions have an app-private crash record; native `SIGABRT`/`SIGSEGV`, process kill and power loss can bypass it. WorkManager is best-effort, not continuous telemetry. A successful upload means the server accepted that request, not that the device's entire history is present.

Screen capture is a separate Android permission and service lifecycle. Android's MediaProjection API requires user consent for each capture session on Android 14 and later, and the foreground service must use the relevant service type. Do not promise invisible stream restart or universal boot-time operation. Validate permissions and first-frame delivery on each supported image/OEM class. See [Android MediaProjection guidance](https://developer.android.com/media/grow/media-projection) and the project's [stream observability report](../2026-09-25/ANDROID-STREAM-OBSERVABILITY.md).

Tasks are predefined, bounded DAGs/Lua actions. Current source review documents a risk that coroutine timeout alone may not preempt a synchronous CPU-bound LuaJ loop. Only reviewed scripts should run until an instruction budget/preemption test closes that risk. Server-side `queued`/`sent`, a socket ACK, or a local screen icon are not terminal task receipts or proof of browser video decode.

## Release contract

The production signing keystore is an identity for the Android package, not a disposable build secret. The production workflow expects these GitHub Actions secrets:

- `ANDROID_RELEASE_KEYSTORE_BASE64`
- `ANDROID_RELEASE_KEYSTORE_PASSWORD`
- `ANDROID_RELEASE_KEY_ALIAS`
- `ANDROID_RELEASE_KEY_PASSWORD`
- `ANDROID_RELEASE_CERT_SHA256` — the expected signer certificate SHA-256, colon-separated or plain hex

The fingerprint must come from the already-approved release certificate and must match packages that are expected to update in place. Never replace it with the CI key. Never post the keystore, passwords, enrollment keys or device tokens in chat or commit them. If the original signing key is lost, Android will reject an in-place update signed with a different key; resolve package migration as a separate operation.

Version source now declares **1.2.35 / 10235**. The only production package is `com.sphereplatform.agent` from `enterpriseRelease`; the dev flavor has a different application ID/version suffix and is not an update for that package. Enterprise server/key defaults remain blank unless the chosen supported provisioning mechanism supplies them. This audit deliberately does not embed a tunnel URL or enrollment secret, publish OTA metadata, create a GitHub tag/release, or deploy the APK repository.

Before a device rollout, require all of the following:

1. CI passes tests, lint, signed smoke builds and signer verification.
2. A production-signed artifact has the expected package, version, certificate fingerprint and recorded SHA-256.
3. The OTA entry points to that exact artifact/hash and an already installed canary reports the new version and artifact identity.
4. A remote canary proves cold start, clone rebind, management reconnect after network loss on either side, diagnostic upload over primary and backup routes, OTA install/receipt, task terminal receipt, and a moving-screen stream whose frames decode/render in the browser.
5. Canary soak, battery/resource measurements and rollback evidence pass before expanding to 20–30 devices.

Without the production key, configured provisioning route, OTA catalogue read and a controlled remote device, the release is **not accepted for rollout**, regardless of local unit-test results.

## Validation record

Validation on this working tree, 28 September 2026:

| Check | Result | Scope and boundary |
| --- | --- | --- |
| `./gradlew test` | **PASS** — four variants, 691 tests each (2,764 total executions), 0 failures, 0 errors, 1 skip per variant. | The skip is the existing documented `ConfigRecoveryTest.public discovery of baked route retains locally provisioned enrollment credential`; this is JVM/Robolectric coverage, not a remote-device test. |
| `./gradlew lint --no-parallel --max-workers=1 --no-configuration-cache --no-daemon` | **PASS** — 0 errors, 74 warnings. | Warnings: 45 dependency freshness, 12 unused resources, 3 AGP freshness, 3 text localization, 2 hardcoded `/sdcard` paths, and 9 individual platform/API/style findings. This is lint-clean for errors, not warning-free. Sequential execution also avoided a repeatable Windows lint-cache file-lock issue seen when reusing a daemon after tests. |
| Release task without signing inputs | **PASS (negative test)** — `assembleEnterpriseRelease` exited nonzero with the explicit missing/invalid signing configuration message. | Proves the task no longer accepts a missing signer; it does not prove the production secret exists in GitHub. |
| `assembleDevRelease assembleEnterpriseRelease` with a disposable local test key | **PASS (packaging smoke only)** — `apksigner verify` passed for both; `aapt` reported `com.sphereplatform.agent.dev` / `1.2.35-dev` and `com.sphereplatform.agent` / `1.2.35`, both code `10235`. | These were signed with a temporary non-production certificate. The exact smoke APKs and keystore were removed after verification. They must not be installed as production updates. |
| GitHub Android CI | **PASS** on `2ad9fb3` in 12m32s: tests/lint, debug + both signed release smoke builds, signature verification and evidence upload all succeeded. | That runner reported a Gradle cache-restore HTTP 400 and deprecation annotations from the old action majors; the job still completed successfully. The Android workflows now use Node 24-compatible action majors: checkout v7, setup-java v6, setup-gradle v6 and upload-artifact v6. Final CI for those action updates is pending. See the [official checkout](https://github.com/actions/checkout/releases), [setup-java](https://github.com/actions/setup-java/releases), [Gradle Actions](https://github.com/gradle/actions/releases) and [upload-artifact](https://github.com/actions/upload-artifact/releases) releases. |
| Production release, OTA, and remote runtime | **NOT RUN**. | No production keystore/certificate was available to this local build; no tag, release, OTA catalog mutation, server deploy, or device install was performed. The candidate remains source-only until the existing production signer and remote canary gates are verified. |

The earlier `1.2.34` unsigned output is historical baseline, not candidate evidence. The only local signed outputs in this check used a disposable certificate and were deleted. No live endpoint or device was changed in this audit.
