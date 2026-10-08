# Continuous input: isolate a disconnected viewer / P1 follow-up

8 October 2026. Source correction; reviewed API installation and live acceptance
are still required at this checkpoint. SF26-05 remains OPEN; ledger9accepted/41open.

## Reproduced source defect

At 18:10–18:18 UTC the installed UI36b160f9 displayed video on PH011, but Control
reported that the server had not confirmed continuous gestures. The diagnostic
state was idle, with zero decode/render errors. This is a live failure observation;
the exception which originally disabled that worker was not captured.

Baseline API9610523 has a separate, reproducible failure path:
[ContinuousRuntime.send](../../../backend/websocket/continuous_runtime.py) can raise
when a viewer socket closes or times out. Its shared pubsub listener treats that
socket exception as a runtime failure, disables itself and retires other viewers.
Later probes fail until the worker is replaced. A single viewer must not disable
continuous control for unrelated viewers. This source finding does not establish
that it caused the earlier browser idle receipt timeout.

## Correction and boundaries

A failed send unregisters only the exact viewer and performs its existing bounded
native close. A dedicated ViewerTransportUnavailable exception lets the shared
listener continue. Session-binding delivery failure propagates out of touch_open:
native OPEN must never follow an undelivered binding. A viewer displaced during
lease acquisition also cannot open native input or unregister its replacement.

No command, send, gesture or lease acquisition is retried. Redis/shared subscription
failure still fences the runtime; cancellation still propagates. Existing native
watchdog, receipt deadlines, TTLs, tenant checks and input limits are unchanged.
No per-MOVE logs, tokens, raw frames or native owner identifiers are added.

## Regression evidence

[Runtime tests](../../../tests/test_ws/test_continuous_runtime.py) use two workers,
fakeredis pubsub/Lua, independent viewer sockets and mocked Android transport.

| Boundary | Result |
| --- | --- |
| Closed socket, OS disconnect and send timeout on capability offer | Other viewer continues receiving capabilities |
| Closed viewer during heartbeat/release receipt | Only its owner retired; no input replay |
| Failed session binding | No native OPEN |
| Viewer replaced during acquire | Replacement preserved; no native OPEN |
| Cancelled send | CancelledError preserved |
| Shared Redis outage | Runtime fenced; no gesture replay |

Valid baseline:6failed/19passed. Corrected runtime suite:27passed. Related continuous
WebSocket tests:158passed/286deselected. Ruff and mypy passed; git diff check passed.
Two existing deprecation warnings remain. These are deterministic transport
fixtures, not Android performance or indefinite runtime availability evidence.

The first local attempt lacked fakeredis Lua support and is invalid app evidence.
Lupa2.8 was installed only in a private test directory; production requirements,
schema and image dependencies were not modified.

## Installed UI checkpoint before API replacement

UI36b160f925e3f1d073620281bbf6e584636ada14 was installed at18:08:51 UTC from
reviewed CI37751101877. Loaded image:
sha256:bf7ff7556bc834e3bca6b1e43d2baa608ea97bd67ba1f421eeed1f7ba9165a05.
Independent CI config digest:
sha256:1ac38dcbf8812082153a763233c2d45ae138c489814316c1602377404e8d6d63.
API9610523, APK10249, schema and OTA remained unchanged;45 other containers
were preserved. Source CI:frontend1892passed/138suites; backend3337passed,
37skipped/229subtests; Android and preview successful. Full backend coverage80.70%.

Real saved-v1 start/sleep2000/end task b50dd03f-db64-47ad-8001-af461e852653
completed with three APK reports. View remained selected; queue0, graph3/2.
No Android touch, navigation, private text or screenshot capture was requested.
The ordinary token refresh has not yet been observed in this installed browser.

![Installed UI and completed graph before API update](assets/viewer-isolation/task-before-api.png)

## Acceptance still required

Install the exact-source successful reviewed API image, preserve other containers,
schema and OTA, then verify ordinary Control returns READY, reconnect and a finite
gesture. Restart recovery alone does not prove the old exception's cause. Keep
browser timer/native ACK attribution, global task/control ownership, durable
unknown-POST reconciliation and fleet/remote fault soak OPEN.

[Historical idle failure](STUDIO-IDLE-RECEIPT-FOLLOWUP.md) ·
[Same-session state fix](STUDIO-SESSION-REFRESH-STATE.md).
