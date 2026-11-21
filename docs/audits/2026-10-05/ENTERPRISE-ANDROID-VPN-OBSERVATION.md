# EP-010 Stage B foundation: independently timed Android VPN observations

**Date:** 5 October 2026, Asia/Yekaterinburg.
**Implementation status:** source `d656b579` installed at 16:11:09 UTC;
independent clock and atomic ownership foundation verified below.
EP-010 remains OPEN; acceptance remains **9/41**.

[Current state](../../operations/CURRENT-STATE.md) ·
[Delivery and coverage contract](ENTERPRISE-LIVE-COVERAGE-NEXT.md) ·
[Installed Stage A evidence](ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json) ·
[Stage B frozen evidence](ENTERPRISE-ANDROID-VPN-OBSERVATION-EVIDENCE.json).

## Concrete defects and reproduction

An ordinary pong refreshed `last_heartbeat` while retaining a previous `vpn_active`
flag. Neither pong nor standalone telemetry attached an independent receipt time
or reporting session. A current heartbeat could therefore make an old VPN flag
look current. Standalone telemetry also lacked the session check already present
in the pong path. The pong check was a separate read followed by an unconditional
write: replacement between those operations could overwrite newer presence.

The first 24 isolated cases failed before implementation, with no collection/setup
errors. They covered report age 0/119/120/600 seconds, future times, old/missing
ownership, connecting/offline presence, unrelated heartbeat renewal, strict boolean
reports and replacement between the read and write. Missing new metadata/signature
also failed as new-contract expectations; not every failure represents a separate
production defect.

The implementation adds a server receipt timestamp and session identity for a
strict boolean `vpn_active` report. A message cannot supply the trusted timestamp
or owner. `null` explicitly clears the observation; a malformed non-boolean value
does not renew it. Other telemetry is validated before persistence. A malformed
telemetry bundle does not destroy heartbeat liveness.

## Read semantics

| Condition | `vpn_active` | Observation state |
|---|---|---|
| Current online/busy session; fresh heartbeat; report age in `[0,120)` seconds | Explicit true or false | `fresh` |
| Same ownership and fresh heartbeat; report age at least 120 seconds | `null` | `stale` |
| Missing report/timestamp/session; legacy record | `null` | `unknown` |
| Reporting session differs from current owner | `null` | `unknown` |
| Offline/connecting or stale/missing heartbeat | `null` | `unknown` |
| Future or naive observation time | `null` | `unknown` |

An independently fresh false report means the Android agent reported its managed
VPN service inactive. Unknown never means false. The 120-second bound is distinct
from the recorded router-handshake threshold of 180 seconds. Server receipt time
does not measure the Android clock, public IP or whether VPN traffic succeeds.

Single and bulk cache reads project freshness without rewriting retained Redis
evidence. Bulk reads share one UTC observation time. The device registry and main
detail response add `vpn_observed_at`, `vpn_observation_state` and
`vpn_observation_max_age_seconds`; existing `vpn_active` becomes null when
unconfirmed. Existing UI null handling remains compatible. This is a backend
contract foundation, not a new coverage dashboard.

The legacy `/{id}/status` service additionally returns a separate older string
presence cache (`live`); this slice does not redefine that string as full Android
telemetry. No consumer should use it as proof of VPN state.

## Atomic ownership and resource budget

Pong and standalone telemetry now share a validated Redis merge. `WATCH` fences
the ownership read through `MULTI/EXEC`. On conflict the merge rereads the owner,
with at most three attempts. A standalone report cannot create presence, adopt an
unowned record or promote connecting to online. An authenticated pong preserves
the existing disposable-presence recovery after eviction. A known newer owner is
never overwritten. Rejected writes do not publish a first-pong confirmation or
replace stream diagnostics.

This uses the deployed Redis 7.2 transaction mechanism and adds no dependency.
[Official Redis transaction documentation](https://redis.io/docs/latest/develop/using-commands/transactions/)
(reviewed 5 October 2026) describes conditional execution after modifications,
expiration or eviction of a watched key. A lost transaction connection does not
turn the write into an accepted observation. The existing full heartbeat interval
remains 30 seconds; no APK telemetry polling or timer frequency is increased.

The merge watches one existing per-device key and writes one bounded status. It
creates no background task, observation history, queue or extra per-event file.
Existing 120/90/3600-second presence TTLs are preserved. WATCH adds round trips;
1000-device throughput and reconnect-storm latency still need their own acceptance.
When the presence key is absent, this slice does not invent a distributed socket
registry: the existing authenticated-pong recovery contract still applies. Other
non-agent status writers are outside this ownership change.

## Checks and boundaries

Initial related source run: **282 passed / 0 skipped**. Changed-file Ruff and mypy
over **231 files** passed. Expanded source tests and exact-image checks are
recorded separately so a local dependency run is not presented as image proof.

Expanded source run: **444 passed / 0 skipped** across device status, WebSocket,
main device API and VPN suites. It includes 31 observation/ownership cases and
four main list/detail freshness cases. These runs use SQLite/FakeRedis locally;
the separate Redis probe below is the real-service check performed so far.

A disposable **Redis 7.2.12** probe with two independent clients reproduced both
pong and standalone-telemetry replacements immediately before `EXEC`. The newer
owner survived both; an explicit false report from the new session became fresh.
The probe used a loopback-only ephemeral port, 128 MiB container limit, no
persistence and no production credentials/services; the probe container was
removed afterwards. It proves Redis transaction behavior for these cases, not
PostgreSQL RLS, Android VPN traffic or fleet load.

New opt-in production regressions repeat both races against isolated real Redis
through the existing guarded PostgreSQL/Redis fixture. Both subsequently passed
in source CI; the disposable probe alone was not used as their execution proof.

No migration, APK release, VPN rotation/provision/revoke, script execution, public
IP probe or tunnel replacement belongs to this slice. The independent fleet
producer, separate tenant coverage endpoint, infrastructure tunnel observations,
coverage UI and mixed stream/script load remain OPEN. Windows disk/RAM writer
attribution remains unresolved.

## Committed image and live receipt — 5 October 2026

API source **`d656b579a77a2997ea7012c9aad7fb3425e07edd`** was built from a
bounded committed Git archive. Installed image:
**`sha256:deea9072fb3e86efd16e2b4a65a8944492ba0821fd3bfa5db31e5443c2dd6455`**.
Only the backend was replaced at **16:11:09 UTC / 21:11:09 UTC+5**. All **45**
neighboring container identities, image IDs, start epochs, mounts and log
configuration were compared before/after and preserved. Backend mounts and log
rotation were preserved; readiness and the build endpoint confirmed the source.
Rollback remains the previously installed Stage A API `66714f26`.

The same image, without a backend source mount and with network disabled, passed:

- **444** device-status, WebSocket, device-API and VPN tests; no failures/skips.
- **35** resource, multiprocess and registry-lifecycle tests; no failures/skips.
- mypy over **231 files** and Ruff for backend plus the **five changed test files**.
- Generated API documentation `--check` with shipped FastAPI **0.136.3** and
  Pydantic **2.9.2**; no application lifespan or services were started for this.

First read-only harness attempts hit unwritable tool caches; corrected flags use
`--no-cache`/`/tmp/mypy`. A full-tests Ruff attempt in the packaged context also
hit import classification differences because extra repository scripts were not
packaged. The exact-image Ruff receipt therefore names its narrower scope;
subsequent source CI passed full repository lint. These harness retries are
retained privately and are not counted as product regressions or additional tests.

Six read-only samples at **16:20:04–16:20:19 UTC** each returned **19 registered,
14 online, 5 offline, 0 connecting**. All 14 online agents provided independently
fresh explicit **false** managed-VPN reports; five offline devices remained
**unknown**, not false. Across the samples fresh report ages were **0.333–29.749 s**.
Bulk status verified current/reporting session equality and online/busy presence.
This validates live receipt/projection compatibility; it does not prove Android
VPN traffic, a live stale-report fault injection, uninterrupted uptime or SLA.

Existing resource history remained `cpu=ready`, `memory=ready`,
`memoryLimit=ready`; `cpuQuota=empty` stayed distinct from zero. HTTP history and
readiness responded. The private HTTP session was closed with **204**; its
subsequent authorized read returned **401**. No human browser session was logged
out, and no Android command, APK reinstall, OTA or tunnel change was performed.

### Source CI and browser compatibility

For **this exact API source**, [backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/37338164228),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/37338164232)
and [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/37338164321)
all completed successfully. Backend unit/real-service step: **2722 passed,
30 skipped, one warning; coverage 79.78%**. Both new replacement races explicitly
passed in the real-service fixture. Image bootstrap, full lint/mypy, security,
RLS inventory, OpenAPI verification, Redis memory/persistence acceptance and
Alembic single-head jobs passed. Skipped tests are not presented as passing.
The earlier Stage A stale-schema CI failure remains in its historical receipt;
this green run resolves the schema check for `d656b579`, not retroactively.
Later documentation-only head CI must be evaluated on its own.

Actual in-app browser `/monitoring` and `/devices` were inspected at the normal
**724×884** viewport with no new viewport override. The build label reported
**W:cb5b3f91 A:d656b579** and explicitly disclosed different revisions. Existing
resource panels appeared in DOM, the registry showed **14/19 online**, and no
warn/error entries were returned by the bounded console read. Document width
matched viewport width; the dense registry uses a contained horizontal viewport.
These three native JPEG captures show the visible viewport, not a complete page
or newly designed VPN coverage UI:

- [Monitoring after API replacement](assets/android-vpn-observation/monitoring-live.jpg)
- [Real registry](assets/android-vpn-observation/devices-live.jpg)
- [Monitoring final view](assets/android-vpn-observation/monitoring-viewport.jpg)

The existing registry access chip is **assignment** (`vpn_assigned`), not the new
Android service observation. This slice does not relabel it or claim that the new
state/timestamp is already exposed as a dedicated UI panel. That richer coverage
presentation and fleet producer remain part of open EP-010 work.

### Portable evidence verification

The [manifest](ENTERPRISE-ANDROID-VPN-OBSERVATION-EVIDENCE.json) pins 12 Git blobs,
the exact image, 14 receipt/XML files, three capture hashes, unchanged 9/41 ledger,
real Redis proof, source CI and the finite live observations. Run:

```powershell
python -m scripts.audit.validate_android_vpn_observation
```

The [checker](../../../scripts/audit/validate_android_vpn_observation.py) verifies
frozen artifact integrity and contracts. It performs no live HTTP call, service
restart or device action and cannot certify current health or close EP-010.
The current entry/report link check covered **12 documents, 774 local links and
19 anchors**; all resolved. Historical evidence manifests remain unchanged.

## Implementation references

- [Read projection and observation contract](../../../backend/schemas/device_status.py)
- [Atomic Redis merge](../../../backend/services/device_status_cache.py)
- [Pong persistence](../../../backend/websocket/heartbeat.py)
- [Current-session standalone telemetry](../../../backend/api/ws/android/router.py)
- [List/detail enrichment](../../../backend/api/v1/devices/router.py)
- [Public response](../../../backend/schemas/devices.py)
- [Clock, old-agent and ownership cases](../../../tests/device_status/test_vpn_observation_freshness.py)
- [Main API response tests](../../../tests/devices/test_vpn_observation_api.py)
- [Real-service ownership regressions](../../../tests/production/test_presence_recovery.py)
- [Generated OpenAPI](../../openapi.json)
