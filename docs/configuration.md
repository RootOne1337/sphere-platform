# Configuration Reference

> Configuration reference; прежняя метка v4.7 не является текущим release.
> Значения примеров не являются настройками установленного pilot; [текущий статус](operations/CURRENT-STATE.md).

---

Backend `Settings` read `.env` followed by `.env.local` relative to the process
working directory; `.env.local` overrides `.env`, and process environment values
take priority over both. The comment in `config.py` implying the reverse priority
is not the Pydantic Settings source order. Settings do not describe every shell/Compose variable. The
Windows launchers pass one selected env file to Compose (`.env.local`, else `.env`);
full-deploy preserves an existing `.env` instead of shadowing it with generated
credentials. See the [startup contract](operations/STARTUP.md). For a new installation,
copy `.env.example` as a starting point and fill in the required values.

Copy the template only when the destination does not already exist, then provide
values appropriate to the selected deployment. `scripts/generate_secrets.py`
can create a candidate, but `--output` **overwrites** its destination; it does
not update running services. A generic `.env.generated` is not covered by the
listed `.gitignore` rules: protect any generated file outside the repository and
do not print it into shared logs. The generator also randomizes `AWG_H1`–`H4`;
do not apply those values to existing tunnels without a coordinated migration.

> **Security:** Never commit `.env.local` or `.env` to version control.
> Use `detect-secrets` baseline and pre-commit hooks to prevent accidental leaks.

---

## Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_USER` | Base Compose | `sphere` in Compose | PostgreSQL initialization user; not a `Settings` field |
| `POSTGRES_PASSWORD` | Base Compose | — | PostgreSQL initialization password; not a `Settings` field |
| `POSTGRES_URL` | Deployment-dependent | Localhost development URL with sample credentials | Asyncpg URL; full/production Compose construct it from user and password |
| `DB_POOL_SIZE` | | `10` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | | `5` | Max overflow connections above pool_size |
| `DB_POOL_TIMEOUT` | | `30` | Seconds to wait for a connection from pool |

The built-in localhost URL contains development credentials and is not a
production configuration. Compose does not forward an independently supplied
`POSTGRES_URL` in the full or production overlay: both construct the URL from
`POSTGRES_USER` and `POSTGRES_PASSWORD`. Test URL compatibility of provisioned
credentials without exposing them; PostgreSQL init values do not rotate an
existing database role.

---

## Redis

Base and production Compose declare a **512 MiB dataset cap and a 3072 MiB
container ceiling**. The ceiling is not a memory reservation and the source
configuration is not proof of an already running container's limit. Persistence
and stream capacity must be verified against the workload and selected profile.
See the [memory contract and evidence](operations/REDIS-MEMORY.md); the separate
preview template remains unvalidated.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_PASSWORD` | Base Compose | Empty in Settings | Redis AUTH password; Settings rejects a nonempty value beginning `CHANGE_ME` |
| `REDIS_URL` | Deployment-dependent | `redis://localhost:6379/0` | Redis URL; full/production Compose construct it from `REDIS_PASSWORD` |

The backend model does not enforce a 32-character password minimum. Use a strong
independent secret appropriate to the deployment. Full/production Compose build
`REDIS_URL` rather than forwarding a separately supplied URL.

---

## Authentication / JWT

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET_KEY` | ✓ | — | Signing secret; Settings requires at least 32 characters and rejects certain insecure prefixes |
| `JWT_ALGORITHM` | | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | | `30` | Access token TTL in minutes |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | | `7` | Refresh token TTL in days |

Provision an independent cryptographically random key through the deployment's
secret mechanism. The template's 64-character recommendation is stronger than
the model's enforced 32-character minimum.

---

## Recoverable game credentials

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ACCOUNT_CREDENTIAL_KEYS` | For account writes, reveal and dispatch | Empty | 1..8 independent Fernet keys separated by commas, newest first; provision through a secret store |

Empty/invalid keys disable credential operations with no plaintext fallback.
Schema migration alone does not encrypt existing account passwords. Follow the
[credential migration and rotation procedure](security/account-credentials.md)
before enabling the new backend. Keep keys separate from PostgreSQL backups and
JWT/VPN secrets; preserve the keys needed for retained backups. This field is not
generated by the existing all-secrets generator.

## VPN / AmneziaWG

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WG_ROUTER_URL` | VPN integration | `http://localhost:8001` | WireGuard router service URL |
| `WG_ROUTER_API_KEY` | VPN integration | Empty | API key for WG router |
| `WG_SERVER_PUBLIC_KEY` | VPN config generation | Empty | Server WireGuard public key |
| `WG_SERVER_ENDPOINT` | VPN config generation | `vpn.example.com:51820` | Example endpoint, replace for clients |
| `WG_PSK_ENABLED` | | `true` | Enable pre-shared keys per peer |
| `VPN_KEY_ENCRYPTION_KEY` | VPN peer encryption | Empty | Fernet key for peer config encryption; absence causes 503 for the dependent operation |
| `VPN_POOL_SUBNET` | | `10.100.0.0/16` | CIDR block for peer IP allocation |
| `VPN_SERVER_HOSTNAME` | | Empty | Settings field; no backend consumer was found in this checkout, so it does not by itself establish a QR endpoint |
| `VPN_PROFILE_ENCRYPTION_KEYS` | Profile imports/reads | Empty | Independent Fernet key ring for the encrypted profile catalog; 1–8 keys, newest first |
| `VPN_PROFILE_POSTGRES_URL` | Profile catalog HTTP | Empty | Separate non-owner asyncpg login to the same database; no fallback to the application URL |

**AmneziaWG obfuscation parameters (coordinate changes with existing tunnels):**

| Variable | Default | Description |
|----------|---------|-------------|
| `AWG_JC` | `4` | Junk packet count |
| `AWG_JMIN` | `40` | Junk packet min size |
| `AWG_JMAX` | `70` | Junk packet max size |
| `AWG_S1` | `51` | Init packet junk size |
| `AWG_S2` | `45` | Response packet junk size |
| `AWG_H1` | `2545529037` | Magic header 1 |
| `AWG_H2` | `1767770215` | Magic header 2 |
| `AWG_H3` | `2031675751` | Magic header 3 |
| `AWG_H4` | `3699611814` | Magic header 4 |

The profile catalog uses separate keys and a separate database principal;
provision them through a secret store and follow the
[VPN profile procedure](operations/VPN-PROFILES.md). Both full and production
overlays explicitly forward the profile fields. Their presence in an env file
alone does not validate the credentials or permissions.

---

## Application

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEBUG` | | `false` | Enable debug mode (NEVER true in production) |
| `LOG_LEVEL` | | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ENVIRONMENT` | | `development` | `development`, `staging`, `production` |
| `SERVER_PUBLIC_URL` | Deployment-dependent | `http://10.0.2.2:8000` | Backend public URL exposed to agents; production overlay constructs it from `SERVER_HOSTNAME` |
| `COOKIE_SECURE` | | `false` | Forces secure refresh cookies; HTTPS detected on the request also enables `Secure` |
| `DEV_SKIP_AUTH` | | `false` | JWT bypass for development; never enable in production |

`SERVER_HOSTNAME` is not a backend Settings field: base Compose uses it in
nginx (default `sphere.example.com`), and the production overlay interpolates
it into public URLs. Extra CORS origins use the separate process environment
variable `CORS_EXTRA_ORIGINS`. The source does not make the JWT bypass safe by
checking `ENVIRONMENT`; production Compose explicitly forces it off.

---

## n8n Integration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `N8N_ENCRYPTION_KEY` | n8n | No Compose default | n8n credential encryption key; Compose interpolates it into the n8n container |

---

## MinIO (S3-compatible storage)

S3-compatible service in Compose. Private task screenshot reads require separate
configuration and a recorded storage key; Android capture alone does not imply
an uploaded artifact. See [private screenshot reads](#private-task-screenshot-reads).

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MINIO_ROOT_USER` | Base Compose | — | MinIO admin username; `spheredev` is a template value, not the Compose default |
| `MINIO_ROOT_PASSWORD` | Base Compose | — | MinIO admin password |

---

## Android Agent OTA

| Variable | Required | Description |
|----------|----------|-------------|
| `APK_SIGNING_CERT_SHA256` | Not required by Settings; default empty | Fingerprint field in the model and template. A repository search found no backend consumer in this checkout; setting it alone does not establish OTA verification or signing policy. |

**Get certificate fingerprint:**
```bash
keytool -printcert -file app.cer | grep "SHA256:"
# Or from keystore:
keytool -list -v -keystore mykeystore.jks | grep "SHA256:"
```

---

## Frontend (Next.js)

For a host development process, `frontend/.env.local` is one possible source.
Compose supplies its own environment and an existing browser bundle may already
contain build-time values:

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Browser API base; frontend code defaults to `/api/v1` when absent |
| `NEXT_PUBLIC_WS_URL` | WebSocket base; consumption depends on the client and an empty string differs from an absent variable |
| `NEXT_PUBLIC_API_BASE_URL` | Next dev rewrite upstream; full Compose sets `http://backend:8000` |
| `NEXT_PUBLIC_DEV_SKIP_AUTH` | Supplied by the full overlay and forced `false` by production; no frontend consumer was found in this checkout |

---

## Docker Compose Variables

Consumed directly by `docker-compose.yml`:

| Variable | Description |
|----------|-------------|
| `POSTGRES_USER` | PostgreSQL user for container init |
| `POSTGRES_PASSWORD` | PostgreSQL password for container init |
| `REDIS_PASSWORD` | Redis AUTH password for container command |

This table lists only examples, not the complete Compose interpolation contract.
Base Compose also requires MinIO root credentials; inspect the selected overlays.

---

## Orchestration and task watchdog

Do not treat the former `ORCHESTRATION_LOOP_INTERVAL`, `TASK_HEARTBEAT_TIMEOUT`,
`TASK_HEARTBEAT_CHECK_INTERVAL`, `EVENT_REACTOR_ENABLED`,
`EVENT_REACTOR_MAX_BATCH` or `NICK_GENERATOR_LOCALE` table as supported environment
configuration: these names are not consumed by the backend in this checkout.
For current behavior inspect the relevant source and tests; for example, the task
watchdog interval is a code constant in `backend/tasks/task_heartbeat_watchdog.py`,
not a setting controlled by that former table.

---

## Settings, Compose and frontend builds

The defaults in `backend/core/config.py` describe Settings when the process has
no overriding value. A Compose env file supplies values for interpolation; it
does not automatically forward every entry into a container. Inspect the
`environment` entries in the selected overlays and verify the effective settings
without exposing secrets. In particular, the full and production overlays do not
explicitly forward `DB_POOL_SIZE` or `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`; an entry
in a Compose env file alone is not evidence that the running backend uses it.
Development bind mounts and explicitly supplied process environment may differ
from the production image, which does not contain the checkout's env files.

Frontend `NEXT_PUBLIC_*` values also depend on the selected build and deployment;
an env edit or container restart does not by itself establish the values compiled
into an existing browser bundle. Verify the built artifact and the actual ingress.

### Explicit backend forwarding in the main overlays

The following describes source declarations, not a resolved or running stack.
The production overlay can be combined with full; Compose merge order and the
chosen files determine the effective result.

| Source | Backend environment behavior |
| --- | --- |
| Base | Defines infrastructure, not a backend service. PostgreSQL and Redis passwords and MinIO root credentials are required for the base interpolation. |
| Full | Constructs PostgreSQL and Redis URLs; forwards the JWT secret, account/profile keys, private screenshot settings, router values, `AWG_H1`–`AWG_H4`, selected app fields and bootstrap slug. It mounts the checkout at `/app`, so dotenv files can additionally be visible to Settings. |
| Production | Constructs PostgreSQL and Redis URLs; forwards the JWT secret, account/profile keys, router values and `AWG_H1`–`AWG_H4`; fixes `DEBUG=false`, `DEV_SKIP_AUTH=false`, `ENVIRONMENT=production`, `LOG_LEVEL=INFO` and `AGENT_CONFIG_ENV=production`; constructs `SERVER_PUBLIC_URL` from `SERVER_HOSTNAME`. Its image does not copy the checkout's dotenv files. |

For example, neither overlay explicitly forwards `DB_POOL_*`, `JWT_ALGORITHM`,
JWT TTLs, `COOKIE_SECURE`, `WG_SERVER_PUBLIC_KEY`, `WG_SERVER_ENDPOINT`,
`WG_PSK_ENABLED`, `VPN_KEY_ENCRYPTION_KEY`, `VPN_POOL_SUBNET`, `AWG_JC`,
`AWG_JMIN`, `AWG_JMAX`, `AWG_S1`, `AWG_S2`, or `APK_SIGNING_CERT_SHA256`.
Supplying one only as a Compose interpolation variable is therefore insufficient
without another effective source. Conversely, full/production explicitly set
`AWG_H1`–`AWG_H4` and router settings from interpolation without defaults:
an absent value can become empty instead of falling back to Settings; empty
integer headers fail typed validation. Full passes screenshot settings;
production alone does not. Full followed by production may retain full's
environment entries that the latter does not override.

The Compose URL strings interpolate credentials directly. Check compatibility
with URL syntax and each consumer before changing them, without exposing the
value. Neither successfully parsing Settings nor rendering Compose proves that
network, access, image identity or migrations are correct.

### Agent configuration

| Settings field | Default | Meaning |
| --- | --- | --- |
| `AGENT_CONFIG_DIR` | `agent-config` | Directory for environment configuration files |
| `AGENT_CONFIG_ENV` | `development` | Selects the agent configuration environment; production overlay sets `production`, local-pilot sets `development` |
| `AGENT_CONFIG_CACHE_TTL` | `300` | Redis cache TTL in seconds; zero disables this cache |

`SERVER_PUBLIC_URL` is the backend URL advertised to agents; `SPHERE_CONFIG_URL`
in the template is a separate Android build input, not a Settings field. Neither
an example hostname nor an APK build input proves agent connectivity.

### Direct transport and diagnostic gates

These Settings fields default off or empty. They are not explicitly forwarded
by the main full/production overlays; a deployment using them must provide an
appropriate effective process source. Their existence does not prove that direct
transport is available or authorized for a device.

| Field | Settings default | Purpose |
| --- | --- | --- |
| `DIRECT_TRANSPORT_PROBE_ENABLED` | `false` | Enables the diagnostic gate |
| `DIRECT_TRANSPORT_PROBE_DEVICE_IDS` | Empty set | Explicit canary device allowlist; empty admits none |
| `DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED` | `false` | Separate finite video-probe gate |
| `DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED` | `false` | Separate live-video gate |
| `DIRECT_TRANSPORT_INPUT_ENABLED` | `false` | Separate input gate |
| `DIRECT_PROBE_TURN_URLS` | Empty tuple | Operator-owned TURN endpoints |
| `DIRECT_PROBE_TURN_SECRET` | Empty | Server-side TURN REST secret |
| `DIRECT_PROBE_TURN_RELAY_ONLY` | `false` | Diagnostic relay-only selection |
| `DIRECT_PROBE_MDNS_RESOLVER_URL`, `DIRECT_PROBE_MDNS_RESOLVER_KEY` | Empty | Optional discovery helper endpoint and server-only key |

The allowlist and TURN URLs are complex Pydantic Settings values; when supplied
through environment variables, use JSON arrays. Other admission, runtime and
frontend build gates still apply. See [direct transport design](design/BROWSER-DIRECT-TRANSPORT.md)
for operational boundaries.

---

## Secret Rotation

Plan rotation for the actual environment and all consumers; back up and test
recovery in an isolated environment first. Avoid exposing secrets in logs,
commands, Git or support artifacts. A Compose `restart` does **not** recreate a
container with changed Compose environment, and editing an env file does not
change an existing PostgreSQL role password.

- **JWT signing key:** coordinate the change across API instances and plan for
  sessions signed with the old key to stop validating. Test login and refresh.
- **PostgreSQL:** change the credential in PostgreSQL through an approved procedure,
  coordinate all connection URLs and dependent services, then recreate affected
  containers with the selected Compose project and env. Check connectivity and
  privileges; retain a tested rollback. Do not treat init variables as rotation.
- **Redis:** coordinate the server authentication configuration and all clients,
  then recreate affected containers as required. Verify authentication and recovery.
- **Encrypted VPN profiles and account credentials:** retain the old keys needed
  to decrypt existing data until a tested migration or re-encryption is complete.
  Changing or dropping a key without that plan can make stored credentials unusable.

The exact procedure and downtime depend on the deployment; this repository does
not establish a zero-downtime rotation. See [startup](operations/STARTUP.md),
[deployment](deployment.md), [credential keys](security/account-credentials.md)
and [database recovery](runbooks/03-database-failure.md).

---

## Validation

The `Settings` class (`backend/core/config.py`) parses typed fields and runs its
configured validators at startup. A missing required field can produce a
`ValidationError`. This does not verify service availability, permissions,
container environment propagation or the suitability of every configuration value.

Do not use `docker compose run` as a read-only validation: it creates a container
and may start dependencies. Use isolated tests with synthetic values and inspect
the selected deployment's effective settings without printing credentials. Base
Compose alone does not define a `backend` service.

## Enrollment bootstrap identity

| Variable | Default | Contract |
| --- | --- | --- |
| `SPHERE_BOOTSTRAP_ORG_SLUG` | `default` | Exact organization shared by administrator CLI, enrollment CLI and the development startup hook. Persist it in the selected Compose env file; export it explicitly for direct host CLI use. |

The enrollment key comes from the effective agent-config environment, not a
second hard-coded startup key. Development hook and explicit CLI share validation
and SQL serialization. A disabled, expired, conflicting or insufficient key is
never silently repaired. The hook warns and keeps the API available for operator
repair; the CLI fails. Production has no automatic enrollment hook provisioning.
See [startup behavior and diagnostics](operations/STARTUP.md) and
[pilot acceptance](operations/PILOT-ACCEPTANCE.md).

## Administrator bootstrap mode

Full-deploy uses `--create-only`: `SPHERE_ADMIN_EMAIL` selects the operator identity
and `SPHERE_ADMIN_PASSWORD` is a candidate for first creation only. An existing active
super_admin retains credentials, role and MFA; changed candidate input does not reset
it. Disabled/wrong-role/foreign-org conflicts fail explicitly. Direct admin CLI uses
`ADMIN_EMAIL`/`ADMIN_PASSWORD`; omit `--create-only` only for an intentional reset.
Initial passwords are shown after commit and before enrollment; Bash retains its
existing `.admin-credentials` artifact only for a newly created account. See
[startup outcomes and unknown-commit limits](operations/STARTUP.md).

## Optional development authentication switch

The full Compose overlay passes `DEV_SKIP_AUTH=false` when the variable is absent
or empty (AUD-86). Previously it passed an empty string, which prevented Settings
from loading even with a freshly generated installation configuration. Explicit
`true` remains a development option; the production overlay forces `false`.
Backend boolean validation remains strict. Generated configuration still requires
operator-supplied addresses/integration values; this fix does not validate the whole
installation. [Startup contract](operations/STARTUP.md).

## PostgreSQL initialization identity

For a fresh cluster, `POSTGRES_USER` selects the entrypoint user and therefore the
owner of the n8n database created by `infrastructure/postgres/init.sql` (AUD-87).
The default remains sphere; a configured alternative no longer fails on a missing
hardcoded sphere role. Both fresh initialization and restart retaining database
contents are tested. Existing clusters do not re-run init.sql, and changing the
environment does not rename database roles. [Startup and partial-init limits](operations/STARTUP.md).

## Private task screenshot reads

Since application source `5fcf18a` (2 October 2026), task images are read through
the authenticated Task API. Browsers receive Blob images from their API session;
they do not need a public MinIO endpoint or storage credentials.

Configure `SCREENSHOT_STORAGE_ENDPOINT` as host:port, the server-only
`SCREENSHOT_STORAGE_ACCESS_KEY` / `SCREENSHOT_STORAGE_SECRET_KEY`,
`SCREENSHOT_STORAGE_SECURE` (default true), and `SCREENSHOT_STORAGE_REGION`
(default us-east-1). Use a bucket-scoped read account for `sphere-screenshots`.
The full Compose overlay forwards these optional settings. The production-only
overlay does not explicitly forward them; full plus production has a different
merged configuration. Inspect the selected file combination and provide the
settings through an appropriate deployment mechanism. After changing container
environment, recreate the affected container using the selected project and
configuration; `restart` alone does not apply changed Compose environment.
Verify the effective configuration without exposing credentials. Empty
configuration disables reads with HTTP503, without preventing task execution,
login or manifest reads.

This does not enable Android DAG artifact uploads. The current action returns
an Android-local path; that file is not a server screenshot until an upload is
accepted and its key is recorded. A historical pilot observation recorded storage reads as disabled; check the
selected deployment's actual configuration. [Task contracts, tests and remaining upload work](audits/2026-10-02/TASK-ARTIFACTS-AND-RERUN.md).

## Scope and remaining verification

This reference was compared with all 55 annotated fields in
[`Settings`](../backend/core/config.py), the checked-in [template](../.env.example),
the base, full and production Compose files, selected local-pilot forwarding,
the backend image, the secret generator, and the cited VPN and agent configuration
consumers. Presence of a field name is not a behavioral test of every consumer.

The review did not resolve every possible overlay combination, enumerate every
environment variable consumed outside `Settings`, inspect real dotenv files or
secret stores, render a deployment configuration, validate an installed artifact,
or connect to services or devices. Preview, remote, review, tunnel, monitoring
and infrastructure-specific Compose configurations require their own checks.
Actual credentials, network paths, build-time frontend settings, operational
permissions and the result of any key rotation remain deployment-specific.
