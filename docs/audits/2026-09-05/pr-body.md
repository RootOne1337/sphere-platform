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

The production Compose override clears inherited private ports and development
application commands, users and source mounts. Both base/production and
base/full/production combinations are checked with synthetic configuration only.
Backend CI now enables the isolated PostgreSQL/Redis regressions, has a bounded
20-minute test job and retains JUnit/coverage artifacts on failure.

VPN assignment now validates the active device in the caller's organization,
serializes concurrent requests and returns the original PSK on retry. Failed or
unconfirmed router deletion preserves the peer/address reservation; concurrent
revocations return it once. The global allocator and ambiguous cross-system
outcomes remain open blockers.

## Validation

- Android enterprise debug unit suite: **316 passed**.
- Combined backend/PC, PostgreSQL/Redis and deployment regressions: **926 passed**.
  This includes **84 real-service tests** and **6 Compose configuration tests**.
  Coverage is **65.04%** and passes the unchanged **65%** gate with two-decimal
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

Apply migrations through `20260906_task_accounting` before a backend rollout; previously
issued refresh tokens require device re-enrollment. The command journal retains
512 receipts for seven days with a 1 MiB cap and rejects new DAGs when full.
Interrupted execution returns an explicit unknown-outcome failure; this does not
claim exactly-once effects. CPU/RAM/FPS, physical-device compatibility and 10–64
emulator capacity have not been measured.

n8n/MinIO ingress, runtime database roles, durable OTA/log storage, task-specific
stop acknowledgements and post-commit webhook delivery remain open. Existing
incorrect batch counters and legacy task metadata require reconciliation.

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
