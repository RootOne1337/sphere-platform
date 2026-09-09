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

HTTP logout now returns its actual cookie-deletion response and revokes the
`X-Refresh-Token` fallback used by the frontend. Five PostgreSQL/Redis/ASGI cases
include a previously successful refresh replay after logout and old-access
rejection. Concurrent single-use refresh is serialized with a PostgreSQL row lock and fresh
ORM state before validation. Eight database regressions prove single consumption,
revoke/expiry visibility after waits and rollback behavior. Refresh-family
revocation and uncertain-commit replay remain open.

MFA completion now requires successful atomic consumption of its Redis challenge.
Concurrent valid submissions cannot issue two sessions, and a challenge expiring
after its initial read cannot issue credentials. Five real Redis/PostgreSQL
regressions cover those races, invalid TOTP, lost Redis responses and SQL failure.
This establishes challenge single-use, not bypass resistance for every MFA path.

Private frontend pages remain unmounted until the identity is ready; a new
session/identity gets a separate React Query client before rendering. Version
checks prevent delayed responses from restoring logout, replacing another login
or replaying old mutations with a different user. Startup/401 refresh is shared
and bounded to five seconds. Login/MFA apply atomically to the current attempt.
Sign out immediately clears browser access and revokes captured server credentials;
network failure displays an unconfirmed-revocation message on login.

## Validation

- On code revision `3630a63` (including MFA consumption), [backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34175662279)
  passed Tests, Lint, Security, Alembic and static RLS checks;
  [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34175662252)
  passed build and unit tests. This is a revision-specific snapshot; consult PR
  checks for subsequent documentation or code commits.

- Frontend: **198 tests / 23 suites passed**, TypeScript noEmit passed on Node 24.19.0.
  Next build exits 0; Windows standalone tracing emits an ENOENT warning, so
  packaging and real-browser behavior remain unconfirmed. On `3630a63`, [Linux frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34175662261)
  passed Jest, tsc, production build and a standalone-entry-point check.
- Android enterprise debug unit suite: **344 passed**.
- Combined backend/PC, PostgreSQL/Redis and deployment regressions: **1300 passed**.
  This includes **428 real-service tests** and **6 Compose configuration tests**.
  Coverage is **68.80%** and passes the unchanged **65%** gate with two-decimal
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

The schema head is `20260909_credential_lookup`; production rollout remains blocked
on separate runtime credentials and auth/job tenant propagation. Previously
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

Frontend tests use React/JSDOM and controlled Axios adapters, with no listening
API. Browser storage fallback, refresh cookie ordering, cross-tab coordination,
other client stores and backend refresh-family concurrency require further work.

### RLS startup guard (AUD-14, rollout remains blocked)

Ordinary table owners previously passed startup and could read both tenants even
without SUPERUSER/BYPASSRLS. Startup now rejects ownership and owner-role membership,
privileged memberships, TRUNCATE privileges, inactive RLS and absent policies in
production. Development warns explicitly. Ten real PostgreSQL regressions exercise
actual owner/FORCE/SET ROLE/TRUNCATE behavior: nine failed before, all ten plus three
lifespan tests pass after. This does not certify policy predicates or solve auth/job
tenant propagation; switching deployment credentials remains blocked on that work.

### Complete schema policies (AUD-54; application rollout still blocked)

The actual migrated schema exposed orchestration settings and device/group/location
associations to other tenants through an ordinary CRUD role, while 15 RLS-enabled
tables without policies denied even legitimate tenant access. The before proof
recorded 19 failures and two controls. A new Alembic revision installs policies for
all 28 application tables, protects both association endpoints and makes audit
runtime access tenant-scoped and append-only. Restrictive boundaries prevent
permissive-policy OR bypass; operator restrictive policies are retained. Missing
or empty context denies access; malformed UUID fails before writes. Unsafe downgrade
is refused and the old manual SQL setup fails explicitly with migration guidance.

Verification: 25 full-schema runtime-role cases, four migration/operator-policy
cases and four CI inventory cases pass (33 total); the startup fix adds ten more
PostgreSQL regressions. The combined 1170-test local suite and unchanged coverage
gate pass. RLS code head `297bb01` passed
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34212030440)
(1170 passed, 67.90% Linux coverage),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34212030378)
and [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34212030360).
Subsequent documentation-only commits trigger separate checks. All reproductions remain isolated and do not assert a
public HTTP exploit for every affected table. See the
[RLS rollout contract](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/security/postgresql-rls.md)
for auth/bootstrap/jobs, transaction context, foreign-key and role constraints.

### Session tenant context survives transactions (AUD-55)

The DB helpers set PostgreSQL LOCAL tenant context only once. A commit, rollback
or recovered connection caused later reads to lose their own tenant rows; rebinding
one Session could retain tenant A ORM objects while loading tenant B. Bind each
Session to one validated tenant and reapply LOCAL context in after_begin. Reject
cross-tenant rebinding and first binding inside a savepoint; use a fresh Session
for another tenant. The connection pool retains no tenant setting.

Sixteen real PostgreSQL login-role regressions cover transaction endings, SQL error,
connection invalidation, one-connection A/B interleaving, fresh-session isolation,
identity-map retention and savepoints. Before: 14 failed, two controls passed;
after: all 16 plus the existing context test pass. These test DB helpers directly;
unscoped HTTP/auth/bootstrap/jobs remain rollout blockers. SQL arbitrary SET and
network partition/server failover are outside this proof.

AUD-55 local combined verification: **1186 passed / 68.01%**, including 314 real-service tests. Ruff and Bandit gate pass; this change is covered by the subsequent combined CI snapshot below.

### Bind the HTTP audit writer to its tenant (AUD-56)

HTTP mutations could succeed while the separate background audit INSERT was
rejected by RLS. Bind the new audit Session to the captured principal tenant before
inserting. Six ASGI/PostgreSQL tests cover successful/denied/missing-resource writes,
concurrent tenants, SQL failure after flush and recovery, and the existing unauthenticated
skip behavior. Before: five failed and one control; after: 26 related tests pass.
Only the audit writer uses runtime login credentials in these HTTP reproductions;
the request/auth DB fixture remains privileged. Missing tenant fails closed. A SQL
failure can still lose audit after HTTP commit because BackgroundTask has no durable
outbox/retry; the regression explicitly records this remaining limitation.

Combined verification with AUD-56: **1192 passed / 67.99%**, including 320 real-service cases. Ruff, Bandit and generated API documentation checks pass. Code head `063a9d5` passed
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34252757065)
(1192 tests, 67.95% Linux coverage),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34252757456)
and [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34252757061).
The subsequent documentation-only snapshot has separate checks; the tested code
is unchanged. Draft review, full auth/job runtime-role rollout and audit outbox
remain open; no production deployment or merge was performed.


### Bind user JWT authentication before querying tenant data (AUD-57)

Valid user access tokens returned 401 with the real non-owner PostgreSQL role
because authentication queried users before setting tenant context. Owner connections
also accepted an old token after its user moved to another organization. Authentication
now validates purpose and UUID claims, binds the signature-verified tenant after the
blacklist check, and selects a fresh user by both id and org_id. Database role/activity
remain authoritative. The generic decoder and device/refresh token formats are unchanged.

The saved before run has 17 failures and five controls. All 22 ASGI/PG/Redis regressions
now pass (10 non-owner HTTP cases and 12 owner controls): both tenants, SQL ordering, runtime device PUT and audit 200/403/404, concurrent
requests on one connection, moved/deactivated/downgraded users and invalid claims.
SQLite unit tests have a test-only SQL adapter; production binding has no dialect bypass.
Opaque auth bootstrap, WebSocket/jobs and full runtime-role rollout remain open.

Local combined validation: **1214 passed / 67.95%**, including **342 PostgreSQL/Redis cases**; 116 related tests pass. The 65% gate is unchanged. Ruff, Bandit and generated API checks pass. GitHub checks for the new code revision are tracked separately below.

Backend CI attempt 1 on `d828a62` had **1 failed / 1213 passed**: the unchanged DAG timing test measured 363.2 ms against 100 ms. All 22 new JWT cases passed. The failure excerpt is retained; 24 local DAG cases pass. One rerun uses identical code and thresholds; runner timing variance is still an open measurement concern.

Code head `d828a62` now passes [backend CI attempt 2](https://github.com/RootOne1337/sphere-platform/actions/runs/34282838423/attempts/2),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34282838431) and
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34282838503).
Linux retry: **1214 passed / 67.99%**; Windows: **1214 passed / 67.95%**.
The first failed timing run remains in evidence; no code, test or threshold changed
between attempts. Preview guard passes, deployment is skipped. The follow-up commit
contains documentation and CI snapshots only and starts its own checks. PR remains draft.


### Device enrollment, refresh and agent connection under RLS (AUD-58–60)

Valid enrollment keys and device refresh tokens returned 401 because their tenant
was unknown before RLS lookup. Two protected SQL functions now return only an org
UUID for a complete active credential hash. PUBLIC access is revoked, search_path
is pinned and relations are schema-qualified. Runtime needs explicit EXECUTE grants;
normal scoped credential checks follow. No runtime ownership/BYPASSRLS is granted.

Android WebSocket now authenticates before target-device lookup. Its shared agent
HTTP/WS JWT verifier binds and checks signed tenant identity. Enrollment also rechecks
key active state, expiry and permissions after a real row-lock wait; previously two
waiting requests could create devices after admin revoke/permission removal/expiry.

Thirty-seven new PostgreSQL/Redis cases include full server-side ASGI enrollment →
refresh → WebSocket → OTA, reconnect and SQL failure recovery; exact device/tenant
boundaries; multi-connection lock contention; refresh replay; lookup function grants
and temp-table shadowing. Before evidence is retained separately for all three defects.
The transport manager/heartbeat/stream effects are doubles. No listening API or APK
OS test is implied. Remaining auth callers, global jobs, production role
provisioning, refresh response loss and live socket revocation remain open. See the
[device credential runbook](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/security/device-credential-bootstrap.md)
for migration/grants/rollback and threat-boundary details.

Combined local validation on `bd7ad7a`: **1251 passed / 68.48%**, including **379 PostgreSQL/Redis cases**. Ruff, Bandit and API export checks pass; the 65% gate is unchanged. Temporary runtime roles/connections were cleaned up. New GitHub checks are reported against this exact code revision.

On `bd7ad7a`, [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34288111441),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34288111373) and
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34288111362) CI all
pass on attempt 1. Linux: **1251 tests / 68.44%**; Windows: **1251 / 68.48%**. Preview
guard passes and deploy is skipped. The following documentation-only commit saves
these snapshots and starts its own checks. No independent review or production rollout
is claimed; the PR remains draft.

### Connected Android task/event persistence under RLS (AUD-61)

A device could authenticate successfully yet its subsequent SQL Sessions had no
tenant context. Start receipts left tasks ASSIGNED, progress disappeared, terminal
results received no result_ack and device-event INSERTs failed RLS. Each of the four
fresh handler Sessions now binds the authenticated connection organization before
its first tenant query. Existing device/tenant predicates and commit-before-ACK remain.

Fifteen new non-owner PostgreSQL/Redis cases execute real ASGI WebSocket messages.
Before evidence records 12 failures and three passing denial controls. They cover
typed/untyped receipts, progress, committed Task/Batch/DeviceEvent state at ACK,
conflicting replay after reconnect, two actual SQL lock waiters without double
accounting, Redis method failures, post-flush SQL abort/no ACK/retry, device/tenant
denials and clean pooled Sessions. The 47 related tests pass. No APK wire-format,
migration or production grant changes are needed for this fix.

Transport manager/heartbeat/stream/publisher remain doubles. PubSub/Fleet events
and Redis lock release may still precede SQL commit; no durable outbox or full
EventTrigger/account/pipeline effect verification is claimed. Global job propagation,
remaining auth callers, live socket revocation and actual APK/network/load runs remain open.

Local AUD-61 validation: **1266 passed / 68.71%**, including **394 PostgreSQL/Redis cases**; four existing warnings, unchanged 65% gate. After the combined run, the test callback guard was strengthened to expose swallowed assertion failures, then all 47 related cases were rerun. Production code is unchanged since the full run. Ruff, Bandit (zero Medium/High) and API export checks pass. GitHub results for the exact code revision follow below.


On code head `f272360`, [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705525),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705438) and
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705527) CI pass
on attempt 1. Linux: **1266 tests / 68.65%**; Windows: **1266 / 68.71%**, including
394 PostgreSQL/Redis cases. Preview guard passes and deployment is skipped. Compact
snapshots and the Linux test summary are committed with the audit report. The following
documentation-only revision starts its own checks; application code is unchanged.
No independent review, full production rollout or APK/OS/load verification is implied.

### User login, refresh/logout and MFA under RLS (AUD-62)

Unscoped credential queries made valid user login/refresh/MFA return 401 under
non-owner PostgreSQL credentials. Logout could return 204 without revoking the SQL
refresh token. Two protected SQL functions now discover only the organization from
an exact globally unique email or a complete active refresh hash. Normal scoped
credential/password checks follow. Refresh/logout retain row-lock consumption;
refresh rejects a user moved outside the token's organization.

MFA stores server-written user/organization JSON under a versioned Redis namespace,
binds before User access, rechecks active/MFA/organization state and requires the
single successful DEL before SQL token issuance. Client wire formats stay unchanged.
Legacy in-flight challenges require a new password step, and deployment must
coordinate old/new workers. Migration `20260909_user_auth_bootstrap` requires explicit
EXECUTE grants on the two user functions, additional to the device-function grants.
See the [user auth runbook](https://github.com/RootOne1337/sphere-platform/blob/codex/enterprise-audit-20260905/docs/security/user-auth-bootstrap.md).

Baseline: 10 failures and eight passing denial controls. The final 34 new non-owner
cases cover A/B HTTP chains, all refresh sources, SQL logout revocation, one parallel
refresh winner, one concurrent MFA consumer, changed identities, malformed/legacy
state, SQL abort/recovery and function grants/search_path/ownership. All 105 related
checks pass. Combined local validation: **1300 tests / 68.80%**, including **428
PostgreSQL/Redis cases**, four existing warnings, unchanged 65% gate. Ruff, Bandit and
API export checks pass. Exact-head GitHub results are recorded separately.

Database EXECUTE can reveal the organization of a guessed active email; this is a
documented metadata boundary and does not authenticate the HTTP caller. Redis DEL
and SQL commit are not a distributed transaction: an MFA SQL failure after consumption
requires a new challenge. Unknown commit/response outcomes, refresh-family revocation,
MFA guessing/recovery policy, other auth callers/global workers and production role
provisioning remain open. No production migration, restart or deployment occurred.


Code head `d642273` passes [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906033),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906010) and
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906047) CI on
attempt 1. Linux: **1300 tests / 68.77%**; Windows: **1300 / 68.80%**, including 428
PostgreSQL/Redis cases. Migration and all 34 user-bootstrap cases pass. Preview guard
passes; deployment is skipped. Compact snapshots are retained with the audit report.
The following documentation-only commit starts its own checks and changes no
application code. The PR remains draft without independent review or production rollout.
