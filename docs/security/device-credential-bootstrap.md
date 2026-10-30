# Device credentials: tenant discovery and runtime rollout

Updated 10 September 2026. AUD-58 fixes opaque API-key and device-refresh tenant
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

Alembic `20260909_credential_lookup` adds two functions;
`20260910_device_refresh_retry` extends device lookup for one retained rotation:

| Function | Input | Output | Eligible row |
| --- | --- | --- | --- |
| `sphere_auth.api_key_org(text)` | Complete SHA-256 API-key hash | Organization UUID or NULL | Active key, no expiry or not expired |
| `sphere_auth.device_refresh_org(text)` | Complete SHA-256 refresh-token hash | Organization UUID or NULL | Active device, unexpired current refresh; current or retained previous hash (AUD-69) |

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

Downgrade of the original bootstrap migration removes only these functions and
the empty schema, without CASCADE. The newer refresh-retry migration restores
the previous lookup and removes only its two metadata columns.
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

After authentication closes its Session, Android progress, start receipts, terminal
results and device events each bind a fresh Session to the authenticated organization
(AUD-61). [Post-auth ASGI regressions](../../tests/production/test_agent_messages_runtime.py)
exercise the non-owner SQL paths, replay and commit-before-result_ack. This does not
make PubSub notifications, Redis lock release or EventTrigger effects a durable outbox.

AUD-69/70 add [recoverable device refresh](device-refresh-recovery.md): a persisted
operation UUID lets the client recover one unconsumed successor after lost commit/
HTTP response. Legacy requests without that header still reject old-token replay. Re-enrollment preserves the device ID but rotates
credentials; it does not promise identical responses. A retained enrollment key
can re-enroll a matching fingerprint; device attestation/proof of possession and
enrollment-key retirement remain separate work. User email/MFA/refresh bootstrap
is covered separately by [AUD-62 and its rollout contract](user-auth-bootstrap.md).
Global jobs, full APK runtime and 10–64 emulator load remain unverified here.

Primary basis: PostgreSQL [CREATE FUNCTION security-definer guidance](https://www.postgresql.org/docs/15/sql-createfunction.html)
and [row security behavior](https://www.postgresql.org/docs/15/ddl-rowsecurity.html).


## Concurrent enrollment-key changes

AUD-60 proves that an enrollment request waiting on last_used_at UPDATE could use
an earlier key snapshot after an administrator committed revoke, expiry or removal
of device:register. Authentication now locks and refreshes the key first, then
checks active/expiry and exposes current permissions to the handler. The lock stays
with the caller's transaction. Two independent runtime requests are observed in
PostgreSQL Lock waits before the administrator commits in each regression.
[Three failures before](../audits/2026-09-05/evidence/enrollment-revocation-before.txt)
and [31 related checks after](../audits/2026-09-05/evidence/enrollment-revocation-after.txt)
are retained. This does not revoke an already-authorized open socket or promise
instant cancellation of an operation whose authorization won the lock first.
