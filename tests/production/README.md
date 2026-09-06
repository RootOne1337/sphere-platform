# Local production regression tests

These opt-in tests use PostgreSQL and Redis, real JWT authentication, and two disposable organizations. External device/router effects are recorded by test doubles. Passing tests require the corrected behavior; they do not assert that a vulnerability still exists.

Use dedicated local PostgreSQL and Redis instances. The database name must contain `audit`, and both URLs must use a loopback host. The suite intentionally refuses other targets. It creates test rows and Redis keys, so do not point it at a development database containing valuable data.

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
or establish an Android handshake. See AUD-28/AUD-29 and the proposed
[durable lease design](../../docs/audits/2026-09-05/VPN-LEASE-DESIGN.md) for remaining scope.
