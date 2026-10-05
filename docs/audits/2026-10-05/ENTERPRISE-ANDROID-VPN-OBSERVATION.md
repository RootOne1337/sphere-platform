# EP-010 Stage B foundation: independently timed Android VPN observations

**Date:** 5 October 2026, Asia/Yekaterinburg.
**Implementation status:** source implemented; committed image/runtime receipt must
be recorded separately below. EP-010 remains OPEN; acceptance remains **9/41**.

[Current state](../../operations/CURRENT-STATE.md) ·
[Delivery and coverage contract](ENTERPRISE-LIVE-COVERAGE-NEXT.md) ·
[Installed Stage A evidence](ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json).

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
over **231 files** passed. Expanded source tests, exact production dependencies,
generated OpenAPI and runtime verification must be recorded with final outcomes.

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
through the existing guarded PostgreSQL/Redis fixture. Those tests must not be
reported as executed merely because the disposable probe passed.

No migration, APK release, VPN rotation/provision/revoke, script execution, public
IP probe or tunnel replacement belongs to this slice. The independent fleet
producer, separate tenant coverage endpoint, infrastructure tunnel observations,
coverage UI and mixed stream/script load remain OPEN. Windows disk/RAM writer
attribution remains unresolved.

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
