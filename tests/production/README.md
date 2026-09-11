# Local production regression tests

These opt-in tests use PostgreSQL and Redis, real JWT authentication, and two disposable organizations. External device/router effects are recorded by test doubles. Passing tests require the corrected behavior; they do not assert that a vulnerability still exists.

Use dedicated local PostgreSQL and Redis instances. The database name must contain `audit`, and both URLs must use a loopback host. The suite intentionally refuses other targets. It creates test rows and Redis keys, so do not point it at a development database containing valuable data.

Install the jointly compatible dependencies with
`python -m pip install -r backend/requirements.txt -r pc-agent/requirements.txt`,
then run `python -m pip check`. CI uses the same joint resolution, so conflicting
pins cannot be concealed by installing one component after the other.

Example PowerShell configuration (synthetic credentials; provision the matching local services first):

```powershell
$env:POSTGRES_URL = 'postgresql+asyncpg://audit:audit-local-only@127.0.0.1:55432/sphere_audit'
$env:REDIS_URL = 'redis://127.0.0.1:56379/1'
$env:JWT_SECRET_KEY = 'audit_local_random_2fba037c8d5442719254f6c30dd7a58b'
$env:SPHERE_RUN_INTEGRATION = '1'
python -m alembic -c alembic/alembic.ini upgrade head
python -m pytest tests/production -q
```

Without `SPHERE_RUN_INTEGRATION=1`, tests using the database fixture are skipped. Backend CI explicitly enables this suite with disposable PostgreSQL/Redis service containers and applies migrations before testing. The normal SQLite suite cannot establish PostgreSQL locking or tenant-policy correctness; the static RLS coverage check is not a runtime isolation test.

The combined CI command is `pytest tests/ --ignore=tests/load -v --tb=short --junitxml=test-results.xml --cov=backend --cov-report=xml --cov-fail-under=65`. Set `PYTHONPATH` to include the repository and `pc-agent` (`.;pc-agent` on Windows, `.:pc-agent` on Linux). Native PostgreSQL types retain SQLite-only variants, so both suites can run in one process. CI has a 20-minute test-job deadline and uploads JUnit/coverage artifacts even after failure. The 65% coverage gate is preserved.

`tests/load` includes long-running load/soak profiles. They require a separately prepared, explicitly isolated API/agent environment; the ordinary CI service containers do not provide that API. Excluding this directory from the PR regression command does not establish capacity or complete the load audit. Record environment, duration, recovery scenarios and CPU/RAM/FPS before making any 10–64 emulator capacity claim.

`test_vpn_health_recovery.py` exercises rejected/malformed router snapshots,
preserved PSK, per-tenant background commit/rollback, concurrent revocation and
out-of-order health observations. Router requests use `httpx.MockTransport` in
memory; PostgreSQL persistence and transaction overlap are real. These tests do
not start a VPN router, prove command delivery through the current stub publisher,
or establish an Android handshake. See AUD-28/AUD-29 and the
[durable lease design](../../docs/audits/2026-09-05/VPN-LEASE-DESIGN.md) for remaining scope.

Apply `20260906_vpn_intents` for `test_vpn_durable_leases.py`. The migration fails
on duplicate held addresses in previously accumulated test fixtures; do not apply
cleanup procedures to valuable data. The fixture now deletes only VPN rows of its
two newly created organization UUIDs. `test_vpn_migration.py` runs migration error,
rollback and downgrade scenarios in temporary PostgreSQL schemas rolled back at
test end. The 64 concurrent assignments use in-memory router responses and do not
represent measured emulator capacity.

Apply `20260906_account_ciphertext` for account credential regressions. Tests
generate ephemeral Fernet keys per fixture and change only disposable accounts;
they do not use deployment keys. SQL reads bypass ORM processing to prove that
create/update/import/orchestrator writers erase the legacy plaintext. The CLI
test executes `python -m backend.cli.account_credentials` against only its new
organization UUID. Encryption/rotation/rollback tests are not a production data
migration or proof that historical backups are free of plaintext.

`test_cancellation_serialization.py` uses independent PostgreSQL sessions and
retained ORM snapshots to check cancel/force-stop against terminal results. It
also holds a result transaction open while cancellation runs, verifies no early
queue/publisher effect, and checks tenant rejection and valid active transitions.
These tests do not prove physical device stop or durable delivery of cancellation.

`test_cancellation_commands.py` delivers stop ACKs through the real backend
handler after injected Redis/SQL failure and verifies that they cannot finalize
the DAG or clear its journal. It also verifies a targeted watchdog stop after
TIMEOUT. Pair these tests with Android `ControlCommandTargetTest` and the
[control contract](../../docs/security/task-control-protocol.md); neither suite
establishes durable stop delivery or physical execution acknowledgement.

`test_batch_cancellation.py` checks real result-owner locks, terminal batch
snapshots, repeated cancellation, tenant rejection, task finish times and the
policy of leaving RUNNING tasks active. A separate ordering case holds Task
before invoking aggregation while cancellation waits; this detects an inverted
Batch-to-Task lock order. Observations use pg_stat_activity in the disposable DB.
The before evidence contains the first 15 cases; the 16th is an additional
lock-order regression. These do not certify wave producer recovery or device stop.

`test_scheduler_cancellation.py` holds task/pipeline outcome transactions open
while the real scheduler cancellation path runs. It checks outcome preservation,
absence of premature queue/control effects, active cancellation and explicit org
predicates. Two malformed legacy links are test fixtures, not proof of a public
API exploit. A supplemental controlled-clock case verifies fresh control signing
time after a 120-second simulated row wait. Pipeline writers, child-task stop,
network/commit recovery and the cancellation outbox are not certified here.

`test_batch_wave_outcomes.py` runs the real wave producer, SQL task admission and
device result handler. Thirteen cases cover queued versus completed state, false
webhook suppression, result commits before producer exit, rejected device slots,
post-submission cancellation and admission/result counter concurrency. A real
PostgreSQL division-by-zero error proves that the current wave aborts without
discarding prior committed waves or reporting success. Transport is mocked;
wave restart and reliable callbacks remain separate work; cancellation fencing
is exercised separately below.

`test_batch_startup.py` verifies parent visibility across sessions, no launch on
commit/mapping failure and an ASGI POST with actual SQL task admission. It does
not exercise a listening server or physical APK. The fourth case supplements
the three-case before proof; durable recovery after commit remains open.

`test_batch_wave_cancellation.py` reproduces cancellation before, during and
between wave transactions, terminal/tenant admission guards and late result/timeout
handling. Thirteen cases include two extra regressions beyond the 11-case before
proof: SQL rollback releases the production lock, and overlapping batches acquire
devices without reverse-order deadlock. PostgreSQL lock waits are observed directly;
queue effects remain mocked and no physical stop guarantee follows.

`test_session_logout.py` verifies actual Set-Cookie deletion on ASGI responses,
SQL refresh-token revocation through cookie/header transports, rejection of refresh
replay and access-token blacklist behavior. It uses real local PostgreSQL/Redis,
not a listening server. Invalid/absent Bearer and concurrent session-recovery limits
are documented separately.

`test_session_rotation.py` proves single-use refresh consumption with real concurrent
PostgreSQL transactions, observed row waits and preloaded ORM identities. It covers
committed revoke/expiry after a wait, rolled-back revocation and failure before
rotation commit durability. The successful child is exercised through ASGI HTTP.
These eight cases establish token-row serialization, not refresh-family revocation,
unknown-commit replay or full browser cookie ordering. See AUD-52.

`test_mfa_consumption.py` uses real TOTP verification, Redis GET/DEL/TTL and PostgreSQL
issuance to prove one winner per MFA challenge. It also covers invalid-code recovery,
a lost Redis response after successful consumption and a SQL failure before commit.
Consumed challenges are not restored after uncertain or failed issuance: restart the
password/MFA flow. This is not a complete MFA rate-limit or Redis-failover assessment.

`test_rls_startup.py` creates UUID-scoped roles and a throwaway schema to exercise
actual owner, FORCE, inherited/NOINHERIT membership and TRUNCATE escapes. The startup
guard rejects unsafe production roles and missing RLS prerequisites. A non-owner
control sees only its tenant. Schema/roles are removed; this is not an end-to-end
HTTP/auth/background-job rollout under runtime credentials.

`test_rls_policies.py` grants a UUID role CRUD (no ownership/BYPASSRLS/TRUNCATE)
on the actual Alembic-migrated schema and verifies unfiltered reads, foreign writes,
both M2M endpoints, audit append-only behavior and absent/invalid tenant context.
`test_rls_migration.py` uses rollback-only minimal schemas to check preservation of
operator restrictive policies, resistance to permissive-policy OR bypass, legacy
policy replacement and refusal of unsafe downgrade. These are SQL boundaries;
HTTP/auth/jobs under runtime credentials remain a [rollout blocker](../../docs/security/postgresql-rls.md).
The earlier privileged integration suite is not relabelled as a runtime-role suite.

`test_tenant_transactions.py` logs in with an actual UUID-scoped non-owner role and
uses pool_size=1 to prove tenant restoration after commit/rollback/SQL failure and
Session.invalidate(). It checks interleaved A/B Sessions on the same backend PID,
no context inheritance by a fresh Session, retained ORM identities and savepoint
behavior. The login role is removed after its pool is disposed. These 16 cases
exercise DB helpers directly; they do not establish complete HTTP/auth/job rollout
or PostgreSQL/network failover. A Session has one tenant for its lifetime.

`test_audit_tenant_runtime.py` executes real ASGI PUT handlers and their background
audit callback. A separate non-owner LOGIN role writes audit logs, while the HTTP
auth/request fixture remains privileged. It covers 200/403/404, concurrent tenants,
SQL failure after flush, recovery and a clean pooled Session. The first audit is
still lost after an injected post-flush failure; this is a documented durable-outbox
blocker, not a claim of guaranteed audit delivery.

`test_jwt_tenant_runtime.py` runs user JWT auth, device PUT and audit writes under
actual non-owner LOGIN credentials sharing a one-connection pool. Twenty-two cases
cover allowed/forbidden/foreign access, concurrent tenants, binding before user SQL,
pool cleanup and account moves/deactivation/role downgrade after token issuance.
Ten cases use non-owner HTTP credentials; twelve owner controls prove explicit token/user organization checks, with invalid claims
rejected at HTTP auth even when PostgreSQL bypasses RLS. Synthetic signed token
purposes are negative contract tests, not evidence of an exploitable issuer bypass.
This covers an already-issued access JWT, not opaque login/refresh/MFA/API-key or
all device/worker bootstrap. Unit SQLite's set_config adapter does not emulate RLS;
none of these PostgreSQL cases uses it or skips production binding.

`test_device_bootstrap_runtime.py` covers opaque key enrollment and device refresh
using actual non-owner LOGIN credentials. The fixture explicitly grants USAGE and
EXECUTE on the two tenant-only functions from `20260909_credential_lookup`; no
runtime ownership or BYPASSRLS is granted. Eighteen cases include parallel SQL lock
waits, replay, post-flush failure/retry, temp-table shadowing, revoked EXECUTE and
function owner protection. See [the operator contract](../../docs/security/device-credential-bootstrap.md).

`test_agent_tenant_runtime.py` drives the real ASGI WebSocket/HTTP routes without a
listener. Sixteen runtime-role cases cover device/refreshed/key/user connection
and reconnect, log/OTA access, device and tenant denials, enrollment-to-refresh-to-WS
and SQL failure/recovery. Connection manager, heartbeat, stream and queue effects
are doubles. This does not exercise APK OS behavior or post-auth task writers.

`test_enrollment_revocation.py` holds a real key row while two runtime HTTP requests
wait, then commits revoke, permission removal or expiry. Both requests must use
current key state and create no device. These three cases cover the previous
SELECT-to-UPDATE snapshot race, not revocation of already-open WebSocket sessions.

`test_agent_messages_runtime.py` sends post-auth messages through the same real ASGI
router with non-owner credentials for all four new SQL Sessions. Fifteen cases cover
typed/untyped start receipts, progress, events, commit-before-terminal-ACK, reconnect
replay, batch/event accounting, two concurrent SQL lock waiters, Redis method failures,
SQL abort after flush and successful replay, ownership denials and pooled context
cleanup. ACK callback assertions also record successful verification outside the
handler, which otherwise catches send errors. No network listener, APK process or
full EventTrigger/account/pipeline effect is exercised; transport doubles are retained.

`test_user_bootstrap_runtime.py` adds 34 actual non-owner HTTP/SQL/Redis cases for
login, refresh, logout and MFA bootstrap. Runtime fixture grants EXECUTE on the two
user functions added by `20260909_user_auth_bootstrap` as well as the earlier device
functions. Tests cover permitted A/B identities, denial controls, all refresh sources,
SQL logout revocation, actual concurrent refresh row waits, one MFA consumer after
two reads, malformed/legacy state, identity changes, post-flush SQL abort/retry and
function grants/search_path/owner protection. Login rate-limit keys are namespaced
per fixture while retaining real Redis enforcement. See [rollout and remaining risks](../../docs/security/user-auth-bootstrap.md),
including MFA v2 challenge invalidation and Redis/SQL unknown outcomes.

`test_pc_tenant_runtime.py` uses actual non-owner PostgreSQL credentials for PC key
auth and workstation/instance registration. Twelve cases cover endpoint reconnect
with registration through the receive loop, key/workstation denial controls, SQL
key-lock contention during revoke, committed registration, SQL abort/retry, Redis
cache failure and pooled scope cleanup. Socket/manager are doubles; disconnect is
raised as WebSocketDisconnect, not supplied as a normal ASGI disconnect frame.
Actual client execution, network/OS recovery and LDPlayer/ADB actions remain open.

`test_pc_result_protocol.py` links the actual PC dispatcher to the backend handler
and a real Redis subscriber through an in-process transport adapter. Ten cases cover
successful ping, a synthetic LDPlayer execution exception, both legacy terminal
replies, typed compatibility and nonterminal/telemetry controls. The fixture uses
the PC tenant runtime setup; no actual network socket or LDPlayer/ADB process runs.
These assertions verify the result discriminator and publication boundary, not
durable delivery, command idempotency or subscriber recovery after Redis/network loss.

Three additional cases in that file reject false success for unsupported PC command
names (AUD-66): a typo, the old guide's `adb_exec`, and a future unknown operation.
The actual dispatcher/handler/Redis subscriber must observe a correlated failed
reply and no LDPlayer/ADB calls. Supported/legacy controls remain active.


### Recoverable device refresh (AUD-69/70)

Apply migration `20260910_device_refresh_retry` before these tests. The 24 new cases
in `test_device_refresh_recovery.py` exercise non-owner SQL, post-commit response
loss, pool recreation, row-lock races, expiry/re-enrollment, commit rollback,
transactional migration roundtrip and recovered ASGI WebSocket authorization.
43 related cases pass with the earlier bootstrap/legacy-refresh regressions.
The migration retains existing protected-function owner/EXECUTE grants. The
roundtrip runs inside an owner transaction that is rolled back; no schema downgrade
is committed. Fixtures use only the named loopback audit services.

Android's separate `RefreshRecoveryTest` has seven cases using distinct fake memory
and disk plus an HTTP interceptor, with no network. JVM suite at AUD-70: 354 cases.
This validates ordering and stale-response fencing, not actual Android OS crash,
keystore or disk durability. [Protocol/rollout](../../docs/security/device-refresh-recovery.md).

### Android authentication acknowledgement (AUD-72)

Eight new cases in `test_agent_tenant_runtime.py` execute actual ASGI auth under a
non-owner PostgreSQL role. The first server frame identifies the authenticated
device before registry publication/command delivery, including reconnect for
device, refreshed, enrollment-key and user credentials. Failed acknowledgement
delivery cannot publish/evict a session; foreign, invalid and inactive credentials
receive no acknowledgement. Initial baseline: five failures and three controls;
48 related auth/refresh cases pass. Delivery/registry/heartbeat are controlled
boundaries, not a listening server or load test.

Android adds 16 lifecycle/gating cases; full enterprise debug suite: 378 tests / 30
suites. [Versioned handshake and deployment order](../../docs/architecture/ANDROID-CONNECTION-PROTOCOL.md).


### Android discovery credential/lifecycle contract (AUD-73)

`test_enrolled_device_discovery_uses_public_config_without_api_key_header` adds two
non-owner SQL/ASGI cases: issued and refreshed device JWTs are rejected as config
API keys (401), public discovery succeeds (200), and the same identity still gets
WS `auth_ok`. These are passing server contract controls; the fix is in the APK.
The new `ConfigRecoveryTest` has 21 Robolectric/OkHttp cases, including held headers,
body limits, 64 coalesced notifications, stop/restart and stale local route revisions.
Full Android enterprise debug suite: **399 tests / 31 suites**. No listeners, device
OS, fleet throughput or new backend permission policy are exercised here.
[Discovery contract](../../docs/architecture/ANDROID-DISCOVERY-RECOVERY.md).

### Saved APK routes and refresh origin recovery (AUD-74)

`test_agent_tenant_runtime.py` adds three PostgreSQL/ASGI cases: optional public
`fallback_server_url` (present/absent), then refresh with a deliberately lost
post-commit HTTP response and retry through a second ASGI origin. The retry returns
the same refresh successor; a changed operation ID fails, recovered device WS auth
passes, and a foreign device remains denied. The transport is in process and the
database uses the dedicated non-owner runtime role.

`tests/test_agent_config_routes.py` adds two pure Python cases for the real config
generator. Android `SavedRouteFailoverTest` adds 27 JVM/Robolectric cases: route
selection, persisted pair, refresh ID, late callbacks, auth denial, local MDM/file
discovery, generated enrollment key, registration URL and derived client pinning.
Full Android enterprise debug: **426 tests / 32 suites**. No actual fleet, listener,
DNS outage, Android OS crash or resource profile is established.

[Contract and evidence](../../docs/architecture/ANDROID-SAVED-ROUTES.md).

### Background APK enrollment (AUD-75)

No backend production behavior or SQL schema changes in this increment.
`BackgroundEnrollmentTest` adds 22 Robolectric cases with real workers, parser,
registration client and store; HTTP, preferences, root and service calls are doubles.
`SavedRouteFailoverTest` adds two cases for enrollment after service boot and stale
identity ACK. Full enterprise debug: **450 tests / 33 suites**, no failures/skips.
This is separate from the preceding 490 PostgreSQL/Redis cases; it does not join an
installed APK to a real database. [Reproduction and boundaries](../../docs/architecture/ANDROID-BACKGROUND-ENROLLMENT.md).

### Cancellable registration HTTP (AUD-76)

13 new `RegistrationRecoveryTest` cases and two worker cases exercise actual OkHttp
callbacks with held headers, body and dispatcher queue, cancellation, late replies,
size boundaries and enrollment lock release. Full enterprise debug: **465 / 34 suites**.
Baseline: five failures / two controls. The first expanded candidate had one invalid
interceptor-count assertion; the corrected test drains callbacks and verifies no
credential mutation. [Evidence and limits](../../docs/architecture/ANDROID-BACKGROUND-ENROLLMENT.md).
No backend code/schema changes or installed APK/SQL smoke is claimed.

### Registration persistence and issuance ordering (AUD-77)

20 new JVM `RegistrationPersistenceTest` cases use the real registration client and
token store with isolated OkHttp issuance gates and separate preference memory/disk
doubles. Baseline 9 cases: 8 failures / 1 control; full enterprise debug after fix:
**485 tests / 35 suites**, no failures/errors/skips. Includes failed/throwing commit,
restart without pending apply, stale replies, both refresh ordering directions,
waiter cancellation and readers during failed persistence. No actual Android disk,
keystore, OS kill or server credential replay is claimed.
[Evidence and residual risks](../../docs/architecture/ANDROID-BACKGROUND-ENROLLMENT.md).

### First-pilot bootstrap (AUD-78)

15 new cases run the shipped seed against isolated PostgreSQL, and an actual admin
Python subprocess followed by ASGI login, registration and device visibility.
Eight Bash/PowerShell cases execute the actual extracted bootstrap functions with
a process-backed Docker boundary. Full suite: **1413 / 505 real-service / 33 deployment**.
No Compose, browser, installed APK or VPN tunnel acceptance is claimed.
[Plan, environment assumptions and evidence](../../docs/operations/PILOT-ACCEPTANCE.md).

### AUD-79: deployment initialization coverage

Four additional Bash cases keep the shipped preamble and both overlay options.
Local deployment directory: 37 passed. Full Linux suite at `ac7a11f`:
**1417 passed / 69.37%**, with 505 PostgreSQL/Redis cases and 37 deployment
cases. [Exact CI excerpt](../../docs/audits/2026-09-05/evidence/ci-ac7a11f-tests.txt).
The Docker process is a boundary double; this does not run the full stack.

### AUD-80: Windows dotenv selection

Seven new deployment cases: actual synthetic Compose rendering and full start-dev
with a Docker process double. Local deployment: 44 passed. Exact `ea8e606` Linux
CI: **1424 passed / 69.38%**, including unchanged 505 PostgreSQL/Redis cases.
[CI excerpt](../../docs/audits/2026-09-05/evidence/ci-ea8e606-tests.txt). No service startup or installed-device claim.

### AUD-83: startup enrollment identity

`test_startup_enrollment.py` adds 19 cases: real isolated PostgreSQL and ASGI
registration/visibility, CLI/restart and four concurrent hook calls, invalid keys,
configuration and development aliases. Three environment controls do not open a
database; the outage-propagation case injects ConnectionError at the session factory.
Two additional deployment cases render Compose to verify the selected org env.
Baseline: 11 failures / 3 controls; Windows full suite: **1466 / 69.70%**,
524 production-directory / 67 deployment cases. [Evidence](../../docs/audits/2026-09-05/evidence/startup-enrollment-full.txt).
The SQL fixture patches only session selection, settings, isolated rate-limit keys
and old hard-coded test material; it does not fake key queries, locks or commits.
This is not a full process startup, installed APK or daemon/network recovery drill.

### AUD-84: retain existing installation configuration

Ten new deployment cases execute both shipped secret-generation stages in
temporary directories. Synthetic credentials are byte-checked; a process double
records unexpected generator calls. Four failures / six controls on `a294c29`,
then **77 deployment cases pass / 70.95 s**. The last local combined suite stays
1466 / 69.70%; no backend or Android runtime change in this increment. Actual
persistent-volume restart and credential rotation are separate acceptance gates.

### Verified runtime CI after AUD-81–84

Exact `b9a35186f13ffe28ab54321fca6604400084ae9a`: **1476 passed / 69.66%** on Linux,
including 524 production-directory and 77 deployment cases. Four immutable-image
stdlib probes run in a separate mandatory job and are not added to pytest counts.
All four Android variants pass. [Structured evidence and excerpts](../../docs/audits/2026-09-05/AUDIT-REPORT.md).
All four runtime heads passed on their first attempts; preview deployment was skipped.

### AUD-85: operator credentials across full-deploy restart

`test_admin_bootstrap_restart.py` adds 14 cases: actual shell bootstrap functions,
real admin CLI processes, disposable PostgreSQL and ASGI login; the Docker boundary
only forwards whitelisted admin commands, while enrollment's outcome is synthetic.
Three concurrent CLI processes exercise existing/fresh organization races. A deferred
SQL trigger rejects COMMIT and is removed in finally; rollback cannot produce a
success marker. Eight deployment cases reject missing/duplicate/unknown outcomes
and verify existing-account output. Before: 9 failures / 4 controls. Full Windows:
**1498 / 69.67%**, 538 production-directory / 85 deployment cases.
[Evidence](../../docs/audits/2026-09-05/evidence/admin-restart-full.txt).
The image probe exercises `--create-only` validation and still has four separate
stdlib cases. This is not Docker app startup, an installed APK or a network drill.

### Current CI and packaged SQL runtime acceptance

Runtime `08338d3161a0916e0ed7ff026a78bb2780884584`: **1498 Linux / 69.66%**, including
538 production-directory and 85 deployment cases; all four PR workflows pass on
attempt 1. Windows: 1498 / 69.67%. Four image probes are counted separately.
A new [packaged runtime scenario](../containers/README.md) passes locally on the same
image source: real fresh SQL/bootstrap, unmodified app lifespan, ASGI login/device
and new-process restart. It is added to mandatory image CI and counted as one
separate scenario, not another pytest case. No full Compose/browser/installed APK.

Packaged acceptance CI `cbf8f01215c5e27a809c29fa711d4e9f2a5c5a95` подтверждён:
**1498 / 69.66%**; отдельно **4 no-network + 1 SQL/runtime** проходят в
обязательном image job. [Сохранённые фазы](../../docs/audits/2026-09-05/evidence/ci-cbf8f01-image-runtime-tests.txt).
Runtime source не менялся после `08338d3`; все четыре PR workflows проходят
с первой попытки. Этот scenario не использует Compose PostgreSQL init.sql.

### AUD-86: exact Compose environment reaches Settings

Eight `tests/deployment/test_compose_runtime_settings.py` cases invoke the actual
generator, render each Compose overlay, then import Settings in a fresh process
with its exact container environment. Two baseline failures / six controls; all
93 deployment cases pass locally after the one-line default fix. No DB/API listener,
daemon or installed APK is involved; the last full local suite remains 1498 cases.

### AUD-86 exact revision verified in Linux

`8932e49cb6ab9a2c6d65a324b833cb0f741597ab`: **1506 passed / 69.66%**, including 538
production-directory and 93 deployment cases. Image probes remain separate: 4
no-network cases plus 1 SQL/runtime scenario. All four workflows pass attempt 1.
[Evidence](../../docs/audits/2026-09-05/evidence/ci-8932e49-tests.txt).
Windows last full: 1498 / 69.67%; targeted deployment after AUD-86: 93 passed.
