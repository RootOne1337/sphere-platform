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
