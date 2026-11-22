# EP-010 — live coverage and event delivery review

**5 October 2026. Initial source reviewed:** `cb5b3f91640c86622060e6e3adea76c6d73a6093`.
**Current status:** tenant coverage API/UI installed with API `7fef9c53` and
UI `9ad0a69e`. [Corrected runtime and coverage cards](ENTERPRISE-FLEET-COVERAGE.md)
record 476+35 corrected-image tests, 1298 UI tests and actual 19-device reads.
[Stage B clock/ownership foundation](ENTERPRISE-ANDROID-VPN-OBSERVATION.md) and
Stage A/schema receipts remain historical. EP-010 is OPEN: request-time coverage
is not the independent producer or public transport probes. The immutable
[50-item backlog](ENTERPRISE-PRODUCT-BACKLOG.json) is retained.
Current acceptance remains **9 accepted / 41 with open criteria**.
[Installed resource histories](ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md) ·
[Current runtime](../../operations/CURRENT-STATE.md).

## What updates by itself today

The product uses two different delivery mechanisms. A fleet event tells the browser
that authoritative state may have changed. The browser then rereads the relevant
mounted REST queries. Prometheus values are sampled histories; a WebSocket event
does not make a controller reading or a scrape arrive sooner.

| Surface | Current mechanism | Interval / trigger | Boundary |
|---|---|---|---|
| Device presence / tasks | One authenticated fleet WebSocket in the dashboard shell | Relevant events coalesced for 500 ms | Marks related caches stale; only active queries refetch |
| Device registry | REST plus fleet-event reconciliation | 30 s fallback; 15 s staleTime | Reads inventory/presence for the filtered tenant scope |
| Dashboard fleet | REST plus related fleet events | 15 s fallback | Tenant fleet data, not platform-wide Prometheus inventory |
| HTTP and container-resource history | Prometheus scrape plus authorized browser snapshot | 15 s scrape and 15 s visible-page refresh | Values can lag by roughly both intervals plus transport/query time |
| Tenant fleet/VPN coverage | REST plus device/task/VPN events | 15 s visible-page fallback; 45 s UI expiry | Bounded request-time SQL/Redis counts; no independent producer or public tunnel probe |
| Infrastructure health / current counters | REST probes | 10 s | Probe availability is separate from data-plane health |
| VPN peers / health | REST plus VPN events | 30 s fallback | Assignment, Android application and handshake are distinct facts |
| VPN pool summary | REST plus VPN events | 60 s fallback | Retained-handshake expiry corrected in Stage A; router and Android coverage still incomplete |
| Device events / aggregate event stats | REST plus fleet events | 15 s / 60 s | Journal reads are separate from the transient notification channel |

Sources: [fleet hook](../../../frontend/lib/hooks/useFleetEvents.ts),
[dashboard shell](../../../frontend/app/(dashboard)/layout.tsx),
[device queries](../../../frontend/lib/hooks/useDevices.ts),
[shared intervals](../../../frontend/lib/queryPollIntervals.ts),
[monitoring page](../../../frontend/app/(dashboard)/monitoring/page.tsx),
[VPN queries](../../../frontend/lib/hooks/useVpn.ts),
[event queries](../../../frontend/lib/hooks/useDeviceEvents.ts).

The current event hook has one bounded set of query roots, not an event queue that
grows with every notification. A burst of progress events coalesces per root;
in-flight reads are not repeatedly cancelled. Inactive cached pages become stale
without starting a read for every hidden page. Hidden-tab invalidations are deferred;
on return, authoritative data is reconciled. Normal query interval work is not
configured to run in the background.

Socket TCP-open alone is not marked live. A server snapshot/pong confirms the
authenticated feed. Handshake timeout is 15 s; heartbeat is 20 s with a 10 s
response timeout. Reconnection backs off with jitter to a 30 s maximum. An auth
rejection does not retry until the token changes. Session query clients are retired
when user, organization, role or session version changes.

The existing [event-hook tests](../../../frontend/__tests__/hooks/useFleetEvents.test.tsx)
exercise coalescing, initial/reconnected reconciliation, watchdog recovery,
background deferral and cleanup. They are included in the previously recorded
1275-test historical source run and the new 1298-test UI run; no end-to-end replay or latency SLA is claimed here.

## Source-proven gaps

### C1 — fleet Prometheus gauges have no producer

[backend/metrics.py](../../../backend/metrics.py) declares
`sphere_devices_total{org_id}` and `sphere_devices_online{org_id}` with `livemax`.
A repository-wide search for the names finds only those declarations, with no
`labels(...).set(...)` producer. This explains the empty metric vectors recorded
in the original backlog. Choosing `livemax` alone does not create a measurement
or keep an observation fresh.

The [device-list route](../../../backend/api/v1/devices/router.py) already provides
tenant-filtered `scope_total`, status counts, `presence_available` and `as_of`.
It uses a small SQL inventory projection and one Redis MGET for the selected scope.
It does not load all ORM device relationships to count the fleet, but the count
work is still O(N) in that scope. Redis read failure reports unknown presence;
an old database status does not become proof of current online state.

This is a usable REST source. It is not yet an independent bounded Prometheus
producer. Updating process-local gauges only when a browser opens the page would
make platform coverage depend on operator activity and leave stale values behind.

### C2 — the infrastructure tunnel field is explicitly unmeasured

[monitoring/router.py](../../../backend/api/v1/monitoring/router.py) returns
`network.activeTunnels = None`. The UI correctly shows a coverage gap. Substituting
the number of assigned peers would conceal the missing signal rather than fix it.
The infrastructure network counters cover backend interfaces; they do not prove
an Android VPN, public tunnel or route is active.

### C3 — pool active count lacked timestamp expiry (corrected in Stage A)

The paragraphs below retain the initial defect rationale. The current count
requires assigned/bound/recent evidence, as recorded in
[Stage A and subsequent foundation](ENTERPRISE-ANDROID-VPN-OBSERVATION.md).

At the initially reviewed source, [vpn/router.py](../../../backend/api/v1/vpn/router.py), `pool_stats`, counted
`VPNPeer.is_active == True` within the organization. Its active-count query does
not also require ASSIGNED state, a bound device or a sufficiently recent handshake.
The [public schema](../../../backend/schemas/vpn/peer.py) describes this value as
handshakes younger than three minutes. The query therefore does not enforce the
documented freshness condition.

[VPNHealthMonitor](../../../backend/services/vpn/health_monitor.py) deliberately
preserves prior state when the router observation is unavailable or malformed.
That preservation protects ownership; it also means an `is_active=True` flag can
outlive the observation that justified it. This is a source-proven expiry gap,
not a claim that current production peers are actually miscounted. A clock-boundary
SQL reproduction and the corrected count must precede runtime acceptance.

### C4 — Android applied state had no independent observation timestamp (Stage B foundation)

At the initially reviewed source, [DeviceLiveStatus](../../../backend/schemas/device_status.py) carried nullable
`vpn_active` and `last_heartbeat`. [HeartbeatManager](../../../backend/websocket/heartbeat.py)
updated the VPN field only when it was present in a pong. A later pong could refresh
the heartbeat without supplying a new VPN observation. Consequently a fresh
heartbeat did not, by itself, prove a fresh VPN-applied observation.

The [Stage B foundation](ENTERPRISE-ANDROID-VPN-OBSERVATION.md) adds independent
server receipt time, current-session ownership and read-time expiry. Its source
checks and runtime acceptance are recorded separately; broader coverage remains
open. The following paragraph describes the initially reviewed gap.

[handle_telemetry](../../../backend/api/ws/android/router.py) can also update
`vpn_active`; it does not establish a separate VPN observation epoch. The next
contract needs an independent VPN-observed timestamp, current-session ownership
and an explicit unknown state for old APKs. It must not assign the time of an
unrelated heartbeat to a retained VPN flag.

## Required semantics before implementation acceptance

1. **Inventory:** active registered devices in an explicitly named tenant/filter
   scope; counted SQL source and collection time.
2. **Presence:** current Redis observation, online and busy separately, connecting,
   offline, issues and unknown coverage. Failed reads cannot become zero online.
3. **VPN assignment:** ASSIGNED, PROVISIONING, REVOKING, FREE and ERROR SQL states
   counted separately; holding an address is not applied Android connectivity.
4. **Android applied:** current-session, independently timestamped observation;
   true, false and unknown are separate. Expired or absent reports stay unknown.
5. **Handshake:** latest validated router observation and handshake age; no/future/
   expired timestamp is distinct from a recent handshake. Router read failure is
   explicit and must not authorize destructive reconciliation.
6. **Transport tunnels:** Cloudflare/Tuna availability, Android VPN state and
   WebSocket presence have different owners and must not share one ambiguous count.
7. **Producer ownership:** one authoritative snapshot, never the sum of duplicate
   whole-fleet gauges from each API worker. Worker replacement and failed updates
   must not retain an accepted-looking old snapshot without freshness metadata.
8. **Access:** tenant REST counts require current tenant authorization; platform
   metrics require their existing administrative scope. No user-selected arbitrary
   PromQL, controller path or upstream URL. Labels must remain bounded.
9. **Delivery:** tenant changes invalidate only relevant query roots. Recovery
   rereads state because current Redis PubSub has no replay cursor. A notification
   is a hint to reread; it is not a transaction receipt or guaranteed durable log.
10. **Load:** the producer must run without an open browser, have a bounded timeout,
    no unbounded SCAN/ORM serialization and no new per-event disk history. A shared
    service-side sampler is preferable to repeating a whole-fleet read per viewer;
    its exact ownership/storage budget requires verification before selection.

## Staged implementation and evidence

The sequence below is the original plan, not a list of entirely unstarted work.
Stage A and the Stage B clock/ownership foundation are installed. The new
[tenant contract, UI and corrected runtime](ENTERPRISE-FLEET-COVERAGE.md) implement
the request-time portion of B/D and freeze its bounded evidence. Stage C, actual
transport probes, dedicated production-role/failure and load acceptance remain
open; this partial implementation does not close the whole EP-010 criterion.

**Stage A:** reproduce the stale pool count using isolated SQL with fixed time,
two organizations and fresh/stale/absent/future timestamps. Correct its advertised
read semantics without assigning, revoking or reconnecting a VPN.

**Stage B:** add the tenant coverage contract with separate assignment / Android /
handshake counts and source availability/time. Verify empty inventory and genuine
zero, old APKs, malformed Redis entries, cross-tenant rows, partial source failures,
current-session replacement and time-boundary behavior.

**Stage C:** design and test the authoritative fleet metric producer, including
multi-worker startup, retirement and source outage. Decide bounded cardinality and
collector ownership from real inventory size. Do not simply populate the legacy
gauges inside a page request.

**Stage D:** add the monitoring coverage UI with source/unit/scope/timestamps,
drilldowns and unknown states. Test visible-page refresh, session changes and
recovery. Review real wide/mobile layouts in both themes.

**Stage E:** freeze source, production image and collection configuration, run
appropriate checks, install with rollback, compare independent source values and
record real browser behavior. Retain failures and transient fleet observations.
Only then update the acceptance overlay; the original audit remains immutable.

This review does not replace event transport, provision VPN protocols, change an
APK, run scripts on devices or claim the 20–30-device mixed-load gate. Windows
disk/RAM writer attribution remains open. The next package must preserve existing
resource-history and HTTP metrics and avoid expanding unrelated telemetry claims.

## Stage A implementation — 5 October 2026

The isolated SQL reproduction contains 13 cases: age 0, 179, exactly 180 and 600
seconds; no timestamp; a future timestamp; a false retained flag; FREE, PROVISIONING,
REVOKING and ERROR states; an unbound assignment; and another organization's peer.
Before the fix **9 failed / 4 passed**, with no collection/setup errors.

The pool active count now requires an organization-owned ASSIGNED peer bound to a
device, `is_active=True` and a recorded handshake in `(now - 180 seconds, now]`.
The stale count uses `<= now - 180 seconds` for bound ASSIGNED peers; absent/future
handshakes do not become recent observations. The peer-list active flag uses the
same conditions. SQL allocation/capacity semantics and all VPN commands remain
unchanged. The pool response adds UTC `observed_at` and the exact handshake-age
threshold without removing existing fields. Allocation / active / stale tenant
counts are collected in one SQL statement, preventing three separate database
snapshots and reducing repeated query work. Global subnet capacity remains a
separate observation and is not relabeled tenant capacity.

After the fix the 13 regression cases and related API/health tests passed:
**42 passed / 0 failed / 0 skipped**. The full local VPN suite then passed
**99 / 0 failed / 0 skipped**. These runs use the canonical SQLite in-memory
adapter and FakeRedis; they are not proof of PostgreSQL RLS, router availability
or an Android-applied tunnel. No router request or Android command is sent by the
new cases. The [regression tests](../../../tests/vpn/test_pool_observation_freshness.py)
also compare the peer list and aggregate result rather than accepting contradictory
active labels.

Source implementation is a partial EP-010 slice. Runtime installation and image
checks must be recorded separately; the currently accepted EP-009 runtime does
not acquire this change merely because the working source was edited. C1, C2,
C4, the independent producer and end-to-end coverage acceptance remain open.

## Stage A runtime receipt

API source **`66714f26a657e3600d10ee87bafa8ab3ed769294`** was installed at
15:26:41 UTC. Image **`sha256:c8b1ffab5837f127772564f0a90e6b58e730b2e3dbc90ec3945fd3673801e40e`**
was built from committed Git archive. Exact-image checks passed: 99 VPN tests,
27 resource/multiprocess tests, mypy 231 files and Ruff. Containers used network
none and no application-source mounts; VPN tests remain SQLite/FakeRedis tests.

Only the backend container was replaced. All 45 neighbors, their start epochs,
mounts and log rotation settings were preserved. The UI source remains
`cb5b3f91640c86622060e6e3adea76c6d73a6093`; its different revision is intentionally
visible in the build badge. Prometheus, Grafana, APK/OTA, databases and tunnels
were not replaced. The API response change is additive for this installed UI.

Actual PostgreSQL-backed tenant reads returned an empty peer catalog and zero
assignment/active/stale counts with a valid UTC observation and threshold 180.
Peer flags and aggregate count agreed. This validates the deployed read path for
empty inventory; it does not demonstrate production stale peers, PostgreSQL RLS
or an operational Android VPN. No router read or device command was sent.

The before/after rollout samples were 14 online / 5 offline of 19. A later finite
six-sample window, three seconds apart, retained the same counts. Connection
epochs and uninterrupted uptime were not measured. HTTP/resource panels remained
available in API checks and the actual browser; the existing absent-quota state
remained unknown. Own-session logout returned 204 and a subsequent resource read
returned 401. The operator's browser session was preserved.

[Portable partial evidence](ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json) ·
[Actual empty VPN catalog](assets/live-coverage/vpn-empty-live.jpg) ·
[Resource panels after API replacement](assets/live-coverage/resources-after-api.jpg).

EP-010 remains OPEN and the acceptance overlay remains 9/41. Its remaining
producer/freshness semantics are listed above; the staged implementation is not
a declaration of platform readiness or a new VPN protocol release.

## Source CI and documentation repair

At source `66714f26`, the backend unit/real-service test step passed **2685 tests,
30 skipped**, with **79.70% coverage**. Production-image bootstrap, four-worker
replacement, PostgreSQL restart, lint, security and RLS policy checks also passed.
The workflow subsequently failed `scripts.export_api_docs --check`: the new
additive VPN response fields were missing from the committed OpenAPI. Redis
memory acceptance and the downstream Alembic job were skipped after that failure;
this workflow is not recorded as successful.

Documentation-only commit `ffdcd36` regenerates the two output documents from
the actual installed production image. Only `docs/openapi.json` changes; the HTTP
endpoint catalog remains identical. The exact-image exporter check now passes
without network, lifespan startup or backend source mounts, with its shipped
FastAPI 0.136.3 / Pydantic 2.9.2. The public
[export receipt](evidence/live-coverage/api-schema-export.json) records that
dependency boundary. The subsequent full CI run must finish independently;
neither this repair nor artifact verification proves all checks are green.

Recheck the frozen artifact set with
`python -m scripts.audit.validate_live_coverage` using the
[integrity checker](../../../scripts/audit/validate_live_coverage.py).
It checks source/image associations, test XML, rollout receipts, screenshot
hashes and the unchanged 9/41 ledger. It does not contact the running API,
rerun tests, certify ongoing health or close EP-010.
