# EP-010 Stage B: tenant fleet coverage in the monitoring UI

**Date:** 5 October 2026. **Criterion:** EP-010 remains OPEN.
**Acceptance overlay:** 9 accepted / 41 open; immutable 50-item baseline retained.
**Scope:** read-only tenant inventory/presence/VPN coverage endpoint and presentation.
Installed API source **7fef9c53**, UI source **9ad0a69e**.
UTC observation date is 5 October; local installation date is 6 October
(Asia/Yekaterinburg). [Frozen receipts and screenshots](ENTERPRISE-FLEET-COVERAGE-EVIDENCE.json)
record the actual sources separately; they do not certify continuous health.

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

## Corrected runtime and evidence

The initial source `9ad0a69e729f9b4960bf8aea529a88e25e4f73cf` shipped the UI
and the initial API. Real reads exposed the text/binary dependency mismatch.
Structured logs identified UnicodeDecodeError; this was not a Redis outage.
The separate fix `7fef9c5308e9a4e6b9de435d3ca27064bf3754fb` corrected the API.
No frontend file differs between the two commits. The runtime badge truthfully
displays different API/UI revisions; it is not evidence of a broken API contract.

Corrected API image:
`sha256:f06fcc4e7fb6fa62164dbfd3dd6544093b4a26636fbaa0e8f80b750d27366c99`.
Installed UI image:
`sha256:7558e79768872c13c64d0d9f413d361ca3eb54cbb510d3553c792d621ff7678e`.
Both were built from committed archives. The contexts contain no local credentials
or generated pilot files. API checks run with no network and no backend source
mount: **476 device/status/WebSocket/VPN tests**, **35 resource tests**, mypy over
233 source files, scoped Ruff and generated API catalog check all passed. The
corrected endpoint suite has 32 cases, including the binary dependency regression.

UI source passed **1,298 tests / 121 suites** with no skipped/failed tests. The
Node 24 production build completed with types and lint; existing unrelated lint
warnings are not reported as a warning-free build. Local Windows Python tests
also passed 475 pre-correction regressions (571 old-library warnings) and the
32-case corrected endpoint suite. Candidate-image checks use the shipped dependency
versions; local older-library output is kept distinct.

API initial rollout at 18:55:33 UTC and UI at 18:56:39 UTC each changed one owned
container and preserved 45 neighbors, their mounts, start times, image IDs and log
rotation. The corrected API was installed at **19:00:24 UTC / 00:00:24 UTC+5**.
Rollback images/configurations were retained. UI keeps reserved internal addresses
172.30.0.3 and 172.29.0.3, a read-only filesystem and dropped capabilities.
The first UI preflight expected an OCI revision label that the existing UI container
does not expose. It stopped before mutation; the corrected preflight verified the
actual previous immutable image digest. No user action was required.

The initial UI installation interval showed 12 online / 7 offline both before and
after its replacement. This is preserved as a transient observation, not rewritten
as 14 or attributed to a proven network cause. Corrected API installation showed
14 online / 5 offline both before and after. Restart recovery is not certified by
these short samples.

Six reads at 19:00:24–19:00:39 UTC showed:

- Active tenant SQL inventory: 19.
- Fresh owned Android connections: 14 online; 5 unknown; no explicit cached offline.
- Independently timed Android VPN service reports: 14 inactive, 5 unknown.
- SQL VPN peer catalog and eligible retained handshake denominator: measured zero.
- Public transport: unmeasured, null counts; no provider health is invented.

The existing registry displayed 14 online / 5 offline. Its offline count includes
missing cached presence, whereas the new coverage explicitly distinguishes missing
observations as unknown. Those sources are not contradictory. All six inventory,
online and Android partitions agreed with independently read registry values at
their respective snapshots. Sequential reads can diverge during a real transition.
The probe's coarse Windows monotonic clock returned **0–16 ms** for local round
trips with 19 devices. Zero means below that timer's resolution, not instantaneous
delivery. These values are not a precise latency benchmark, an SLA or a
5,000-device acceptance measurement.

CPU/memory and HTTP panels continued returning their separate measurement states.
Own probe logout returned 204; the revoked coverage read returned 401. The human
browser session remained available. No Android control, stream, script, VPN
provision/revoke/rotation, APK/OTA or public tunnel replacement occurred.

## Actual browser checks

Native captures are viewport screenshots, not mockups or reconstructed pages.
The scope was this new panel and compatibility of the existing monitoring page:

- Desktop 1440×1000: three columns, all six cards read, dark/light themes.
- Mobile 390×844: one column, all six cards stay inside the viewport width.
- Restored default 724×884: no horizontal document or card overflow.
- Manual refresh fetched current source times; the event badge remained connected.
- Browser log query returned zero warning/error entries in its bounded result.
- Original dark theme restored and temporary viewport overrides reset.

[Desktop dark](assets/fleet-coverage/desktop-dark.jpg) ·
[Desktop sources](assets/fleet-coverage/desktop-sources.jpg) ·
[Desktop light](assets/fleet-coverage/desktop-light.jpg) ·
[Mobile light](assets/fleet-coverage/mobile-light.jpg) ·
[Default view](assets/fleet-coverage/default-dark.jpg).

Screenshots show different scroll positions and do not claim the entire page fits
in one viewport. This is not a complete accessibility review, a fleet soak, tunnel
traffic acceptance or verification of all product pages. No deliberate device-state
transition was generated for this browser test; event reconciliation is covered by
the hook regression tests, not claimed as an end-to-end live event-latency result.

## Implementation references

[Tenant endpoint](../../../backend/api/v1/monitoring/router.py) ·
[Bounded source reader](../../../backend/services/fleet_coverage.py) ·
[Response schema](../../../backend/schemas/fleet_coverage.py) ·
[Binary cache projection](../../../backend/services/device_status_cache.py) ·
[Presentation](../../../frontend/src/features/monitoring/FleetCoveragePanel.tsx) ·
[Response/session validation](../../../frontend/src/features/monitoring/fleetCoverageTypes.ts) ·
[API regressions](../../../tests/devices/test_fleet_coverage.py) ·
[UI regressions](../../../frontend/__tests__/monitoring/fleet-coverage-panel.test.tsx) ·
[Fleet event tests](../../../frontend/__tests__/hooks/useFleetEvents.test.tsx).

## Corrected source CI

All completed workflows for API source `7fef9c5308e9a4e6b9de435d3ca27064bf3754fb` passed: backend, frontend,
Android and the existing preview workflow. Backend unit/real-service step:
**2754 passed / 30 skipped / 1 warning**, total coverage
**79.77%**. All 32 coverage endpoint cases passed. Full lint/security/RLS,
production bootstrap, generated API check, Redis memory/persistence and Alembic
gates passed. [Backend run](https://github.com/RootOne1337/sphere-platform/actions/runs/37360072616).

The new permission, timeout and partial-source regressions use SQLite/FakeRedis;
they do not independently prove real-database role/failure behavior. Live reads
used the existing authenticated admin tenant with real PostgreSQL/Redis. Dedicated
non-admin production coverage/failure acceptance remains open. The overall real-
service suite and static RLS checks must not be described as those missing tests.

The documentation follow-up changes neither installed image and has its own CI.
The [artifact checker](../../../scripts/audit/validate_fleet_coverage.py) verifies
these immutable files and Git objects, does not contact production and cannot
certify current uptime or close EP-010. Acceptance remains **9 / 41**.

## Documentation integrity

The entry-point/reference check verified **812 local links**
and **19 Markdown anchors** across 13 documents.
Historical evidence and the acceptance overlay were retained. Run the frozen
artifact check from the repository root with:

```powershell
python -m scripts.audit.validate_fleet_coverage
```

The checker validates receipt hashes, committed source trees, image tests,
source-specific CI, finite live observations and screenshot dimensions. It does
not query current services, re-run CI, diagnose the Windows writer, or advance
an open acceptance criterion. Current operating facts belong in CURRENT-STATE;
the immutable receipt remains tied to API `7fef9c53` and UI `9ad0a69e`.
