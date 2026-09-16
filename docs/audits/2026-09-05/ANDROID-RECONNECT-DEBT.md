# AUD-124 · independent outages accumulated Android retry debt

**High · operational recovery delay · 16 September 2026 local time.**

## Evidence and cause

Repeated native network drills successfully reconnected both APKs, executed DAGs
and resumed streaming. After another shared-ingress outage, however, the APK log
reported attempt 8, then 9, `Circuit OPEN after 10 failures`, a 60-second pause and
another 25.5-second retry delay. Successful authenticated sessions had occurred
between the earlier outages. Recovery was eventually observed 74.312 / 79.641 s
after restoration. Both processes remained alive, so automatic crash recovery was
not the cause. [Native evidence](NETWORK-RECOVERY-NATIVE.md).

`SphereWebSocketClient.reconnectLoop` cleared the attempt/consecutive-failure
counters only after `connectOnce` returned normally. A successfully authenticated
session remains inside that call for its entire lifetime. An eventual network
failure completes its disconnect deferred exceptionally and bypasses the reset.
Thus distinct outages count as consecutive failures. The circuit pause and long
backoff accumulate; even the first-outage discovery refresh no longer runs.

## Reproduction and minimal fix

The production-loop regression `authenticatedRecoveriesResetOldFailureDebt`
authenticates, loses transport, recovers and repeats twelve times. It requires
each independent outage to retain the normal jittered 1–2 s first retry and to
request discovery again. The old implementation fails after the second outage.
The companion case confirms TCP open without `auth_ok` does not clear failure debt.
Before the fix: 11 lifecycle tests, one failure.

`connectOnce` now invokes a private callback on the reconnect coroutine after the
existing target-bound authentication acknowledgement completes successfully. That
callback resets attempt, consecutive failures, open-circuit deadline and old route
failure. An exceptional disconnect then becomes the first failure of a new outage.
Callbacks from expired generations and unauthenticated sockets cannot perform this
reset. The backoff/jitter/circuit limits and normal-close pacing remain intact.

Affected files:

- `android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt`
- `android/app/src/test/kotlin/com/sphereplatform/agent/ws/WebSocketLifecycleTest.kt`
- `android/version.properties`: forward release 1.2.7 / 10207, retaining AUD-119.

Both flavors' complete WebSocket suites pass after the fix. Full Android run:
579 dev tests pass; enterprise has 578 passed and one existing baked-route fixture
skipped. There are zero failures/errors across 43 suites per flavor.
[Machine-readable regression evidence](evidence/android-reconnect-debt-regression.json).
Native 1.2.7 acceptance now passes on both owned Android9 devices. Canary and
stable OTA returned commands in 9.687 / 9.671 s, with installed hashes
verified and no ADB install, launcher or manual permission action. After a 75 s
Android UID block the canary returned in 2.015 s; the subsequent combined outage
on the updated pair returned in 0.516 / 5.141 s (sequential observation upper bounds).
Each affected device executed echo and the pinned DAG, resumed frames, kept its
process and had unchanged crash buffers. Three capture/stop cycles per device,
including overlapping viewers, passed and released projection automatically.
[Installed release evidence](evidence/android-reconnect-native-10207.json).

The original shared-Nginx failure scenario was then repeated on both 1.2.7 APKs:
76.411 s blocked, recovery observed at 0.531 / 6.062 s. Both returned new
sessions, commands, ordered DAG receipts and frames, with unchanged processes and
crash buffers. This final drill used protocol viewers; the separate real-browser
acceptance of the unchanged web build is recorded in the network matrix.
The second APK's logs independently confirm the reset: the first retry of the
three separate outages starts at attempt 1, with 1,788 / 1,262 / 1,093 ms backoff.
Further failed handshakes during each outage still increase backoff normally.
Sanitized sequences and source-log hashes are retained in the release evidence.

All workflows for source 0f257fe passed: [CI archive](evidence/ci-0f257fe-summary.json).

## Residual risk

Recovery still depends on DNS, TLS, routing, discovery freshness and backend health.
Truly consecutive failed handshakes still back off and can open the circuit.
Authentication success is the reset boundary; a server that authenticates and
immediately drops every connection can cause repeated 1–2 s retries, spread by
jitter. This patch does not promise zero downtime, guarantee an unavailable
provider, or establish hundreds-device reconnect capacity. Physical-device and
long-duration acceptance remain open.
