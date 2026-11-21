# Browser and APK direct transport: deferred research brief

9 October 2026, Asia/Yekaterinburg. User idea recorded; research and implementation
explicitly deferred. No new transport, library, port, credential or VPN configured.

Desired experience: authenticate in the browser, download the latest compatible
APK, install it on two to four local emulators, discover authorized devices and
operate them from the existing Studio. Scripts execute on Android. The server
remains the authority for identity, organization, authorization and coordination;
the media path should be direct when the network and browser support it.

This document is an investigation backlog, not an evaluated recommendation.
Pion WebRTC, browser WebRTC, overlays and tunnel tools mentioned by the user are
candidates to investigate against current primary documentation. No current
version or comparative performance claim has been verified here.

## Questions for the later investigation

1. Browser/Android transport capabilities and codec/device compatibility; actual
   capture and encoder limits must be separated from network limits.
2. Localhost, separate LAN hosts, WAN, NAT, restricted networks and relay fallback.
   Direct connectivity must be measured, not inferred from physical distance.
3. Signaling authorization, short-lived scoped device/viewer grants, revocation,
   tenant separation, native control ownership and task/control conflict handling.
4. Video quality, bandwidth adaptation, input/ACK path, frame timestamps and
   input-to-picture measurements. “Direct” does not imply zero latency.
5. Browser deployment constraints, secure contexts, origin policy, discovery,
   background tabs, suspended laptops, reconnect and transport change without
   replaying unknown Android commands.
6. Relay sizing, availability, observability, retention and predictable VPS costs;
   direct/relayed path must be explicit in the UI and telemetry.
7. Existing Android APK capture pipeline, server contracts and Studio integration;
   incremental migration and a reversible fallback must preserve current tasks.
8. Operator installation instructions, package provenance, upgrade compatibility,
   fleet policy, health diagnostics and a deployment/rollback acceptance matrix.

## Gate before implementation

Prepare a separate research report with current primary-source links, licensing,
compatibility, threat boundaries, measured prototype results, costs and an ADR.
Compare localhost/LAN/WAN/restricted paths under disconnect, rotation and load.
Only then choose a transport and prepare the implementation plan. Current
development continues on the audited Studio and control reliability backlog.

[Current installed scope](../../operations/CURRENT-STATE.md) ·
[Existing viewer reliability evidence](../2026-10-08/CONTINUOUS-VIEWER-FAULT-ISOLATION.md).
