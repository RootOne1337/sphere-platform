# Bidirectional recovery · native acceptance, 15–16 September 2026

The initial 15 September trials target only the new pilot and the two owned Android 9
emulators. APK versions were 1.2.5 on the first and 1.2.6 on the second. Backend
12249b1 and web 6dea6b4 were running. Old containers retained IDs/images/start times.

| Fault | Actual blocked interval | Observed return after restore | Commands, DAG and frames |
| --- | --- | --- | --- |
| Second APK UID, IPv4 + IPv6 DROP | 78.931 s | 2.484 s | Passed, same APK PID |
| Public gateway pause, both APK paths | 82.835 s | 0.782 / 5.282 s | Passed on both, same PIDs |
| APK UID DROP plus public gateway pause | 83.202 s | 0.859 / 12.625 s | Passed on both, same PIDs |
| Shared Nginx pause, web and APK paths | 76.465 s | 74.312 / 79.641 s | Eventually passed; excessive delay AUD-124 |

Times are observation upper bounds, not latency percentiles. Devices were checked
sequentially, and the first device's command/DAG preceded the second timing sample.
The first three probes requested 75 s but added diagnostic overhead between sleeps;
the retained runner uses absolute sampling deadlines. During each fault the
canonical server WebSocket sessions disappeared; afterwards new sessions appeared.
Each affected APK executed an echo and the pinned safe 13-node success path, with
native node receipts checked for order, count, device and version. Existing Python
viewers received fresh binary frames without reopening in the first three trials.

The same real browser tab retained the selected cards, showed offline placeholders,
and decoded both home screens again without F5 or another Start click. On common
Nginx loss, its silent-socket watchdog displayed `Переподключение…` over stale
pixels. The list's separate 30 s polling interval can delay the Online/Offline badge;
that badge is not a frame-delivery acknowledgement. Python viewers reconnected in
the common-ingress case. Temporary connection/timeout/control-unavailable messages
are retained in evidence, not hidden. Crash buffers stayed unchanged and APK PIDs
remained stable during each trial.

## Forward release 1.2.7: repeated acceptance, 16 September

Both devices received source `0f257fe` / versionCode 10207 through their own OTA.
The second device first passed Android-only loss while the first was still 1.2.5;
the combined and shared-Nginx trials below used 1.2.7 on both. Each affected device
returned a new authenticated session, executed echo and the pinned native DAG,
resumed frames, retained its process and had unchanged crash buffers.

| Fault | Actual blocked interval | Observed return after restore |
| --- | --- | --- |
| Second APK UID, IPv4 + IPv6 | 75.786 s | 2.015 s |
| APK UID plus public gateway | 76.729 s | 0.516 / 5.141 s |
| Shared Nginx, same pre-fix scenario | 76.411 s | 0.531 / 6.062 s |

These are bounded observations with the same sequential timing caveat above.
The final shared-Nginx retest used protocol viewers, not a new browser UI trial.
All injected rules/pauses were removed and protected container identities remained
unchanged. Six capture/stop cycles on the new APK, including overlapping viewers,
released MediaProjection automatically. [Installed release evidence](evidence/android-reconnect-native-10207.json).

## Test corrections and reproducibility

The first browser fixture incorrectly expected Android sessions to survive a
shared Nginx pause. It timed out despite recovery; its failed record is preserved.
The corrected fixture expects new sessions and passed. No change to application
code was needed to correct that test assertion. All fault rules and pauses were
removed, including on failed runs.

Retained runner: `scripts/pilot/network_recovery_probe.py`. It requires the private
pilot directory, validates project/package scope and the exact reviewed DAG before
mutations, starts a separate hidden cleanup guard, saves private correlated evidence,
and checks PIDs, crash buffers, sessions, task receipts, frames and protected
container identities. Run from the repository, only against the explicitly owned
two-device pilot:

```powershell
python -m scripts.pilot.network_recovery_probe --pilot-dir .local-pilot --mode android
python -m scripts.pilot.network_recovery_probe --pilot-dir .local-pilot --mode server
python -m scripts.pilot.network_recovery_probe --pilot-dir .local-pilot --mode both
python -m scripts.pilot.network_recovery_probe --pilot-dir .local-pilot --mode browser
```

`browser` pauses the shared Nginx, so Android also loses its server path. ADB is
used to inject scoped packet loss and read diagnostics; it never performs APK
reconnect, install, permission grants or scenario actions. The cleanup guard cannot
run while Windows/Docker is down; after host failure inspect the private guard
journal before another drill. This is a development fault tool, not a startup service.

## Defect found and remaining work

The fourth trial exposed **AUD-124**, subsequently fixed and accepted on installed
APK 1.2.7: [regression, OTA and repeated fault results](ANDROID-RECONNECT-DEBT.md).
Before the fix, the Android retry loop reset its attempt and circuit counters only
when a session returned normally. A healthy authenticated session later ending
with a network exception retained failures from earlier outages. The tenth
accumulated failure opened a 60 s circuit pause plus the old backoff.
The failing source regression, fix and installed retest are retained in [AUD-124](ANDROID-RECONNECT-DEBT.md).

These checks do not establish independent provider failover, host reboot recovery,
physical-device/API26–35 compatibility, hundreds of simultaneous reconnects, packet
loss/jitter distributions or an eight-hour successful soak. The earlier failed
night remains failed. VPN, complete Task Engine history (AUD-120) and interactive
diagnostic noise (AUD-121) remain separate open work.

[Machine-readable evidence](evidence/network-recovery-native-20260915.json) ·
[Connector incident](CONNECTOR-RECOVERY.md) · [Web source regressions](WEB-STREAM-RECOVERY.md)
