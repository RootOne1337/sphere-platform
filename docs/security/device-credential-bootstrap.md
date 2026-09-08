# Device credentials: tenant discovery and runtime rollout

Updated 9 September 2026. AUD-58 fixes opaque API-key and device-refresh tenant
discovery under a non-owner PostgreSQL login. Full production rollout remains
blocked by other unscoped auth/jobs and runtime-role provisioning. Tests use only
the dedicated local PostgreSQL 15/Redis services and synthetic credentials.

## Why registration and refresh failed

Enrollment calls `APIKeyService.authenticate()` before knowing its organization.
Device refresh similarly locates a device by the hash of its opaque refresh token.
The tenant policies deny these initial unscoped SELECTs. Correct credentials thus
returned 401 with a real runtime role even though privileged integration tests passed.

[Before evidence](../audits/2026-09-05/evidence/device-bootstrap-before.txt): seven
failures and six negative controls. The initial concurrent HTTP cases used a
one-connection pool; the retained regressions additionally use three connections
and observe at least two PostgreSQL lock waits before releasing the row owner.

## Narrow lookup boundary

Alembic `20260909_credential_lookup` adds two functions:

| Function | Input | Output | Eligible row |
| --- | --- | --- | --- |
| `sphere_auth.api_key_org(text)` | Complete SHA-256 API-key hash | Organization UUID or NULL | Active key, no expiry or not expired |
| `sphere_auth.device_refresh_org(text)` | Complete SHA-256 refresh-token hash | Organization UUID or NULL | Active device, unexpired refresh |

These are a deliberate, limited exception to RLS, executed as their trusted owner.
They return no credential, key prefix, permissions, device metadata or user record.
They cannot enumerate organizations without candidate full credential hashes.
The SQL is fixed, tables are schema-qualified, and search_path is pinned to
`pg_catalog, pg_temp`; temporary tables cannot replace the referenced relations.
`row_security=off` raises if the owner cannot bypass the relevant table policy;
it does not grant RLS bypass to the caller. Settings and execution identity restore
on return. Functions are STRICT/STABLE and have no writes or dynamic SQL.

PUBLIC has no schema access or function execution. After tenant discovery, the
application binds the UUID to the Session and queries the credential again with
both its full hash and organization. Active/expiry/permission checks remain in the
application. Redis never becomes the credential authority. Connection cleanup
does not leave another request's tenant behind.

Knowledge of a full stored hash can reveal its organization to a caller with
function EXECUTE; possession of a hash alone does not authenticate at HTTP, which
hashes the raw token again. Protect hashes, database access and function ownership.
This mechanism assumes high-entropy generated secrets; it is not an email/password
lookup mechanism. An arbitrary SQL caller capable of SET can choose a tenant GUC;
RLS does not isolate against compromise of backend database credentials.

## Migration and grants

Upgrade with the trusted migration/table-owner credentials. The migration refuses
an existing `sphere_auth` schema instead of adopting or replacing it. Creation and
PUBLIC revocation occur in one transaction. Keep the function owner separate from
runtime logins and prevent runtime membership in that owner role. A dedicated
protected table-owner role is preferable to a superuser function owner.

After reviewing the actual runtime role, grant only:

```sql
-- Replace sphere_runtime with the reviewed, separately provisioned runtime role.
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.api_key_org(text),
    sphere_auth.device_refresh_org(text) TO sphere_runtime;
```

Do not grant CREATE, function ownership, table ownership or BYPASSRLS to runtime.
Missing grants fail closed; they must not trigger an application fallback to a
privileged engine. Migration ownership must be able to read `public.api_keys` and
`public.devices` across tenants. Existing operator FORCE RLS/ownership rules need
review. The current Compose owner login remains rejected by the production guard.

Downgrade removes only these functions and the empty schema, without CASCADE.
Coordinate application rollback first: code using the functions cannot work after
they are removed. Operator objects in the schema deliberately block its removal.
No production migration or grant was performed during the audit.

## Verification and remaining work

[18 runtime regressions](../audits/2026-09-05/evidence/device-bootstrap-runtime-after.txt)
cover allowed/rejected enrollment and refresh, re-enrollment identity, real SQL
lock contention, one refresh winner, replay/child usability, post-flush SQL failure
and retry, explicit grants, owner protection and temporary-table shadowing.
The original related [83-test snapshot](../audits/2026-09-05/evidence/device-bootstrap-after.txt)
also covers existing auth/discovery contracts. SQLite substitutes only the two
exact tenant-only lookup calls in test fixtures; it does not prove RLS or function
security. PostgreSQL tests execute the actual migration functions.

Refresh response loss after a successful commit still requires recovery: replay
of the old token is rejected. Re-enrollment preserves the device ID but rotates
credentials; it does not promise identical responses. A retained enrollment key
can re-enroll a matching fingerprint; device attestation/proof of possession and
enrollment-key retirement remain separate work. User email/MFA/refresh bootstrap,
global jobs, full APK runtime and 10–64 emulator load remain unverified here.

Primary basis: PostgreSQL [CREATE FUNCTION security-definer guidance](https://www.postgresql.org/docs/15/sql-createfunction.html)
and [row security behavior](https://www.postgresql.org/docs/15/ddl-rowsecurity.html).
