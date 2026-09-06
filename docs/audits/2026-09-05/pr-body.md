## Problem and resulting behavior

Tenant users could escalate roles or delegate excessive API-key privileges,
device credentials were not consistently bound to the addressed device, and task
results/account selection crossed authorization boundaries. Android refresh and
agent HTTP contracts also disagreed with the backend.

The changes enforce delegation and device/tenant boundaries, persist and rotate
device refresh credentials, repair PC registration and agent HTTP contracts, and
support startup from an immutable image. Android transport cleanup is cancellation
safe and automatic HTTP credentials are limited to the management origin.

Duplicate DAG delivery now uses a durable receipt instead of cancelling and
repeating device actions. Terminal results remain in the Android journal until
the backend acknowledges its PostgreSQL commit. Failed DAGs remain failed, and
Redis failure cannot prevent committing the task result. Queue acquisition and
conditional release use atomic Lua; synchronous command waits have real deadlines
and ignore intermediate acknowledgements.

Orchestrator account updates now enforce tenant ownership, record a separate
processing receipt and preserve terminal task outcomes. Device-row locking
serializes task creation; missing Redis presence no longer causes a retry to
replace work that the APK may still be executing. Batch counters serialize
across result handlers and watchdogs, whose queue deadline now remains UTC.
Live task progress/logs require ownership for both API reads and device writes.
Authenticated heartbeats reconstruct evicted Redis presence on the next pong.
Cancel/force-stop now lock and refresh the task before validating its status, so
a concurrent committed result cannot be overwritten or trigger a late stop.
The mutation retains the tenant filter; terminal-state conflicts return 409.

The production Compose override clears inherited private ports and development
application commands, users and source mounts. Both base/production and
base/full/production combinations are checked with synthetic configuration only.
Backend CI now enables the isolated PostgreSQL/Redis regressions, has a bounded
20-minute test job and retains JUnit/coverage artifacts on failure.

VPN assignment now validates the active device in the caller's organization,
serializes concurrent requests and returns the original PSK and saved route choice
on retry. PostgreSQL owns global held-IP uniqueness and commits provisioning/revoke
intents before router effects. Completion checks the operation generation; unknown
outcomes retain their address and reject blind retries. Redis loss or stale free
lists cannot reissue an address. Lifecycle commits use separate sessions from HTTP
callers. DELETE percent-encodes peer keys and accepts only 200/204; generic 404
requires reconciliation. The authoritative provider inventory/reconciler remains
unimplemented, so pending operations deliberately retain their IP.

VPN health polling now authenticates to the router, validates observations and
preserves last known state on failed or malformed responses. Missing/zero
handshakes no longer trigger peer provisioning. Reconnect uses the stored PSK.
Background observations commit independently per tenant; conditional writes skip
revoked peers and prevent late poll responses from overwriting newer handshakes.
The production command publisher is still a stub, so these fixes do not claim
successful delivery to Android or an established tunnel.

Account password disclosure requires a separate credential-read permission held
by organization administrators/owners and platform administrators. Ordinary
account readers cannot reveal passwords; allowed responses use no-store and retain
the tenant filter. Create/update/import/auto-registration encrypt recoverable
credentials before persistence using a separate Fernet key ring and an envelope
bound to account/tenant UUIDs. The legacy plaintext is cleared in the same write.
Reveal and dispatch reject unmigrated, corrupted or unavailable credentials.
The backend image includes a read-only-by-default migration/verification CLI with
bounded transactions, restart and rotation support. Indirect script access and
credential-bearing APK/cache/log surfaces remain under audit.

Android text input no longer emits raw or shell-encoded values to Timber. The
file logger is active in release and its content enters diagnostic uploads;
the input command remains unchanged. Regression tests exercise the real executor
and logging API with a fake root process. Historical logs still require review.

Root input no longer blindly resends a command after an ambiguous pipe write or
flush failure. The broken session is invalidated and a distinct unknown-outcome
error stops DAG retry/failure routing and nested loops; LuaJ host errors preserve
that classification. The failed receipt survives duplicate delivery. Live touch
handlers contain the failure without another send or an uncaught coroutine error.
A successful pipe flush still does not prove physical execution or exit status.

DAG controls now require an explicit task target and atomically match it to the
active Android execution. Delayed cancel/pause/resume cannot affect a different
DAG; missing or inactive targets return failed control receipts. Watchdog includes
the target, and user stop has a distinct control ID so its ACK cannot falsely
complete a task after Redis/SQL rollback. Acceptance remains separate from
physical stop; durable cancellation and ordering within a task remain open.

Audit selection and resource identity, request log context and HTTP metric labels
now use the ASGI path rather than a URL reconstructed from Host. Malformed Host
headers could otherwise suppress or relabel a successfully committed mutation's
audit entry. Real API/PostgreSQL regressions preserve the routed resource identity.

## Validation

- Android enterprise debug unit suite: **333 passed**.
- Combined backend/PC, PostgreSQL/Redis and deployment regressions: **1035 passed**.
  This includes **179 real-service tests** and **6 Compose configuration tests**.
  Coverage is **66.61%** and passes the unchanged **65%** gate with two-decimal
  precision. No threshold or coverage scope was weakened. Two additional
  regression tests exercise the 64.98% rejection and exact 65.00% boundary. Long load/soak profiles require a prepared API
  environment and are excluded from the ordinary PR command.
- Reproductions and before/after evidence are indexed in
  [the audit report](docs/audits/2026-09-05/AUDIT-REPORT.md).
- Tests cover PostgreSQL row/commit behavior, Redis atomicity and lost responses,
  tenant/device authorization, command duplicates, simulated process restart,
  storage failure, failed DB commit and Redis outage.

## Remaining blockers and rollout constraints

This remains an **ongoing draft audit**, not a production-readiness assertion.
The former strict xfail now passes: committed PostgreSQL assignments own dispatch
intent, row locks serialize workers, and receipt-based retries survive lost
transport responses. n8n/orchestrator producers use the validated task contract;
resolved account payloads determine DAG cache identity. Full RLS rollout,
orchestrator creation/pipeline recovery, VPN/deployment and the remaining
component audit are still open. Legacy running assignments require rollout reconciliation.

Apply migrations through `20260906_account_ciphertext` before a backend rollout; previously
issued refresh tokens require device re-enrollment. The command journal retains
512 receipts for seven days with a 1 MiB cap and rejects new DAGs when full.
Interrupted execution returns an explicit unknown-outcome failure; this does not
claim exactly-once effects. CPU/RAM/FPS, physical-device compatibility and 10–64
emulator capacity have not been measured.

n8n/MinIO ingress, runtime database roles, durable OTA/log storage, task-specific
stop acknowledgements, cancellation under Redis/commit failure, batch/scheduler
cancellation and post-commit webhook delivery remain open. Existing
incorrect batch counters and legacy task metadata require reconciliation.
Update all backend writers before enforcing explicit control targets in the APK;
old watchdog messages lack a target and will be rejected. Old APKs still need
updating to prevent controls from affecting a different task. See the
[control contract](docs/security/task-control-protocol.md) for rollout limits.

The VPN migration refuses duplicate held IPs, invalid addresses/network prefixes
and downgrade with pending intents. Reconcile PostgreSQL/router inventories and
stop legacy allocation writers before rollout; old code still provisions before
SQL ownership. The 64-concurrent-assignment regression uses real PostgreSQL and
mock router responses and is not an Android emulator capacity measurement.

Account encryption additionally requires an independent `ACCOUNT_CREDENTIAL_KEYS`
secret, quiesced legacy account/orchestrator/dispatch writers, explicit credential
backfill and verification before resuming work. Alembic alone does not migrate
passwords; missing keys or legacy records block credential use. Encrypted rows
prevent schema downgrade. Old backups/WAL may still contain plaintext, and restore
requires the matching keys. No deployment key or production data was changed.

A real APK-to-backend runtime test is incomplete: automatic approval review
rejected starting the isolated local API with `blocked by policy`; no workaround
was used. CI results must be read on the latest PR head; dependency/security work
is still open. No merge or deployment has been performed.

The report corrects the earlier ACK-discriminator assessment: the original main
WebSocket loop already supported untyped legacy acknowledgements. The explicit
type standardizes the contract; it does not prove all original replies were lost.

The earlier claim that 64.98% necessarily blocked CI was incorrect: the default
precision rounded it to 65% for the exit decision, despite a FAIL summary.
`1335a72` fixes precision and adds a real coverage CLI boundary regression.
`31077b3` fixes the subsequent mypy timestamp-narrowing diagnostics. The latest
checks must be evaluated on this updated head, not inferred from historical jobs.
