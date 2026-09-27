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

Tuna is a useful alternate ingress for this pilot, but the evidence does not justify replacing Cloudflare for every device. The user's subscription is not renewed by this experiment. Do not publish the local CLI token or the canary hostname in the repository, APK, public build metadata, or ordinary logs.

## Findings

1. **No proof that Cloudflare dropped the H.264 payload in this canary.** The Cloudflare and local viewers received the same four encoded video frames that the Tuna viewer received.
2. **Decoder acceptance passed for the captured sample, not for the deployed page.** Both repository decoders rendered the captured frames in a Chrome secure context. Browser navigation to the actual authenticated pilot page was unavailable to the isolated test runner, so the production route, session handling, and rendered canvas still need live-page verification.
3. **The test exposed a stale-frame presentation defect.** `frontend/components/sphere/DeviceStream.tsx` replaced the video with a full-screen black overlay after ten seconds without a decoded frame, even when a valid frame had already rendered. The current change keeps the last good frame visible and shows a compact, non-blocking stale/retry badge; focused regression tests cover that behavior.
4. **No useful frame-rate conclusion from an idle screen.** The Android capture stage must be tested while display content changes. Do not attribute a static-screen sample to an ingress provider.
5. **Tuna has not yet passed a soak or failover test.** A fixed name improves endpoint stability but does not remove the connector, account, edge, DNS, or ISP failure modes.
6. **The rollout remains one device.** The other Android routes and the signed discovery publication were not changed.
7. **The UI-only pilot rollout does not establish source-to-image provenance.** It replaced only the local pilot frontend container; it did not publish a release, restart the backend, or update any Android APK.

## Next acceptance steps

1. Keep the Tuna route limited to this canary while observing heartbeat age and stream diagnostics for at least 15 minutes. Do not call it the active management route until the agent reports its selected route. Restore the saved Cloudflare primary/fallback route if the canary loses heartbeat or the connector becomes unavailable.
2. Run a controlled, reversible screen-change test on the same emulator. Compare Android captured/rendered/encoded counters with backend ingress, Redis publication, browser decoder output, and canvas presentation. Keep the device on a harmless system screen; do not launch the game or alter app data.
3. Verify the authenticated production page in a real browser session and confirm the received frames reach its canvas. The isolated Chrome test decoded the production decoder modules but did not navigate the signed-in pilot page.
4. Repeat the viewer probe through Tuna and Cloudflare separately, then compare real decoded/rendered frame counts and latency. A binary WebSocket receipt alone is not a successful stream acceptance.
5. Perform a bounded primary-failure test on the same canary and verify Android reconnects through the configured fallback without reinstalling the APK. Save before/after route receipts and device heartbeat timeline.
6. Only consider updating signed discovery or more devices after the canary survives the above checks and the account has a stable-name entitlement for the planned test window.

## Reproduction and safety

The private probe scripts and raw results are under ignored `.local-pilot/tuna-pilot` and `.local-pilot/rollout/ota-ui-20260927`. They are intentionally excluded from source control because they contain operator/session data. The test was restricted to one remote device; no APK was published and no catalog records were deleted.
