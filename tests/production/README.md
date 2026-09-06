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

Without `SPHERE_RUN_INTEGRATION=1`, tests using the database fixture are skipped. CI should explicitly enable this suite with disposable service containers. The normal SQLite suite cannot establish PostgreSQL locking or tenant-policy correctness.
