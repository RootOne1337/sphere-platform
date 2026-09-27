# Tuna remote stream canary

**Date:** 27 September 2026
**Scope:** one remote Android canary, one backend, three viewer ingress paths
**Result:** The sampled remote H.264 packets traversed Tuna, Cloudflare, and the local viewer route. Both production TypeScript H.264 decoders rendered the captured sample in Chrome's secure context. This proves delivery and decoding for this short canary sample; it does not establish sustained frame rate, live-page behavior, durable tunnel availability, active management-route selection, or a fleet-wide fix.

The frontend candidate was subsequently rebuilt and deployed to the isolated `sphere-pilot-20260911` frontend service only. The backend and Android agents were not restarted. The updated `/devices` and `/stream/auto-ph-011` pages both returned HTTP 200 through Tuna and the existing Cloudflare ingress; their delivered JavaScript contained the new Fleet Matrix and stale-frame status markers. The backend remained healthy on its previous pilot image, so `connected_since` session duration is not yet available in the live UI.

## What was tested

The agent `auto-ph-011` was online on APK `1.2.32-dev`. Its management route was changed on that device only. The primary was a Tuna HTTP tunnel to the current pilot gateway; Cloudflare remained the fallback. The latest route intent and command receipt are retained only in ignored `.local-pilot` evidence. No token, dynamic host name, or raw device log is part of this document.

A 30-second three-way viewer probe opened authenticated WebSocket viewers through Tuna, the existing Cloudflare public ingress, and the local gateway. The Android capture/agent path was common to all three viewers. In a separate synchronized 30-second capture, nine binary packets (53,419 bytes) arrived at the Tuna viewer, with all packets received within 3.71 seconds and no additional packets in the remaining interval. This was a mostly static home screen, so it is not a meaningful moving-content FPS measurement.

| Viewer route | Binary packets | Bytes | H.264 content received |
|---|---:|---:|---|
| Tuna | 6 | 124,717 | 3 IDR + 1 non-IDR video frame; SPS/PPS present |
| Cloudflare | 10 | 124,839 | 3 IDR + 1 non-IDR video frame; SPS/PPS present |
| Local gateway | 10 | 124,839 | 3 IDR + 1 non-IDR video frame; SPS/PPS present |

During the same interval the backend recorded 10 Android ingress frames / 124,839 bytes and 10 Redis publications / 124,839 bytes. Its viewer-send counters advanced by 26 packets / 374,395 bytes, matching the three viewer totals. No stream queue-drop or viewer-send-failure counter increased in the sampled delta.

Packet counts vary because SPS/PPS may be repeated. The three viewers received the same encoded video payload. To verify decode rather than only WebSocket receipt, the captured remote packets were replayed in Chrome using the production TypeScript decoder modules from the repository. The newer `frontend/lib/h264-decoder.ts` rendered five frames at 1280×720 from both Tuna and Cloudflare samples with zero invalid packets and zero decode errors. The legacy decoder used by the device inspector rendered five frames from the Tuna sample with zero frame drops. The sample contained SPS, PPS, one IDR, and four delta frames. This validates both decoders against these captured packets, but does not prove that the deployed page, its authentication/session lifecycle, or canvas presentation works end to end.

In the synchronized device-side sample, capture/encode counters reached seven frames, local accepted packets reached nine, and rejected packets remained zero. The agent reported zero FPS after the static screen stopped generating new frames. Remote logcat showed two start requests with screen-capture permission verified, successful encoder sync-frame requests, and normal stream start/stop events; no capture or encoder crash appeared in this sample. This is evidence for a short, mostly static session only.

The Tuna readiness endpoint returned HTTP 200. A later read showed the canary still online on `1.2.32-dev` with a fresh heartbeat. The static-name tunnel also returned readiness 200 before the one-device route update. The canary's route update was saved for this device only, but the backend/agent status does not currently expose which route slot carried the management WebSocket. A transient authentication race occurred during the route change; the agent retried and returned online. These are point-in-time checks, not an uptime/SLO result or proof that management traffic is currently using Tuna.

## Product constraints and operational implications

Tuna's [HTTP tunnel documentation](https://tuna.am/en/docs/tunnels/http/) says HTTP tunnels support bidirectional WebSockets. It also says free HTTP tunnels use dynamic names and are limited to 30 minutes, while reserved names require a subscription. Its [TCP tunnel documentation](https://tuna.am/en/docs/tunnels/tcp/) says TCP tunneling is subscription-only. A stable name therefore depends on an active account entitlement, and a running local connector remains a single point of failure unless it is supervised and agents have an independently reachable fallback.

Tuna is a useful alternate ingress for this pilot, but the evidence does not justify replacing Cloudflare for every device. The operator's saved Tuna CLI credential reports paid access through 28 September 2026; the CLI output does not identify the exact plan. The official [Russian pricing page](https://tuna.am/tunnels/) lists the Profi tier at ₽299/month with reserved subdomains and no tunnel time limit. A qualifying paid tier and reserved hostname remove the free dynamic-tunnel time limit, but do not start the connector, wire the endpoint into Android discovery, supervise it after restart, or provide an independent fallback. Do not publish the local CLI token or the canary hostname in the repository, APK, public build metadata, or ordinary logs.

On Windows, this pilot's earlier Tuna connectors were started as hidden user-session processes; automatic recovery after logout/reboot was not tested. Tuna's [service guide](https://tuna.am/en/docs/tunnels/guides/service/) requires an elevated PowerShell session to install a service and warns that it runs as the privileged installer by default unless a runtime user is selected. When using the existing user-profile config, the service also needs an explicit config path and read permission; the token should not be placed in command-line arguments. The guide directs Windows service troubleshooting to Event Viewer. This host has no Tuna service/task, and the current PowerShell process is not elevated. Its Docker Compose alternative uses host networking, which Tuna says requires enabling Docker Desktop's development feature on Windows/macOS; that feature is not enabled here. The current setup is therefore not a persistent, supervised tunnel deployment.

### Runtime and discovery recheck — 28 September 2026 (pre-connector snapshot; superseded below)

The local Sphere frontend and backend containers were healthy. The local gateway returned HTTP 200 from `/health` and `/api/v1/health/readyz`. The saved Tuna CLI credential authenticated and reported paid access through 28 September 2026. There was no running Tuna process, Windows service, or Tuna-specific scheduled task, so no new remote Tuna request or live video frame was tested in this recheck. The current PowerShell process was not elevated.

The signed discovery document read from `RootOne1337/sphere-agent-config` was version 25, issued 25 September and expiring 25 October 2026. It contained one HTTPS `server_url` under the Cloudflare Quick Tunnel domain; it did not contain a Tuna address. The local publisher configuration still watches the `cloudflare-quick` Compose service every 60 seconds and keeps a `loca.lt` URL as its fallback. That fallback's `/api/v1/health/readyz` returned HTTP 503 during this check, and the Windows publisher task's last result was `1`. Therefore the paid Tuna subscription is not currently wired into discovery. The publisher can retain a configured fallback URL, but it only discovers Cloudflare Quick Tunnel as the primary route; using Tuna as primary would need publisher/discovery changes. The current fallback failure blocks safe publication until it is replaced with a running, verified route. The Cloudflare URL remains the published route; no fleet route was changed.

The previous private Tuna log records a 15-second SSH keepalive timeout followed by `Connection restored` about three seconds later. That is direct evidence that the running client recovered from one transient tunnel interruption. It is not evidence of unattended start after reboot/logoff, current Tuna route selection by Android, sustained uptime, or agent failover. Tuna's [HTTP tunnel documentation](https://tuna.am/en/docs/tunnels/http/) limits free dynamically named tunnels to 30 minutes and makes reserved subdomains subscription-only; the current official [Profi pricing](https://tuna.am/tunnels/) lists no time limit. A reserved name addresses endpoint stability, but the local connector still needs supervision and agents still need a tested fallback.

## Findings

1. **No proof that Cloudflare dropped the H.264 payload in this canary.** The Cloudflare and local viewers received the same four encoded video frames that the Tuna viewer received.
2. **Decoder acceptance passed for the captured sample, not for the deployed page.** Both repository decoders rendered the captured frames in a Chrome secure context. Browser navigation to the actual authenticated pilot page was unavailable to the isolated test runner, so the production route, session handling, and rendered canvas still need live-page verification.
3. **The test exposed a stale-frame presentation defect.** `frontend/components/sphere/DeviceStream.tsx` replaced the video with a full-screen black overlay after ten seconds without a decoded frame, even when a valid frame had already rendered. The current change keeps the last good frame visible and shows a compact, non-blocking stale/retry badge; focused regression tests cover that behavior.
4. **No useful frame-rate conclusion from an idle screen.** The Android capture stage must be tested while display content changes. Do not attribute a static-screen sample to an ingress provider.
5. **Tuna has not yet passed a soak or failover test.** A fixed name improves endpoint stability but does not remove the connector, account, edge, DNS, or ISP failure modes.
6. **The rollout remains one device.** The other Android routes and the signed discovery publication were not changed.
7. **The UI-only pilot rollout does not establish source-to-image provenance.** It replaced only the local pilot frontend container; it did not publish a release, restart the backend, or update any Android APK.
8. **The paid Tuna account is not the active fleet discovery route.** The signed manifest still points to Cloudflare, while the configured fallback is an unhealthy `loca.lt` endpoint. The publisher currently supports discovering Cloudflare Quick Tunnel as primary; it can only carry a Tuna endpoint if configured as fallback. No current Tuna connector or Tuna-backed end-to-end Android stream was confirmed on 28 September.
9. **A persistent Windows connector is not installed.** Tuna documents an elevated service installation and recommends a non-privileged runtime identity; the current shell is not elevated and the machine has no Tuna service/task. A paid reserved name alone will not survive Windows logout or restart.

## Next acceptance steps for the 27 September viewer sample (superseded by the live release gate below)

1. Install the reserved Tuna connector as a Windows service from an elevated session, run it under a least-privilege identity that can read the existing Tuna config, and configure/verify service recovery and Event Viewer logging. Then verify `/health` and `/api/v1/health/readyz` externally. Do not publish the Tuna endpoint to device discovery until both checks pass and the tunnel remains available through a controlled connector restart.
2. Keep the Tuna route limited to this canary while observing heartbeat age and stream diagnostics for at least 15 minutes. Do not call it the active management route until the agent reports its selected route. Restore the saved Cloudflare route if the canary loses heartbeat or the connector becomes unavailable.
3. Run a controlled, reversible screen-change test on the same emulator. Compare Android captured/rendered/encoded counters with backend ingress, Redis publication, browser decoder output, and canvas presentation. Keep the device on a harmless system screen; do not launch the game or alter app data.
4. Verify the authenticated production page in a real browser session and confirm the received frames reach its canvas. The isolated Chrome test decoded the production decoder modules but did not navigate the signed-in pilot page.
5. Repeat the viewer probe through Tuna and Cloudflare separately, then compare real decoded/rendered frame counts and latency. A binary WebSocket receipt alone is not a successful stream acceptance.
6. Perform a bounded primary-failure test on the same canary and verify Android reconnects through the configured fallback without reinstalling the APK. Save before/after route receipts and device heartbeat timeline.
7. Only consider updating signed discovery or more devices after the canary survives the above checks and the account has a stable-name entitlement for the planned test window.

## Reproduction and safety

The private probe scripts and raw results are under ignored `.local-pilot/tuna-pilot` and `.local-pilot/rollout/ota-ui-20260927`. They are intentionally excluded from source control because they contain operator/session data. The test was restricted to one remote device; no APK was published and no catalog records were deleted.

## Docker connector recheck — 28 September 2026 (first deployment snapshot; superseded below)

The earlier statement that no Tuna connector was running was true at the time of the 28 September discovery recheck, but it is superseded by this later check. A separate `sphere-tuna-canary` Docker Compose project now runs the reserved Tuna HTTP connector. It forwards to the local pilot gateway through Docker Desktop's `host.docker.internal:18080` bridge; it does not use host networking, publish a host port, or modify the existing `sphere-tunnel` project.

The connector uses the official Tuna image pinned by digest `yuccastream/tuna@sha256:bb214af134a42d8c6266ae3d9bf0e67b2c60db0dcbfa111ae8ef68b9ce956449`. The Compose definition runs as UID/GID 65532, with a read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, an init process, `unless-stopped` restart policy, and bounded JSON log rotation. The existing user-profile Tuna config is mounted read-only at runtime and is not tracked by Git. The Compose model validates successfully.

At the verification instant the container was `running`, had restart count 0, and had started at 2026-09-27 20:03:26 UTC. The Tuna connector log reported successful forwarding. Through the reserved Tuna ingress, `/health`, `/api/v1/health/readyz`, `/api/v1/config/agent`, and `/devices` each returned HTTP 200. Four additional readiness rounds, five seconds apart over 20.5 seconds, all returned HTTP 200 for both `/health` and `/api/v1/health/readyz`. The local gateway and Tuna ingress returned byte-identical bodies for readiness and agent config; the config body was 464 bytes at `config_version=20260925`. This confirms the external route reaches the intended pilot service at that instant. It is a short functional check, not a connector uptime or reboot-survival result.

The agent config still sets its primary `server_url` to the Cloudflare Quick Tunnel; neither its primary nor fallback URL points to Tuna. No Android route, signed discovery document, backend configuration, or APK was changed. The live Tuna ingress therefore exists and is usable for pilot HTTP requests, but Android agents have not been switched to it. No authenticated Android WebSocket stream or video frame was exercised through this new container route. Do not describe this as a fleet-wide tunnel fix.

The Tuna `tunnel list`/`session list` inventory commands were not independently verified: the CLI exposes these as API-key operations, while this least-privilege connector only has the saved tunnel credential. The active forwarding log and successful external requests independently prove the connector is serving traffic, but not the exact row displayed in the Tuna dashboard. The browser UI check could not be completed by the current desktop browser-control runtime. The account CLI reported paid access through 28 September 2026; the exact subscription tier was not available, so continued reserved-name entitlement should be checked in the Tuna account before the next test window.

The `unless-stopped` policy restarts the container when the Docker engine starts, provided Docker Desktop itself is running. At this check `com.docker.service` was `Stopped` with `StartMode=Manual`; Docker Desktop's Linux engine and the container were nevertheless running. Automatic Docker Desktop startup after Windows login, operation across Windows logout/reboot, and a controlled container restart followed by Android reconnection remain untested. The tunnel must remain a single-device canary until those lifecycle checks and an authenticated remote WebSocket/video test pass.

## Android route recheck — 28 September 2026 (pre-publication snapshot; superseded below)

The Android fleet has **not** automatically migrated to the Docker-backed Tuna route. The live backend's `/api/v1/config/agent` still returns Cloudflare Quick Tunnel as `server_url` and no fallback URL; its config version is `20260925`. The signed discovery v25 used by the locally built 1.2.33-dev/10233 candidate has Cloudflare as primary and `loca.lt` as fallback, with no Tuna URL. That artifact's private build metadata says it was not published or installed; this is not evidence of what is installed on remote LDPlayer instances.

The retained 27 September Tuna route mutation is a deliberate per-device canary command for one subscriber on APK 1.2.32-dev. Its result receipt says `completed`, `updated=true`, `subscribers=1`, and no error; its intent set Tuna as primary and Cloudflare as fallback. This is not an automatic fleet-wide redirect or a fresh acknowledgement from every currently running APK. The current Docker connector forwards the same reserved Tuna route used by that canary, but device reconnection through this Docker connector has not yet been re-proven.

The current default branch of `RootOne1337/sphere-agent-config` contains a production JSON at config version 2 with an empty `server_url` and no fallback; its latest commit is dated 18 March 2026. It does not publish the signed discovery v25 currently recorded in the local pilot evidence. Treat this as configuration-source drift: neither this repository file nor the live backend presently advertises Tuna to newly starting agents. `ConfigWatchdog` in the APK periodically fetches discovery and updates route candidates; it cannot select an unadvertised Tuna ingress on its own. Do not reinstall or mass-update APKs expecting this tunnel to be discovered automatically.

No remote emulator is attached to this workstation's ADB, so its installed package version and currently authenticated WebSocket route cannot be read directly from here. The live HTTP checks above prove the Tuna connector's path to the backend only. Fleet migration still requires publishing a signed Tuna route with Cloudflare retained as fallback, verifying the signature/config source consumed by the APK, then testing one identified remote device's reconnect and video frames before any wider rollout.

## Live route and capture recheck — 28 September 2026, 21:26 UTC

This section supersedes the earlier point-in-time configuration statements above. It records the state observed from the local pilot host at the timestamp in the heading; it is not an uptime guarantee.

### Discovery publication and public ingress

The live signed agent config is version `20260928`, with Tuna as primary and Cloudflare Quick Tunnel retained as fallback. Both public ingress paths returned HTTP 200 for `/api/v1/health/readyz`, `/api/v1/config/agent`, `/bootstrap/agent.signed.json`, and `/devices`. The signed bootstrap bytes fetched over each ingress were identical to the local signed mirror. This proves the current public ingress and publication path, but not that an already-running APK selected Tuna.

The Tuna connector is running in Docker with restart count 0. Its upstream was corrected from the UI nginx listener to the pilot public gateway on port 8080; the older `host.docker.internal:18080` description above is historical and no longer describes the current connector. Both the Tuna and Cloudflare routes reach the same pilot application. No production service or the old `sphere-tunnel` project was changed.

### Registry, heartbeat, and Android stream telemetry

The live database contained 29 device records: 19 active and 10 inactive. Of the active records, 14 had Redis `online` status and heartbeats no older than 45 seconds; 5 had no live status entry. The reported expectation of 23 devices is therefore four higher than the active server catalog observed in this sample. The inactive records were not reactivated.

The 14 fresh active records also had stream-diagnostic snapshots observed within 120 seconds. Their cumulative snapshots summed to 315 captured, rendered, and encoded frames, 1,029 WebSocket queue accepts, and zero queue rejections. These are per-session cumulative counters, not FPS and not proof that a browser decoded those frames. The active agents reported version codes `10222` (5), `10230` (3), `10231` (1), and `10232` (5); none of the 14 reported `10233`.

The online canary `auto-ph-025` reported version `10232`, heartbeat age 29 seconds, and active stream telemetry observed 29 seconds earlier: 23 captured/rendered/encoded frames, 71 queue accepts, and zero queue rejections. The counters prove the APK capture/encode/local-queue stages produced data in that diagnostic interval. They do not prove an end-to-end frame reached or decoded in the web viewer.

### Management WebSocket route evidence

The last-24-hour public-gateway access-log sample contained 7,137 Android WebSocket upgrade responses (`101`) and 24 `502` responses on the Cloudflare fallback route, across 19 device identifiers. Fourteen of the route's identifiers overlapped devices with a heartbeat fresh within 45 seconds. Tuna had only two short `101` entries, zero response bytes, and one identifier; that identifier did not match any active catalog device. Those two entries are not evidence of an authenticated Android agent session. `auto-ph-025` had 606 `101` and 3 `502` log entries on Cloudflare, and none on Tuna.

Nginx writes these access records when a WebSocket request ends, so these counts describe completed requests during the log window, not a live socket inventory. Even with that caveat, the current fleet sample shows Cloudflare carrying the observed Android sessions; it does not show an active registered device using Tuna.

The local `1.2.33-dev`/`10233` APK candidate was built from source commit `863786f`, remains unpublished, and is not reported by any of the 14 fresh agents. That source keeps the selected route ahead of the signed primary and does not force an already-connected agent to migrate. The committed source change now orders a verified signed primary first for the next connection attempt while retaining the last authenticated route as the selected recovery candidate until another route authenticates. `ConfigWatchdog` schedules a reconnect when the preferred signed route changes; a failed Tuna attempt can fall back to the prior working ingress and then the explicitly configured fallback. This code has targeted regression tests, but it is not yet in an APK installed on the remote canary.

### Static screens and what “no new frame” means

The Android pipeline draws into the encoder surface only when the `ImageReader` callback supplies an image; it does not synthesize repeated screenshots on a timer. The backend transport also explicitly accounts for `ImageReader` producing no callback while a screen is static (`backend/websocket/video_transport.py`). Therefore a frozen last frame or the viewer's “no new frame” age alone cannot distinguish a healthy static screen from a stalled capture or broken transport. For diagnosis, correlate the active agent heartbeat/session, capture/render/encode counter deltas, backend ingress and Redis publication, and actual browser decode/presentation. In this sample, agent counters confirm some recent capture activity, while the current route evidence still points to Cloudflare rather than Tuna.

The practical consequence is that a still Android home screen may legitimately produce no fresh video packets after its initial frames. A viewer should retain and label the last decoded frame as stale instead of treating it as proof of device disconnection. A transport/capture acceptance check must include a controlled moving-screen interval and compare per-stage counter deltas; a static idle interval is useful for verifying that the capture service stays alive without falsely requiring continuous video traffic.

### Route-migration regression verification — 28 September 2026, 21:46 UTC

The Android route-migration changes passed the focused `testDevDebugUnitTest` regression suites: `CommandDeliveryTest` 24/24, `SavedRouteFailoverTest` 31/31, and `ConfigRecoveryTest` 27 passed / 1 skipped / 0 failed. This verifies that a signed primary is tried first after a preference change, an existing authenticated route remains available until a new route authenticates, and an intentional reconnect cancellation does not count as a failed primary attempt. It is source-level test evidence only; it does not prove the new route in a remote APK or viewer.

### Release gate

Do not call the tunnel issue resolved or roll this route to the fleet yet. The source tree now reserves version `1.2.34`/`10234` for the next monotonic APK candidate from the route-selection changes. Build it from the reviewed commit, verify its signed-discovery installation and version metadata, then install it on one identified remote canary. Acceptance requires that the canary report the new version, connect through Tuna with an authenticated Android WebSocket, keep fresh heartbeats, and deliver a controlled moving-screen sample that is decoded in the real web viewer. Keep Cloudflare as fallback and retain a rollback route. The lack of remote ADB on this workstation prevents independently installing or identifying remote APKs.

### Source validation

On 28 September 2026, the targeted Android route/config suite was rerun from source with all Gradle tasks forced: 55 tests passed (24 command-delivery and 31 saved-route/failover tests), with zero failures or errors. The discovery-publisher suite passed 32 tests. `git diff --check` was clean. This validates the code-level transition and publication rules; the Android candidate build and remote canary acceptance are still separate release gates.
