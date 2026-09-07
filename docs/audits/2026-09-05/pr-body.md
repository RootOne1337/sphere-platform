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

Batch cancellation now locks eligible tenant tasks in stable ID order, then
locks and refreshes the batch before status validation or queue effects. This
preserves concurrent committed results, rejects all terminal batch states and
prevents repeated cancellation effects. Cancelled tasks receive finished_at;
RUNNING tasks remain active. Sixteen PostgreSQL cases cover row-owner waits,
stale snapshots and Task-to-Batch lock ordering. Wave producer lifecycle and
durable cancellation delivery remain separate open work.

Scheduler cancellation likewise locks and refreshes eligible tenant task and
pipeline rows before effects, preserving results committed by competing writers.
Control signing time is generated after SQL waits. Sixteen PostgreSQL cases cover
result races, allowed transitions, legacy-link tenant guards and control TTL.
This does not fence all pipeline executor writes or introduce a stop outbox.

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

Android loop diagnostics no longer stop body execution at 200 entries. All
configured actions still run within the explicit execution limits, and failures
past the log cap retain their abort policy. Coroutine cancellation in a suspended
body action propagates before the next device command. Five new runner regressions
failed before the fix and pass now; bounded log size and exact truncation are checked.

Accepted wire controls are checked before each action and retry, including
nested loop bodies. Paused bodies wait for resume or cancellation; cancellation
escapes body/retry failure handling and produces a failed terminal DAG receipt.
A stop observed during the final action cannot report success. Six additional
real dispatcher/runner/journal regressions failed before the fix and now pass,
including replay of the cancelled task's durable receipt. Checkpoints remain
cooperative and do not interrupt a running root/Lua action or freeze timeouts.

Audit selection and resource identity, request log context and HTTP metric labels
now use the ASGI path rather than a URL reconstructed from Host. Malformed Host
headers could otherwise suppress or relabel a successfully committed mutation's
audit entry. Real API/PostgreSQL regressions preserve the routed resource identity.

The tested Python dependency set now includes the PyJWT, Starlette and pytest
security releases with compatible FastAPI/Pydantic/pytest-asyncio versions.
Backend and PC settings pins agree; CI resolves both requirements together,
checks consistency and scans both. Twelve JWT controls preserve fixed-key,
single-algorithm verification and reject forged tokens across access/logout.
The joint local scan reports no known vulnerabilities in the resolved Python set;
other ecosystems and application blockers remain under audit.

The APK operator guide is aligned with actual WS authentication, provisioning,
flavors/signing, command/ACK payloads and component names. Previous claims of
100% uptime and application-level OTA certificate pinning were unsupported and
have been removed; device, signing, installation and recovery limits are explicit.

The HTTP schema/catalog now regenerate from the registered application and CI
rejects stale artifacts. The previous snapshot omitted 30 routes; the updated
catalog lists 162 operations across 126 paths. Manual Tasks/Batches, signing,
WS authentication and documentation URLs are reconciled with source. Other manual
component guides remain under review; declared schemas do not certify runtime.

Wave admission no longer marks QUEUED work COMPLETED or sends a false completion
callback. Rejected device slots contribute to SQL outcome counters under the same
lock as device results. Unexpected/database faults abort the current wave while
retaining earlier commits. Thirteen real PostgreSQL regressions include concurrent
outcome writes and an actual statement error. Batch callback delivery and durable wave recovery remain open. Batch startup now commits
the parent before launching independent work; four regressions cover parent
visibility, commit/mapping failure and real ASGI submission/task admission.

Wave admission and batch cancellation now share a transaction advisory lock
before task/device row locks. A cancellation sees in-flight inserts after their
commit, and later waves check fresh tenant-scoped status before admitting work.
Results/watchdogs retain CANCELLED while counting surviving task outcomes.
Thirteen PostgreSQL regressions cover both race orders, cancellation between waves,
terminal/tenant guards, rollback lock release and overlapping reverse-order device
sets. All workers must be updated to honor this fence; physical stop and durable
cancellation delivery remain open.

## Validation

- On code revision `87092d2`, [backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34133092803)
  passed Tests, Lint, Security, Alembic and static RLS checks;
  [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34133092736)
  passed build and unit tests. This is a revision-specific snapshot; consult PR
  checks for subsequent documentation or code commits.

- Android enterprise debug unit suite: **344 passed**.
- Combined backend/PC, PostgreSQL/Redis and deployment regressions: **1109 passed**.
  This includes **241 real-service tests** and **6 Compose configuration tests**.
  Coverage is **67.64%** and passes the unchanged **65%** gate with two-decimal
  precision. No threshold or coverage scope was weakened. Two additional
  regression tests exercise the 64.98% rejection and exact 65.00% boundary. Long load/soak profiles require a prepared API
  environment and are excluded from the ordinary PR command.
- Reproductions and before/after evidence are indexed in
  [the audit report](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/audits/2026-09-05/AUDIT-REPORT.md).
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
stop acknowledgements, cancellation under Redis/commit failure, other pipeline writers and batch wave production and post-commit webhook delivery remain open. Existing
incorrect batch counters and legacy task metadata require reconciliation.
Update all backend writers before enforcing explicit control targets in the APK;
old watchdog messages lack a target and will be rejected. Old APKs still need
updating to prevent controls from affecting a different task. See the
[control contract](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/security/task-control-protocol.md) for rollout limits.

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
