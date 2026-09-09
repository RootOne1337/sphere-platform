## Problem and resulting behavior

This draft repairs demonstrated authorization, tenant isolation and runtime failures
across the backend, Android/PC agents, frontend, task producers and VPN lifecycle.
It is an ongoing audit, not a production-readiness or complete security certification.

The [audit report](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/audits/2026-09-05/AUDIT-REPORT.md)
records severity, root cause, before/after evidence, affected files, fixes, regressions
and residual risk for each finding. Fixes and evidence use separate, scoped commits.
The [roadmap](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/audits/2026-09-05/ROADMAP.md)
separates confirmed blockers from paths still requiring investigation.

## Changes

| Area | Resulting behavior |
| --- | --- |
| Authorization and secrets | Restricts role/key delegation, binds device/task/account access to the authenticated identity, protects credential reveal, encrypts account writers and removes credentials from APK logs. |
| PostgreSQL tenant isolation | Installs policies for all 28 tenant tables, rejects unsafe runtime roles, preserves tenant binding across transaction recovery and binds JWT/auth/audit/agent sessions before SQL. Narrow credential lookup functions bootstrap tenant context under non-owner credentials. |
| User sessions and frontend | Refresh rotation has a single SQL consumer; logout revokes the actual refresh source and clears cookies. MFA requires one Redis challenge consumer. Browser identity/cache generations prevent old responses from restoring a previous session or crossing organizations. |
| Task execution and recovery | Committed assignments own dispatch intent; durable Android receipts handle duplicates and retain results until SQL commit acknowledgement. Task/batch/scheduler locks preserve competing terminal outcomes. Wave admission, parent commit ordering, cancellation fences and counters are reconciled. |
| Android | Repairs enrollment/refresh and HTTP contracts, limits automatic credentials to the management origin, cleans up transport cancellation, restores Redis presence, targets controls to the intended task and prevents loop/root retries from falsely reporting success or repeating uncertain effects. |
| PC agent | Enforces workstation ownership, uses current locked API-key validation, binds registration SQL and fixes terminal result routing, including older installed clients. |
| Orchestrator and VPN | Enforces account ownership and versioned task contracts; VPN assignments retain SQL ownership/intents across uncertain provider outcomes, concurrent allocations and health/revoke retries. |
| Deployment and maintenance | Removes startup writes from immutable API images, corrects effective Compose inheritance, updates the compatible Python dependency set, enforces the exact coverage threshold and regenerates the HTTP schema/catalog in CI. Operator guides describe actual contracts and rollout constraints. |

### Latest runtime findings

- **AUD-62:** valid user login/refresh/MFA failed under RLS; logout could return 204
  without revoking its SQL token. Protected tenant resolvers and versioned MFA state
  restore scoped access. Baseline: **10 failures / 8 controls**; **34 new cases** cover
  real non-owner SQL/HTTP/Redis, row-lock races, malformed state and abort/recovery.
- **AUD-63:** valid PC key auth and workstation registration lost tenant context.
  Shared key bootstrap and a bound registration Session fix both paths. Baseline:
  **6 failures / 6 controls**; **12 new cases** cover reconnect registration, denials,
  real key-lock waiters during revoke, SQL rollback/retry and cache failure.
- **AUD-64:** PC success/error replies lacked the discriminator used by the backend,
  so no result reached Redis. Both client branches now send `command_result`; the
  backend accepts the narrow legacy terminal envelope. Baseline: **4 failures / 6
  controls**; **10 new cases** join the actual dispatcher and handler to a real Redis
  subscriber. All **24 related cases** pass. LDPlayer/ADB and transport are doubles.

- **AUD-65:** a dead sender left the PC client apparently connected with no outgoing
  consumer. Auth failure/cancellation also escaped cleanup; reconnect/circuit waits
  leaked tasks or delayed stop, and clean closes reconnected without pacing. Session
  supervision and interruptible waits repair these paths. Baseline: **6 failures /
  3 controls**; nine new lifecycle cases and all **91 related PC tests** pass with
  controlled socket boundaries. Network/OS execution remains unverified.

## Validation

- Combined local backend/PC/PostgreSQL/Redis/deployment: **1322 passed**, including
  **450 real-service cases** and six Compose configuration tests; **69.30%** coverage,
  four existing warnings. Load/soak profiles are excluded from this ordinary PR run.
- Android enterprise debug unit suite: **344 passed**. These JVM/MockWebServer checks
  do not establish device OS, codec, battery or real network behavior.
- Frontend: **198 tests / 23 suites**, TypeScript and production build pass. Linux CI
  verifies the standalone entry point; local Windows tracing emitted an ENOENT
  warning. Real-browser behavior remains unconfirmed.
- Ruff, backend Bandit gate (**0 Medium/High**) and generated API export checks pass.
  The compatible joint Python dependency scan is a recorded snapshot, not a scan of
  all ecosystems. Coverage remains gated at **65%**, with precision=2 and tests for
  the 64.98% rejection / 65.00% acceptance boundaries.
- Application revision **`eda33a7`**, including both PC fixes, passes
  [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128767),
  [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128758) and
  [Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128765)
  CI on attempt 1. Linux: **1322 tests / 69.27%**, including all 22 new PC cases.
  Compact run snapshots and the test summary are retained with the audit report.
  The following documentation-only commit starts its own checks; application code
  is unchanged. Preview guard passes and deployment is skipped.

## Rollout and remaining risks

Schema head: **`20260909_user_auth_bootstrap`**. Production remains blocked on
separate migration/runtime credentials and remaining auth/global-worker tenant
propagation. Runtime grants must include all four protected credential functions.
MFA v2 invalidates old in-flight challenges and requires coordinated worker cutover;
Redis consumption and SQL commit are not one transaction. Refresh-family revocation,
lost successful commit responses and MFA guessing/recovery policy remain open. See
[user auth](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/security/user-auth-bootstrap.md)
and [RLS rollout](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/security/postgresql-rls.md).

Account encryption requires independent `ACCOUNT_CREDENTIAL_KEYS`, stopped legacy
writers, explicit backfill/verification and retained restore keys. Alembic alone does
not encrypt historical passwords; old backups/WAL can retain plaintext. VPN rollout
requires inventory reconciliation and stopped legacy allocators; pending/unknown
provider effects retain ownership. Duplicate/invalid leases block migration.

Legacy running assignments, batch counters and metadata require reconciliation.
Update all control writers and APKs together: old untargeted watchdog messages are
rejected by the stricter APK. The Android journal is bounded at 512 receipts, seven
days and 1 MiB; interruption can produce an explicit unknown outcome. Durable stop
acknowledgements, pipeline/wave crash recovery and post-commit event delivery remain
open. These changes do not guarantee exactly-once physical effects.

PC workstation/instance provisioning, live key revocation, normal ASGI disconnect,
topology replay, durable result delivery and unknown-command handling remain open.
Redis PubSub and the client queue can lose replies on failure. No actual LDPlayer/ADB
process, Windows service or PC network recovery was exercised by the new cases.

n8n/MinIO ingress, OTA/log persistence, deployment health and backup restore still need
runtime validation. Real APK-to-listening-backend validation was blocked by automatic
approval review (`blocked by policy`); no workaround was attempted. Physical Android
compatibility and CPU/RAM/FPS/battery for **10–64 emulators have not been measured**.
The 64-concurrent VPN test uses SQL plus a router double and is not a capacity result.

No independent review, production migration, service rollout, merge or deployment
is claimed. Preview deployment is skipped; the PR remains draft.
