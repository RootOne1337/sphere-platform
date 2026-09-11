## Problem and resulting behavior

This draft repairs demonstrated authorization, tenant isolation and runtime failures
across the backend, Android/PC agents, frontend, task producers and VPN lifecycle.
The current operational priorities are unattended APK recovery, durable execution,
truthful startup, incident diagnosis and measured UI data. Fleet capacity is a target,
not a verified property; this draft does not establish production readiness.

The [audit report](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/audits/2026-09-05/AUDIT-REPORT.md)
records severity, root cause, before/after evidence, affected files, fixes, regressions
and residual risk for each finding. Fixes and evidence use separate, scoped commits.
The [roadmap](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/audits/2026-09-05/ROADMAP.md)
separates confirmed blockers from paths still requiring investigation. The
[operational matrix](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/operations/READINESS.md)
now sets the work order; the README, documentation index and incident runbooks have
been reconciled with current contracts. A separate
[AI readiness assessment](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/architecture/AI-READINESS.md)
researches NitroGen and a future external inference worker; no AI is implemented.

## Changes

| Area | Resulting behavior |
| --- | --- |
| Authorization and secrets | Restricts role/key delegation, binds device/task/account access to the authenticated identity, protects credential reveal, encrypts account writers and removes credentials from APK logs. |
| PostgreSQL tenant isolation | Installs policies for all 28 tenant tables, rejects unsafe runtime roles, preserves tenant binding across transaction recovery and binds JWT/auth/audit/agent sessions before SQL. Narrow credential lookup functions bootstrap tenant context under non-owner credentials. |
| User sessions and frontend | Refresh rotation has a single SQL consumer; logout revokes the actual refresh source and clears cookies. MFA requires one Redis challenge consumer. Browser identity/cache generations prevent old responses from restoring a previous session or crossing organizations. |
| Task execution and recovery | Committed assignments own dispatch intent; durable Android receipts handle duplicates and retain results until SQL commit acknowledgement. Task/batch/scheduler locks preserve competing terminal outcomes. Wave admission, parent commit ordering, cancellation fences and counters are reconciled. |
| Android | Repairs enrollment/refresh and HTTP contracts, limits automatic credentials to the management origin, cleans up transport cancellation, restores Redis presence, targets controls to the intended task and prevents loop/root retries from falsely reporting success or repeating uncertain effects. Clean closes now wait before retry, with equal jitter to spread fleet reconnects. A persisted refresh intent recovers lost responses and prevents stale credentials from replacing new state. |
| PC agent | Enforces workstation ownership, uses current locked API-key validation, binds registration SQL and fixes terminal result routing, including older installed clients. Supervises send/receive failure and rejects false success for unsupported commands. |
| Orchestrator and VPN | Enforces account ownership and versioned task contracts; VPN assignments retain SQL ownership/intents across uncertain provider outcomes, concurrent allocations and health/revoke retries. |
| Deployment and maintenance | Removes startup writes from immutable API images, corrects effective Compose inheritance, updates the compatible Python dependency set, enforces the exact coverage threshold and regenerates the HTTP schema/catalog in CI. Development startup checks native Docker failures and waits for API/frontend readiness. Operator guides describe actual contracts and rollout constraints. |

### Latest runtime findings

- **AUD-84:** full-deploy treated an installation with `.env` as fresh and generated
  a higher-priority `.env.local` with different credentials, even in skip-secrets.
  Both launchers now retain the existing configuration. Four reproduced failures /
  six controls; ten new cases and all 77 local deployment tests pass. Persistent
  volume restart, admin password lifecycle and deliberate rotation remain open.

- **AUD-83:** the development startup hook ignored configured enrollment identity,
  bound its legacy key to the first org and raced on worker startup. Real SQL/ASGI
  reproduced registration 401, wrong org and duplicate-key errors. CLI/hook now
  share exact-org/configured-key validation and row-lock serialization; Compose
  forwards the org slug. Known conflicts produce diagnostic warnings in the dev
  hook, remain strict CLI failures and never reactivate/rebind credentials.
  11 baseline failures / 3 controls; local **1466 passed / 69.70%**, including
  524 production-directory and 67 deployment cases. Full lifecycle/installed APK
  and runtime-role provisioning remain open.

- **AUD-82:** full-deploy started API before schema/admin/enrollment existed and
  depended on backend exec/host migration fallback. Both launchers now wait for
  databases, run one-off migration/admin/key, then wait for applications. Production
  gets API/login healthchecks; fixed names/host HTTP and false success output are
  removed. All 65 local deployment cases pass (21 new). Full SQL/daemon acceptance,
  role separation and coordinated upgrades remain open.

- **AUD-81:** full-deploy invokes bootstrap CLIs absent from the production image.
  Ship only those two scripts. A new mandatory CI job builds the actual image and
  executes four network-isolated, read-only probes without a source mount. Baseline:
  two missing-file/module failures; after: all four pass. These are separate from
  the 1424-case pytest suite; full SQL bootstrap/rollout remains open.

- **AUD-80:** Windows full-deploy ignored its generated `.env.local`; start-dev
  rejected that file unless `.env` also existed. Both normal paths now select
  `.env.local` then `.env` explicitly, with absolute paths and unchanged process-env
  precedence. Seven new cases reproduce five failures plus controls; all 44 local
  deployment tests pass, including actual Compose rendering of synthetic config.
  Legacy branches, secret lifecycle and migration/API startup remain open.

- **AUD-79:** the Bash launcher's newline/tab IFS sent the entire Compose file
  prefix as one argument. Both overlay choices are arrays and all ten call sites
  preserve argument boundaries. Four baseline failures keep actual initialization
  and options; all 37 deployment tests pass against a separate Docker boundary
  process. The older bootstrap fixture now also includes the shipped preamble.
  Full-stack env selection, migrations, installed APK and VPN remain open.

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

- **AUD-66:** unsupported PC commands returned completed/null without executing
  anything. They now use the correlated failed/error envelope. Baseline: **3 failures
  / 10 controls**; three additional Redis cases verify no LDPlayer/ADB call. All
  **95 related cases** pass. This Medium finding concerns unsupported command types;
  real execution correctness and command authorization require separate validation.

- **AUD-67:** APK clean server close skipped retry delay, while network retries had
  shared fleet deadlines. Clean-close pacing and equal jitter repair the retry policy.
  Three failing cases before the fix; all **347 Android JVM cases** pass afterward.
  Hardware fleet behavior remains unmeasured.
- **AUD-68:** the development launcher printed success after native Docker failure,
  discarded health wait outcomes and never checked API/frontend readiness. Checked
  exit codes, config preflight and Compose service health gates fix this path.
  **17 new regressions**, baseline 10 launcher + 7 missing-probe failures; **25 total
  deployment cases** pass. Actual PowerShell/Python/Node processes are exercised with
  controlled CLI/HTTP boundaries, not a real Docker failure drill.

- **AUD-69:** lost successful device-refresh commit/HTTP responses stranded the
  installed credential. Optional persisted UUIDs and one SQL receipt recover the
  same unconsumed HKDF-derived successor without extending expiry. Baseline:
  **7 failures / 9 controls**. **24 new PostgreSQL/ASGI cases** cover response loss,
  lock races, expiry/re-enrollment, migration/grants and recovered WS auth.
- **AUD-70:** APK refresh now commits its operation ID before HTTP and fences replies
  against intervening credential changes. **7 new JVM cases**, all failed before,
  prove disk/memory ordering, failed commit handling and stale re-enrollment/clear.
  Full Android suite: **354 passed**. Physical Android crash/keystore remains untested.

- **AUD-71:** a hung blocking APK refresh held the token mutex beyond its coroutine
  deadline; cancellation was swallowed and late bodies still saved credentials.
  Baseline: **4 failures / 1 control**. Async OkHttp cancellation, bounded parsing and
  coroutine-owned credential writes repair the lifecycle while preserving retry ID.
  **8 new cases**, including 64 concurrent callers and failed-body cleanup; the full
  suite now has **362 tests**. Disk/keystore stalls and physical network recovery
  require separate drills.

- **AUD-72:** APK reported connected on transport open, bypassing its deadline while
  waiting for server auth and allowing ended-session callbacks during backoff.
  A target-bound `auth_ok` now gates application traffic and result replay; it is
  sent before registry publication. Failed acknowledgement delivery cannot evict
  an existing session. Baseline: **10 JVM failures / 2 controls**, **5 SQL/ASGI
  failures / 3 controls**. **16 new JVM + 8 SQL/ASGI cases** cover acknowledgements,
  denial, loss, reconnect and late callbacks. **Deploy every backend worker before
  APK**; an older server without the acknowledgement cannot confirm a new client.

- **AUD-73:** enrolled APK sent device JWT as a config API key (401); forced checks
  fanned out and outlived stop/local route changes. Public cancellable discovery now
  has a 10-second HTTP budget, bounded parsing, one active watchdog check and a
  generation/local-revision fence. Baseline **9 failures / 4 controls**; **21 new
  Android cases** and **2 SQL/ASGI contract controls**. AUD-74 below extends this
  with saved candidates and ACK-gated route selection.

- **AUD-74:** one saved URL and unconditional discovery/registration replacement
  stranded APKs on unavailable routes. The APK now persists primary/fallback URLs,
  retries WS and refresh through the selected route without GitHub, and promotes
  it only after device-bound `auth_ok`. Discovery retains a healthy active socket;
  successful LAN registration retains its request URL. Route-only MDM/files work
  at service start for enrolled agents. API/schema/generator carry fallback, and
  APK parsing accepts the generator's enrollment key. **27 new JVM + 5 Python
  cases (3 PostgreSQL/ASGI)** cover route failures, persistence, pending refresh ID,
  late events, config propagation and lost-response retry through a second origin.

- **AUD-75:** background workers treated a supplied bootstrap key as a session,
  marked enrollment without an assigned identity, and could register concurrently.
  Service boot captured the old ID for all subsequent WS attempts. Shared worker
  serialization, explicit registration selection, activation retry and per-attempt
  assigned identity repair these paths. Baselines: 7/8 failures initially, four
  further failures on the first candidate, and both identity cases failing before
  the WS fix. **24 new JVM cases** cover actual worker/parser/client/store logic
  with synthetic HTTP, preferences and OS boundaries. Initial registration response
  loss and hardware/OS/fleet behavior remain unverified.

- **AUD-76:** blocking registration ignored caller cancellation, persisted a late
  reply and read the entire response before applying a size limit. Async cancellable
  HTTP with a separate 10-second budget and pre-parse 64 KiB bound repairs these
  paths. Known non-success status no longer waits for error body. Worker timeout
  remains retryable and releases the enrollment mutex. Baseline: **5 failures /
  2 controls**; **15 new cases**, including actual worker recovery after timeout/stop.
  One first-candidate test misidentified application interceptor invocation as a
  network send; its failure and corrected cancellation/state assertions are recorded.

- **AUD-77:** registration returned before ID/tokens reached disk and persisted routes
  separately; overlapping UI/worker replies could install older credentials or undo
  a clear/route change. One checked registration commit, shared registration/refresh
  mutex and local revisions repair these paths. Invalid UUID/credentials/expiry are
  rejected before mutation. Baseline: **8 failures / 1 control**; **20 new cases**
  cover persistence failure/retry, races, cancellation and refresh issuance order.
  This does not recover server-side issuance after a lost initial response.

- **AUD-78:** the first-run bootstrap imported nonexistent DB factories, targeted
  a different organization from the administrator, and launchers printed credentials
  after failed creation. The real session factory, explicit shared organization,
  checked existing keys and environment-forwarded admin CLI repair these paths.
  Baseline: eight seed cases fail at one ImportError; six launcher regressions fail.
  **23 new cases** exercise actual admin subprocess/login/register/device visibility
  with isolated SQL/HTTP and both shell functions against a Docker process double.
  Four further cases catch the reserved `.local` default email and invalid CLI
  inputs. Both launchers now default to `admin@example.com`; the CLI validates
  against the actual LoginRequest before SQL, without printing rejected passwords.
  [Pilot acceptance plan](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/operations/PILOT-ACCEPTANCE.md)
  now prioritizes the first usable stack/APK/task/VPN path with conditional estimates.

## Validation

- Latest runtime `ea8e606` (AUD-80): **1424 passed**, including 505 PostgreSQL/Redis
  and 44 deployment cases; **69.38%** coverage. [Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302055),
  [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302107), [Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302056) and
  [preview guard](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302095) pass on attempt 1; preview deployment is
  skipped. Local deployment has 44 passing cases. Evidence/docs follow separately.

- `0da40f1` (AUD-78): **1413 passed** in the full Linux backend/PC/real-service/deployment suite; all four PR workflows passed on attempt 1. [Backend results](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/audits/2026-09-05/evidence/ci-0da40f1-tests.txt).
- `ac7a11f` (AUD-79): **1417 passed** in the full Linux backend/PC/real-service/deployment suite; all four PR workflows passed on attempt 1. [Backend results](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/audits/2026-09-05/evidence/ci-ac7a11f-tests.txt).
- Latest `ac7a11f` coverage: **69.37%**, including 505 PostgreSQL/Redis and
  37 deployment cases. [Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567946), [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567951),
  [Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567922) and [preview guard](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567939).
  All four Android unit-test variants pass; preview deployment is skipped.
  The subsequent evidence/docs commit changes no runtime behavior and has separate checks.

- Combined local backend/PC/PostgreSQL/Redis/deployment: **1413 passed**, including
  **505 real-service cases** and 33 deployment cases; **69.38%** coverage,
  four existing warnings. Load/soak profiles are excluded from this ordinary PR run.
- Android enterprise debug unit suite: **485 passed / 35 suites**. These JVM/MockWebServer/OkHttp checks
  do not establish device OS, codec, battery or real network behavior.
- Frontend: **198 tests / 23 suites**, TypeScript and production build pass. Linux CI
  verifies the standalone entry point; local Windows tracing emitted an ENOENT
  warning. Real-browser behavior remains unconfirmed.
- Ruff, backend Bandit gate (**0 Medium/High**) and generated API export checks pass.
  The compatible joint Python dependency scan is a recorded snapshot, not a scan of
  all ecosystems. Coverage remains gated at **65%**, with precision=2 and tests for
  the 64.98% rejection / 65.00% acceptance boundaries.
- Preceding runtime revision **`93a4872`** (AUD-77; does not cover AUD-78) passes
  [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711631), [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711638),
  [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711637) and [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34518706234)
  on attempt 1. Linux backend: **1390 passed / 69.40%**, 296.33 seconds,
  four existing warnings. Android builds and all four variant test tasks pass;
  the local enterprise debug XML separately records 485 tests / 35 suites.
  [Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711671) passes its guard and skips deployment.
  The following evidence-only commit does not change runtime behavior.
- Preceding runtime revision **`2f17a85`** (AUD-76; does not cover AUD-77) passes
  [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34500318992), [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34500318999),
  [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34500319016) and [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34500313633)
  on attempt 1. Linux backend: **1390 passed / 69.37%**, 291.44 seconds,
  four existing warnings. Android builds and all four variant test tasks pass;
  the local enterprise debug XML separately records 465 tests / 34 suites.
  [Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34500319000) passes its guard and skips deployment.
  The following evidence-only commit does not change runtime behavior.
- Preceding runtime revision **`be75f57`** (AUD-75; does not cover AUD-76) passes
  [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536085), [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536209),
  [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536769) and [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34497528849)
  on attempt 1. Linux backend: **1390 passed / 69.38%**, 286.11 seconds,
  four existing warnings. Android builds and all four variant test tasks pass;
  the local enterprise debug XML separately records 450 tests / 33 suites.
  [Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536756) passes its guard and skips deployment.
  The following evidence-only commit does not change runtime behavior.
- Preceding revision **`2bbd9a5`** (does not cover AUD-75), including AUD-74 and the discovery-test correction, passes
  [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836701),
  [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836636),
  [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836418) and
  [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34490829634) CI on attempt 1.
  Linux: **1390 passed / 69.38%**, 294.70 seconds, four existing warnings;
  all five new route/config/refresh-origin cases pass. Android builds the debug
  APKs and runs all four Dev/Enterprise × Debug/Release unit-test tasks.
  [Preview guard](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836570) passes; deployment is skipped.
  Earlier `5f7900e` PR CI failed one test assertion race; its failed snapshot and
  deterministic reproduction remain in the report. Runtime fix: `5f7900e`;
  harness correction: `2bbd9a5`. Exact-revision evidence is retained. The following
  evidence/documentation commit changes no executable behavior; its own
  checks are separate. Database schema is unchanged.

## Rollout and remaining risks

Schema head: **`20260910_device_refresh_retry`**. Device recovery rollout is migration
→ all backend workers → APK, preserving app identity. Existing grants are retained.
AUD-72 additionally requires the `auth_ok` handshake on every backend worker before
updating APK; it adds no migration. [Handshake protocol and rollback](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/architecture/ANDROID-CONNECTION-PROTOCOL.md).
[Refresh recovery contract](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/security/device-refresh-recovery.md). Production remains blocked on
separate migration/runtime credentials and remaining auth/global-worker tenant
propagation. Runtime grants must include all four protected credential functions.
MFA v2 invalidates old in-flight challenges and requires coordinated worker cutover;
Redis consumption and SQL commit are not one transaction. Refresh-family revocation,
lost successful **user-session** commit responses and MFA guessing/recovery policy remain open. See
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
topology replay, durable result delivery and payload/correlation validation remain open.
Redis PubSub and the client queue can lose replies on failure. No actual LDPlayer/ADB
process, Windows service or PC network recovery was exercised by the new cases.

n8n/MinIO ingress, OTA/log persistence, deployment health and backup restore still need
runtime validation. Real APK-to-listening-backend validation was blocked by automatic
approval review (`blocked by policy`); no workaround was attempted. Physical Android
compatibility and CPU/RAM/FPS/battery for **10–64 emulators per station or hundreds/
thousands of connected APKs have not been measured**.
The 64-concurrent VPN test uses SQL plus a router double and is not a capacity result.

Saved primary/fallback routes now support WS and refresh retry independently of
GitHub, with optional discovery. Both routes must belong to one installation; this
does not provide backend/database HA. Durable config version/rollback, live local
config reload and pre-credential installation validation remain open. AUD-75 repairs
background worker selection/concurrency and WS identity; initial registration
response loss and installed APK boot recovery remain open. AUD-77 adds one checked registration commit and serializes it with refresh across UI/workers. Failed re-enrollment can still leave old credentials unusable; server issuance recovery and physical storage drills remain open. [Configuration and limits](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/architecture/ANDROID-SAVED-ROUTES.md). AUD-69/70 cover new device refresh response recovery; legacy already-lost
operations, expired credentials and real OS/network drills remain open. AUD-71
repairs HTTP cancellation; mutex queueing, disk/keystore stalls and device scheduling
are outside its 10-second HTTP bound. Monitoring
Compose wiring and synthetic VPN UI zeroes are confirmed open gaps. Startup readiness
does not check schema head, task execution or browser actions; the legacy tunnel
path remains outside AUD-68. Reboot/restore/soak drills are still required.

The local dependency-aware mypy run repeated for AUD-74 reports 13 errors in seven unchanged files/imports;
CI mypy uses a separate lighter environment and must be assessed separately.

No independent review, production migration, service rollout, merge or deployment
is claimed. Preview deployment is skipped; the PR remains draft.
