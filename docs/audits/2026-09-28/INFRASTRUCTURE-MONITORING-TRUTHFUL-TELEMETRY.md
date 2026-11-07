# Infrastructure Monitoring: truthful telemetry correction

**Date:** 28 September 2026
**Scope:** backend `/api/v1/monitoring/{metrics,nodes}` and the Infrastructure Monitoring page
**Fleet baseline:** the operator-designated 14 devices with fresh, stable online sessions are the comparison baseline. This source change does not alter those devices, routes, APKs, or server state.

## Finding

The Infrastructure Monitoring page could report a healthy system while losing the data needed to diagnose an outage:

1. `GET /monitoring/metrics` generated random CPU/RAM sparkline values around one current sample. These were not historical observations.
2. Linux load average was normalized and presented as a CPU percentage; a read failure returned `0`, which looked like a healthy idle host.
3. RAM came from host `/proc/meminfo` even when the app ran in a memory-limited container; read failures again became zero.
4. `/proc/net/dev` counters are cumulative bytes, but the UI called them bandwidth. The API returned `activeTunnels: 0` without a tunnel exporter.
5. `/monitoring/nodes` marked PostgreSQL, Task Worker, and Nginx healthy without probing them and supplied fixed CPU/RAM values. Its database check was a `pass` placeholder.
6. The page caught failed requests and substituted zero metrics and an empty node list, then rendered `ALL SYSTEMS NOMINAL`. It also compared lowercase statuses although the API emitted uppercase values, so a real `CRITICAL` could be missed.

These are source-level findings in the branch, not a claim that the live service currently has an outage. False telemetry is nevertheless a production issue: it can hide one.

## Source correction

- Health status now comes from the existing bounded `HealthService.check_all()` probes for PostgreSQL, Redis, and disk. The API responder is healthy only because it served the request; that does not imply all Gunicorn workers are reachable. Unprobed worker and edge services are omitted instead of being invented as healthy.
- Node resource fields are `null` when no measurement exists; actual probe status, latency, and probe details are carried through.
- The CPU field is named `linuxLoad1mPerCpu` and described as Linux 1-minute host load average per system-reported logical CPU. It is not CPU utilization or cgroup quota-aware container usage. A failed read returns `null`, and values are not clamped to 100.
- RAM uses cgroup usage and limit counters (v2 and v1). If the container has no limit or cgroup data is unavailable, the known usage may be shown with an unknown limit, or both values remain unavailable. Host memory is not presented as container memory.
- Network values are cumulative transmitted/received bytes summed across non-loopback interfaces. They are not a rate. A rate needs two samples and elapsed time.
- There is no generated history. `history` is empty until a real time-series source is wired in. `activeTunnels`, Redis operations/sec, and unavailable Redis details remain `null`/unavailable until measured.
- The frontend no longer substitutes a healthy-looking payload after a request failure. It handles uppercase critical/warning states, shows errors and empty results as unknown, and only calls the returned probe set healthy when every returned check is healthy.

## Regression evidence

New backend tests verify that dependency failures are reflected in the topology, CPU/RAM are not fabricated, cumulative counters exclude loopback and add interfaces, cgroup-unlimited memory is represented without a fake limit, and missing probe states map to `UNKNOWN`. New frontend tests verify uppercase `CRITICAL` and `WARNING`, unavailable telemetry, and that monitoring API failures cannot render healthy/zero defaults.

Commands run for this change:

```powershell
$env:JWT_SECRET_KEY='unit-test-only-key-012345678901234567890123456789'
python -m pytest tests/test_monitoring -q
python -m ruff check backend/api/v1/monitoring/router.py tests/test_monitoring/test_dashboard_telemetry.py
cd frontend
npm test -- --runInBand
npm run type-check
npm run build
```

Backend result: **52 passed**. The full frontend suite: **41 suites / 306 tests passed**. The focused Monitoring UI suite: **7 tests passed**. Ruff and the frontend type check passed. Next.js production build exits 0 and includes `/monitoring`, but on this Windows host it emits a standalone file-tracing warning for a missing route-group client-reference manifest; this is tracked as a local packaging caveat, not represented as a clean build. CI on the PR is still required.

## Operational boundary and follow-up

This patch changes source only. It does not deploy the backend/frontend, publish an APK, change the signed discovery document, update OTA, change a tunnel route, or command any Android device. The 14-device online baseline is a comparison point, not new live evidence produced by these source tests. This page's health probes also do not prove Android heartbeat, remote video receipt, browser decode, or stream freshness.

Before deployment, run backend and frontend CI. After a paired rollout, compare the live Monitoring page against `/api/v1/health/full`, and verify that a forced monitoring API failure renders unavailable/critical rather than green. Prometheus-backed history, cgroup quota-aware CPU utilization, network-rate sampling, and a real active-tunnel exporter remain follow-up work. Keep the Android fleet and ingress unchanged until these checks are separately authorized and measured.
