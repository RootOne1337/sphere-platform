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

## Validation

- Android enterprise debug unit suite: **316 passed**.
- Backend/PC suite: an earlier full run had **834 passed**. The latest had
  **833 passed and one performance-threshold failure** (500-node DAG validation,
  127.1 ms vs 100 ms); its isolated rerun passed. The threshold was not relaxed.
  Load tests and real-service regressions run separately.
- Dedicated loopback PostgreSQL/Redis regressions: **38 passed, no xfail**.
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
orchestrator accounting/concurrency, VPN/deployment and the remaining component
audit are still open. Legacy running assignments require rollout reconciliation.

Apply the device refresh migration before deploying the new backend; previously
issued refresh tokens require device re-enrollment. The command journal retains
512 receipts for seven days with a 1 MiB cap and rejects new DAGs when full.
Interrupted execution returns an explicit unknown-outcome failure; this does not
claim exactly-once effects. CPU/RAM/FPS, physical-device compatibility and 10–64
emulator capacity have not been measured.

A real APK-to-backend runtime test is incomplete: automatic approval review
rejected starting the isolated local API with `blocked by policy`; no workaround
was used. CI results must be read on the latest PR head; dependency/security work
is still open. No merge or deployment has been performed.

The report corrects the earlier ACK-discriminator assessment: the original main
WebSocket loop already supported untyped legacy acknowledgements. The explicit
type standardizes the contract; it does not prove all original replies were lost.
