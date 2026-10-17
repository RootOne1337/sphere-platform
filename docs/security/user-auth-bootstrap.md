# User authentication with a non-owner PostgreSQL role

Updated 9 September 2026, AUD-62. Login, user refresh, logout and MFA now establish
the tenant before accessing user/refresh rows under RLS. This closes the tested
HTTP bootstrap paths; global jobs and production role provisioning remain open.

## Failure and corrected contract

Login originally selected a user by email in an unscoped Session; refresh/logout
selected an opaque token hash the same way. RLS returned no rows: valid login and
refresh returned 401, while logout could return 204 without revoking the SQL token.
MFA state held only a user UUID, so its separate request could not load the user.

Migration `20260909_user_auth_bootstrap`, after `20260909_credential_lookup`, adds:

| Function | Exact input | Return | Checks inside function |
| --- | --- | --- | --- |
| `sphere_auth.user_login_org(text)` | Existing globally unique email, 1–255 characters | Organization UUID or NULL | Active user; exact existing email matching semantics |
| `sphere_auth.user_refresh_org(text)` | Complete SHA-256 refresh-token hash | Organization UUID or NULL | Not revoked; expiry strictly in the future |

Functions return no password hash, MFA secret, user row, token, role or permissions.
They are SQL/STABLE/STRICT/SECURITY DEFINER, use schema-qualified relations, pin
search_path to `pg_catalog, pg_temp` and set row_security off locally. An owner
unable to bypass table RLS gets an error; callers do not receive BYPASSRLS. CREATE
refuses name collisions instead of replacing operator functions. PUBLIC execution
is revoked in the same migration transaction.

After discovery, the normal Session binds the UUID and queries by both credential
and organization. Login still verifies the password and current active state.
Refresh/logout retain SELECT FOR UPDATE and a refreshed snapshot for token
consumption. Refresh reloads the user and rejects inactive or moved identities;
the old token cannot follow its user into another organization. Token issuance
commits SQL before returning credentials; fresh pooled Sessions stay unscoped.

Email is not a secret. A database caller with EXECUTE can discover the organization
of a guessed active email. This is a deliberate metadata disclosure to the backend
database role, not a password verifier or an HTTP organization-lookup endpoint.
The email resolver must not be repurposed as proof of authentication. The separate
[device hash resolvers](device-credential-bootstrap.md) have a different input
threat model. Arbitrary SQL callers able to SET a tenant GUC remain outside RLS's
application-isolation guarantee.

## Runtime grants and rollout

Apply the migration as the trusted migration/table owner. Keep that role separate
from runtime logins; do not give runtime ownership, role membership or BYPASSRLS.
Grant the reviewed runtime role only the required function privileges:

```sql
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.user_login_org(text),
    sphere_auth.user_refresh_org(text) TO sphere_runtime;
```

Replace `sphere_runtime` with the separately provisioned runtime login. These are
additional to the device/API-key function grants. Missing grants fail closed;
never add a privileged application-engine fallback. Review function ownership,
schema ownership and any operator FORCE RLS policies before rollout. This audit
applied the migration and grants only in its isolated PostgreSQL database.

MFA now stores JSON user_id/org_id in Redis `mfa:state:v2:<opaque-state-token>`
after password verification, with the existing five-minute TTL. The second request
validates this server-written identity, binds the tenant, reloads the active
MFA-enabled user, verifies TOTP and atomically consumes the challenge with DEL.
It then commits the new SQL refresh token. Client request/response formats stay
unchanged; tenant fields supplied by HTTP clients are not trusted.

The new Redis namespace deliberately invalidates in-flight legacy challenges.
Users must restart the password step after upgrade or rollback. Coordinate the
application cutover: mixed old/new workers do not share MFA challenges, and routing
between versions may require another login. Old workers cannot parse v2 payloads
because they look under a different key. Malformed/missing v2 identity returns 401.

Downgrade drops only the two user functions; device functions/schema remain.
Roll back the application first. Do not remove functions still used by serving
workers. No production migration, restart or deployment was performed.

## Evidence and limits

[Before: 10 failed / 8 passing denial controls](../audits/2026-09-05/evidence/user-bootstrap-before.txt).
[After: 105 related checks passed](../audits/2026-09-05/evidence/user-bootstrap-after.txt),
including [34 new PostgreSQL/Redis cases](../../tests/production/test_user_bootstrap_runtime.py).
The initial baseline contained 18 HTTP cases; function security and additional
MFA/SQL-failure cases were added after introducing the bootstrap mechanism.

Tests use actual non-owner credentials, real ASGI HTTP handlers, row locks,
commits and Redis. They cover both organizations, wrong-tenant headers, every
refresh source, SQL logout revocation, one concurrent refresh winner and usable
child, two simultaneous MFA reads with one consumer, identity changes, malformed
and legacy challenges, explicit grants, owner protection and temporary-table
shadowing. Injected SELECT 1/0 after flush proves rollback and retry. SQLite unit
adapters substitute four exact lookup calls; they do not implement RLS. Raw
AsyncMock service tests mock tenant-binding boundaries; PostgreSQL tests do not.

This is not a distributed transaction between Redis and PostgreSQL. If MFA DEL
succeeds and SQL then fails, no credentials are issued and a new password step is
required. Lost responses after successful commit, refresh-family revocation,
concurrent administrator changes after authorization, MFA guessing/recovery policy,
browser state during rolling upgrades and full network failover remain separate
work. Global workers still require tenant discovery and propagation. The complete
suite is not wholly a non-owner suite, and it does not certify production readiness.

Primary basis: PostgreSQL [function security guidance](https://www.postgresql.org/docs/15/sql-createfunction.html)
and [row security behavior](https://www.postgresql.org/docs/15/ddl-rowsecurity.html).
