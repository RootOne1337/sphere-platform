# EP-010 Stage B: tenant fleet coverage in the monitoring UI

**Date:** 5 October 2026. **Criterion:** EP-010 remains OPEN.
**Acceptance overlay:** 9 accepted / 41 open; immutable 50-item baseline retained.
**Scope:** read-only tenant inventory/presence/VPN coverage endpoint and presentation.
This document records the contract; installation evidence is added only after
the committed API/UI images have passed checks and actual live observation.

Previous installed foundation:
[Android VPN observation clock and ownership](ENTERPRISE-ANDROID-VPN-OBSERVATION.md).
Broader requirements and outstanding work:
[delivery and coverage plan](ENTERPRISE-LIVE-COVERAGE-NEXT.md),
[product audit](ENTERPRISE-PRODUCT-AUDIT.md),
[implementation ledger](ENTERPRISE-PRODUCT-IMPLEMENTATION.md).

## Why a new endpoint is needed

The device registry, VPN assignments and retained handshakes are different
sources. A configured SQL peer is not a fresh Android report, and neither proves
public tunnel availability. A missing Redis record must not be converted into
zero active devices or a successful VPN observation. The monitoring page needs
these counts, their timestamps and missing-data reasons in one bounded response.

## Contract and sources

`GET /api/v1/monitoring/fleet-coverage`, response schema version 1.
Organization is derived from the authenticated principal and tenant database
dependency. A supplied query-string organization does not change the scope.
No arbitrary host, query, tenant ID or device command is accepted.

| Section | Source and exact scope | Measured counts | Limit of evidence |
| --- | --- | --- | --- |
| inventory | SQL active devices of current organization | total | Not a count of live connections |
| presence | Redis records for those device IDs | online, busy, connecting, offline, error, unknown | Missing record is unknown; not offline |
| android_vpn | Agent-managed VPN report projected from those records | active, inactive, stale, unknown | Does not prove external IP or successful traffic |
| vpn_assignment | SQL peers of current organization | free, assigned, error, provisioning, revoking, outside_active_inventory | Last count is an assigned subset, not another lifecycle state |
| handshakes | Retained SQL handshakes for assigned peers bound to active devices of current organization | recent, stale, unknown, inactive | No current router probe occurs in this request |
| transport_tunnels | Provider probes are not connected | null | Always unmeasured in schema version 1 |

Every section has its own state, source, observed_at, counts, reason and optional
max_age_seconds. Ready means a source snapshot was received, not that the service
or its data plane is healthy. Failed, forbidden, limited and unmeasured sources
carry null counts and null observed_at. Measured zero remains an actual zero.

## Presence and Android evidence

For online/busy, Redis must contain the current WebSocket owner and an aware
server heartbeat with age in [0, 120) seconds. Missing owner, expired heartbeat,
future heartbeat, corrupt/missing record or a mismatched record device ID maps to
unknown. Offline, error and connecting remain reported cached states.

Android uses its independently timed VPN report from the previously installed
foundation. Fresh explicit true is active; fresh explicit false is inactive.
Expired reports are stale. Absent, mismatched-owner or future evidence is unknown.
An unrelated heartbeat does not renew the VPN report. Counts partition the SQL
active inventory and never infer false from null.

## SQL VPN evidence

Lifecycle counts include all tenant peers. Assigned peers whose device is absent,
inactive, unbound or outside the tenant active inventory are separately counted.
Only assigned peers bound to the tenant active inventory enter handshake counts.

Handshake age in [0, 180) seconds with is_active=true is recent. The same recent
timestamp with is_active=false is inactive. Age >=180 is stale. Missing or future
timestamps are unknown. Provisioning/free/revoking/error peers do not silently
enter the assigned-device handshake denominator. These are retained SQL values;
timestamps describe snapshot time, not proof of a fresh router interrogation.

## Authorization and session boundaries

Device read permission is required for the endpoint. VPN read permission controls
Android VPN, assignment and handshake sections independently. Script runners can
read fleet inventory/presence without receiving VPN counts. Authentication remains
required; no credentials, peer keys, private IPs, device identifiers or foreign
tenant details are returned in this aggregate response.

The frontend query key includes organization, user, role and session version.
A response for a different organization or an unsupported schema is rejected.
The request passes TanStack Query's AbortSignal to the API client, so unmounting
or changing query scope can cancel a pending read. Prior-session counts cannot
appear as current-session observations.

## Budgets and failure isolation

The inventory query selects at most 5,001 IDs and a window count. The SQL total
remains exact within its snapshot. Above the 5,000-device budget, Redis presence
and Android sections become limited, rather than partially counted. SQL peer
counts remain independently available where permitted.

Inventory and peer reads each have a three-second asynchronous timeout and
SAVEPOINT. Redis reads have a two-second aggregate timeout with MGET chunks of
500 IDs and no SCAN. The route uses the existing binary Redis client because
device statuses are MessagePack, not UTF-8 text. A failed later chunk discards all partial counts. Recoverable
peer source failure does not hide valid inventory or Android evidence.

Failure of authentication, tenant setup or an unrecoverable database connection
may still produce the platform's normal HTTP error; a JSON success response is
not guaranteed for every database outage. UI HTTP errors hide cached counts.
Logs record structured event and exception class, not raw SQL/upstream details.

Empty tenant inventory produces a measured zero partition without querying Redis.
That proves the SQL denominator is zero, not that Redis is healthy.

The endpoint is a request-time aggregate. SQL and Redis are sequential snapshots;
there is no distributed transaction or independent metrics producer. Each browser
read still incurs bounded source work. Fleet size and multi-operator load testing,
producer decoupling and shared sampling remain open acceptance work.

## Delivery and presentation

The monitoring page shows six source cards in a responsive one/two/three-column
grid. Each card provides count labels, evidence boundaries, its source time and
missing-data state. Footer links reach devices and VPN assignments.

Device/task/VPN events invalidate the mounted coverage query through the existing
500 ms coalesced event adapter. Initial connection and reconnect reconcile the
snapshot. Events are not replayed and every heartbeat is not an event. Visible
pages therefore retain a 15-second fallback poll and focus reconciliation.
No universal instant-delivery or exact 15-second end-to-end latency is claimed.

The page checks its clock every five seconds, and hides a snapshot older than
45 seconds or more than five seconds in the future. The parser rejects source
timestamps after generated_at or more than 15 seconds before it, negative/non-
integer counts, contradictory inventory partitions and altered freshness budgets.
An HTTP failure hides prior numbers; manual/automatic refresh can restore them.
The timer and visibility listener are released on unmount.

## Validation before installation

New API cases cover independent clocks, explicit false, missing/corrupt records,
Redis outage, later-chunk failure, inventory budget, tenant/active scope, retained
handshake boundaries, source timeout, permission split and anonymous requests.
UI cases cover source independence, session boundaries, cancellation, malformed
responses, stale/future timestamps, expiry without a network event, recovery and
event reconciliation. Existing stream and command business logic is unchanged.

Local test libraries differ from production dependency versions. Candidate-image
checks and source CI are separately recorded; one must not stand in for the other.
Generated OpenAPI/catalog use the installed dependency family without starting
application lifespan or contacting production services.

The first live rollout exposed a dependency wiring error: the new route injected
the text Redis client, causing UnicodeDecodeError on real MessagePack records.
The UI correctly displayed unavailable sources. A separate correction injects
the binary client and adds a regression with both clients sharing one Redis
fixture. The initial rollout is not recorded as successful fleet coverage;
only the corrected source and rechecked runtime can supply final evidence.

## Outstanding criteria

- Independent fleet metric producer, coverage numerator/denominator history.
- Actual infrastructure/public transport tunnel probes and fresh timestamps.
- Permission/failure/live producer acceptance on real PostgreSQL/Redis.
- Representative fleet and multi-browser load/soak with bounded source work.
- Full product backlog, Studio, automation replay and mixed stream/script test.
- Windows disk/RAM writer attribution; this feature does not resolve that issue.

No VPN provision/rotation, Android input, script, stream, APK/OTA or transport
replacement is required to read this coverage. A successful finite read is not
continuous uptime, VPN traffic, stream/script health or enterprise readiness.
