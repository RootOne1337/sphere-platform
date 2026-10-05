# EP-009 — backend container CPU and memory history

Date: **5 October 2026**. Implementation and acceptance are separate stages.
Status of this first source change: **IMPLEMENTED / LIVE ACCEPTANCE PENDING**.
The immutable [50-item product backlog](ENTERPRISE-PRODUCT-BACKLOG.json) is preserved.
EP-009 requires a named source/unit/interval, distinct process/cgroup/host scopes,
and missing CPU/memory represented as missing measurements.

## Observed gap and source selection

The reviewed REST endpoint returns `history=[]`. The running four-worker API uses
Prometheus multiprocess exposition; its fresh worker registry does not expose
default process CPU/RSS as a usable container history. On the actual Docker host,
the bounded preflight observed cgroup **v1** controllers: memory usage
565,608,448 bytes, memory limit 2,147,483,648 bytes, CPU cumulative
1,171,288,093,800 nanoseconds, and quota `-1` / period 100000 (unlimited quota).
This was a point-in-time source probe, not an accepted history or leak diagnosis.

The new producer reads its own cgroup namespace **once per `/metrics` scrape**.
It appends a separate short-lived collector registry to the unchanged existing
worker exposition. It does not register resource gauges in each worker's mmap
directory: summing four identical container readings would multiply the resource
usage by four. It creates no background thread/task, polling cache or disk file.
Existing HTTP worker aggregation and worker-retirement behavior remain tested.

Sources:

- [Producer](../../../backend/monitoring/container_resources.py).
- [Separate resource exposition](../../../backend/monitoring/resource_exposition.py).
- [API integration](../../../backend/main.py).
- [Prometheus allowlist](../../../infrastructure/monitoring/collection/prometheus.yml).
- [Bounded server query](../../../frontend/lib/server/resourceObservability.ts).
- [Live UI](../../../frontend/src/features/monitoring/ResourceMetricsPanel.tsx).
- [Snapshot contract](../../../frontend/src/features/monitoring/resourceMetricsTypes.ts).

## Units and boundaries

| Signal | Controller | Exposition | Display |
|---|---|---|---|
| CPU accumulated time | v1 `cpuacct.usage` ns; v2 `cpu.stat usage_usec` µs | `sphere_container_cpu_usage_seconds_total` | `rate(...[1m])` used cores; 1 means one fully used core |
| CPU quota | v1 quota/period; v2 `cpu.max` | `sphere_container_cpu_quota_cores` | Cores; no percentage denominator is invented |
| Charged memory | v1 `memory.usage_in_bytes`; v2 `memory.current` | `sphere_container_memory_usage_bytes` | GiB, dividing bytes by 1,073,741,824 |
| Memory limit | v1 `memory.limit_in_bytes`; v2 `memory.max` | `sphere_container_memory_limit_bytes` | GiB, omitted when unbounded or unavailable |
| Per-source availability | Successful finite controller read | `sphere_container_resource_available` | 1 valid / 0 unmeasured; this is not application health |
| Per-source read time | Time of successful controller read | `sphere_container_resource_read_timestamp_seconds` | Freshness guard; absent on failed reads |

Container charged memory includes cache; it is **not** RSS and **not** Windows
physical RAM/commit. CPU covers all processes inside the backend container, not
just the request worker. Windows host consumption, other containers, emulator
memory and per-worker RSS remain outside this panel. Availability alone does not
prove that memory has stopped growing or that a leak has been fixed.

The source selection follows the observed namespace. Missing/malformed v2 data
does not silently fall back to v1 values. Unreadable namespace detection produces
explicit `cgroup="unknown"` unavailable signals. No PID, container ID, device ID
or arbitrary controller path is added as a label. There are at most **12 samples**
per scrape and four fixed resource names. Controller reads are capped at 4096
ASCII characters each; numbers are bounded unsigned 64-bit values. A failed read
omits the value and timestamp, publishes availability zero, and does not retain a
previous value in producer memory. A valid measured zero remains a real zero.

## Collection, query and UI behavior

Prometheus job `sphere-backend` collects every **15 seconds**, timeout five
seconds, using the existing target. The existing retention/storage budget is
unchanged. No additional monitoring stack, exporter or port is installed.

The server exposes `/api/observability/resources`. Authorization is rechecked
against the live API before metrics are fetched; only `super_admin` can obtain
these platform-wide resources. URL parameters accept one `window` value: `1h`,
`6h`, or `24h`. Browser input never supplies PromQL, instance, labels or upstream
URL. Four fixed resource queries and one target-discovery request are concurrent,
bounded by the shared five-second request / 2 MB JSON limits. Each history has at
most one aggregate series and **1441 ordered nonnegative points**; unexpected
labels, timestamps, cardinality, nonfinite values or annotations fail closed.

CPU `rate` precedes aggregation and therefore follows Prometheus counter reset
handling. Resource values are masked by per-resource availability and read age
(-5 to 45 seconds). A stale controller value cannot survive Prometheus lookback
as a current resource reading. Every historical point also requires exactly one
backend target; discovery of multiple targets hides the panel rather than merging
different containers into one claim. Multi-target comparison is a future feature.

Steps are **15 / 30 / 60 seconds** for 1 / 6 / 24 hours. CPU averaging is one
minute; memory and quota are sampled gauges. No pre-deployment history is backfilled
or inferred. Missing points stay gaps in the chart. States `ready`, `empty`,
`partial`, `error`, and `stale` are separate. A quota with no finite value is
unmeasured: the UI does not guess whether the controller is absent or unlimited.

The open visible page requests a new snapshot every **15 seconds**. It cancels
requests on query disposal, stops polling in the background and refreshes when
focused. Query keys include user ID, session version and history window. Errors
or expired snapshot/scrape timestamps hide cached measurements; recovery can be
automatic or requested manually. The page is sampled monitoring, not instantaneous
push delivery. Depending on scrape and request phases, a new resource change can
take roughly two intervals to become visible, plus query/transport time.

Current REST health/probe coverage remains separate. Empty legacy REST history
arrays no longer generate a misleading whole-page CPU/RAM-history warning:
the Prometheus resource panel owns its actual history state. Missing current REST
probes (including active tunnels) remain explicitly unknown. The UI never promotes
missing host/RSS measurements or available `/metrics` to global platform health.

## Verification and acceptance

Source checks cover v1/v2 units and quotas, genuine zero, absent/unlimited limits,
malformed/oversized values, controller permission failure, registration without
reads and real four-worker exposition through retirement/replacement. Frontend
checks cover live authorization, fixed windows/query inputs, discovery ambiguity,
partial response isolation, invalid histories, gaps, stale snapshot/scrape times,
zero versus unknown, refresh after error and readable scope/units.

Live acceptance must still record exact immutable API/UI images, unchanged
neighbors and mounts/log budgets, validated Prometheus configuration, real query
values/units and actual browser wide/mobile screenshots. The first source commit
does **not** close EP-009. Passing mocked queries is insufficient to demonstrate
valid PromQL or actual controller scope; real Prometheus/controller checks are
required. Historical failures remain alongside a later successful acceptance.

## References and upstream behavior

The [Prometheus Python multiprocess documentation](https://prometheus.github.io/client_python/multiprocess/)
describes fresh multiprocess registry handling and its collector restrictions.
This change preserves that worker registry and appends a separate scrape-time
resource registry.

The [Linux cgroup v2 reference](https://docs.kernel.org/admin-guide/cgroup-v2.html)
defines `cpu.stat`, `cpu.max`, `memory.current` and `memory.max`.
The [cgroup v1 CPU accounting reference](https://docs.kernel.org/admin-guide/cgroup-v1/cpuacct.html)
defines cumulative `cpuacct.usage` nanoseconds. The
[v1 memory reference](https://docs.kernel.org/admin-guide/cgroup-v1/memory.html)
is historical documentation; runtime controller values and Docker limits were
checked directly for this host. No third-party implementation was copied or
vendored and no new dependency was added.
