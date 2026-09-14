# AUD-122 · a live but unhealthy tunnel left every APK offline

**14 September 2026 · High · observed operational incident.**

## Evidence and cause

The local API returned 200 while the public HTTPS ingress returned 530 and later
failed DNS resolution. The scoped `sphere-pilot-20260911/cloudflare-quick`
container stayed running/unhealthy. Its logs repeatedly reported
`Unauthorized: Tunnel not found`; the publisher reported only
`Scoped connector is not healthy`. Last publisher success preceded the observed
incident by over 30 minutes. No automatic connector repair occurred.

Docker `unless-stopped` acts on process/container exits, not a running process
whose healthcheck fails. The old publisher deliberately only observed this state.
APK retries cannot recreate a tunnel that the provider no longer recognizes.
[Docker restart policy semantics](https://docs.docker.com/engine/containers/start-containers-automatically/).

At 14:36:32 UTC a single scoped manual restart restored the connector. The existing
scheduled publisher then advertised signed discovery v10. Both APKs independently
saved the new candidates around 14:40:05 UTC and passed authenticated server shell
echo checks by 14:40:41. PIDs stayed 31803/386; no app restart, reinstall or manual
route injection occurred. Every other container retained its identity, image and
start time. This validates APK recovery after a route replacement, **with manual
connector repair in this first observation**, not full unattended recovery.

## Fix

`scripts/discovery_publisher.py` supports explicit
`"recover_unhealthy_connector": true` for `cloudflare-quick` only.
Before publication it checks exactly one running, unpaused container with the
configured project/service labels. Persistent unhealthy for another 180 seconds
after first observation permits a restart of that exact container ID. Fresh
identity/health is checked again immediately before mutation.

The recovery journal survives minute-by-minute `--once` processes. Restart intent
is saved first; timeout/uncertain outcome still observes cooldown. Continued
failure backs off 5/10/20/40/60 minutes, capped at one hour. A successful healthy
observation resets the failure sequence. Starting, paused, stopped, ambiguous or
foreign containers are never restarted. A backend/PostgreSQL/Redis API failure
does not trigger connector repair while connector health remains healthy.

Publishing still requires verified installation identity and readiness. It does
not publish an unhealthy route, reuse a signed version for different content,
restart backend, alter VPN or touch other installations. Existing process lock
serializes publishers and recovery. Recovery is disabled unless explicitly set.

## Validation and residual risk

42 publisher/recovery tests pass, including persistence across one-shot runs,
grace period, cooldown, transient recovery, scope checks, disk failure, uncertain
CLI result and connector replacement before restart. Ruff passes. Native automatic
repair and separate client/server network fault scenarios are subsequent checks;
they must be recorded independently of the manual incident repair above.

The healthcheck itself already has its own detection delay; this fix adds a
three-minute grace and up to one scheduler interval. GitHub CDN/polling then adds
minutes on a changed address. This is eventual recovery, not a zero-downtime path.
Host scheduler requires the configured logged-in Windows user and Docker Desktop.
No independent second ingress is provided; a provider-wide outage remains a
shared dependency. Quick Tunnels are a development facility, not an availability
commitment: [Cloudflare documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

The browser's old public origin cannot discover a new origin by itself. The local
web remains on port 18080. Stable external web addressing and a second independent
APK route remain prerequisites for the desired deployment topology.
