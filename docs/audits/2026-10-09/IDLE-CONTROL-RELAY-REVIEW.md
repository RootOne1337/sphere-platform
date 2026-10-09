# Idle control: confirmed relay path and accurate failure reporting

9 October 2026. Source review against `556a311a`; UI correction below is
source/test only until a separate installation receipt exists. Runtime during
the observation: UI `86354350`, API `d720232e`, PH011 APK `1.2.49-dev / 10249`.

[Current work](../../operations/WORK-STATUS.md) ·
[Server timing boundaries](../../operations/CONTINUOUS-INPUT-TIMINGS.md) ·
[Previous installed failure](CONTINUOUS-SERVER-TIMINGS-INSTALLED.md).

## Reproduction through the public host

At approximately 16:39–16:41 UTC, a separate background browser tab opened the
PH011 device card through the existing public Tuna host. Video/control was
selected once. No Android DOWN, MOVE, UP, keyboard, navigation, script, recorder,
save, device restart or APK update was submitted by this check.

The current installed UI reproduced the generic warning that Android had not
confirmed a command. Its retained controller snapshot reported:

| Observation | Value |
| --- | --- |
| Phase at fencing | ready |
| Offered / acknowledged sequence | 4 / 1 |
| Pending receipts | 3 |
| Oldest action | sequence 2, HEARTBEAT |
| Oldest age / deadline age | 592 / 503 ms |
| Last actual ACK RTT / age | 518 / 329 ms |
| Browser tick gap | 15 ms |
| Last send age | 80 ms |
| Held pointer / terminal receipt | none / none |
| Browser socket / buffered bytes | OPEN / 0 B |
| Automatic idle reconciliation | 1 of 1 used |

The controller subsequently showed `closed` after release. At the first expanded
diagnostic observation, the viewer had received 18 packets / 177194 bytes,
decoded 12 outputs and drawn 12 frames, with zero invalid packets, decode errors
or render errors. Its last frame had become stale. Later counters reached
32 packets / 460153 bytes and 18 drawn frames. These are finite observations of
a mostly static screen, not an FPS, gesture or latency acceptance test.

The tab was switched to View and closed. Private evidence is bounded in
`.local-pilot/direct-transport-review-20261009/idle-before.txt` and
`idle-before.jpg`. No credential, raw frame, owner/session identifier or complete
diagnostic payload is published in this report.

## What the code establishes

* `frontend/components/sphere/DeviceStream.tsx` connects the active canvas to
  the server stream WebSocket. `frontend/lib/h264-decoder.ts` decodes its binary
  video packets. There is no active RTCPeerConnection in this path.
* `android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt`
  sends both binary video and JSON input receipts on the same authenticated
  OkHttp WebSocket. Both paths check a 1 MiB outbound queue ceiling.
* A small receipt can therefore be enqueued behind video already accepted by
  that socket. A byte ceiling bounds memory, not delay. This is a confirmed
  architectural risk, **not proof that this queue caused the observed timeout**.
* `backend/websocket/continuous_runtime.py` and `continuous_delivery.py` relay
  viewer input and native receipts through the server/Redis topology. A local
  emulator does not currently imply a direct browser-to-APK media/input path.
* `RootTouchPipeFactory.kt` waits at most 500 ms for the helper ACK;
  `ContinuousTouchSupervisor.kt` handles one owner sequentially.
  `RootTouchSession.java` has a 1500 ms native lease watchdog. The browser's
  500 ms receipt deadline includes additional transport and scheduling work.
  These values describe different boundaries; they are not additive allowances.

The previous seven observed server coroutine spans were below 25 ms. They do
not cover every queue and were not correlated to this exact sequence. Neither
those spans nor a zero browser buffer exonerate the public route, APK, native
pipe or reverse path. The exact producer of the delay remains unknown.

## Contained UI correction

The first heartbeat-only timeout retains the existing one automatic
reconciliation, gated by confirmed native release. The second heartbeat-only
timeout now says that a connection confirmation was delayed without a touch
and that automatic recovery has already been used. Its UI failure category
remains `idle_receipt_timeout`, including after confirmed release.

An outstanding DOWN/held pointer or exact terminal receipt continues to show
the unknown-command warning. Input and Android navigation remain blocked after
the repeated failure. There is no extra retry, silent discrete fallback, replay,
new timer, queue, network endpoint or relaxed deadline.

Expanded diagnostics now explicitly identify the installed transport as video
and control through the server WebSocket; direct APK connectivity is not claimed.

## Verification and remaining work

* Pointer/controller integration: **138 tests passed**. The repeated idle case
  checks the accurate category, blocked input/navigation, no extra probe after
  release and heartbeat-only traffic. Two additional cases protect held/terminal
  timeouts from being misclassified as idle.
* Full frontend: **139 suites / 1950 tests passed**; TypeScript check passed.
  Existing unrelated Radix dialog-description warnings remain in the test output.
* No UI/API/APK was installed by this source review. The browser observation
  above used the preceding UI and proves reproduction, not the new wording.

SF26-05 / EP-020 / EP-029 remain OPEN. Correct wording does not improve RTT.
The next transport design must remove unnecessary media **and control** relay
when ICE establishes a direct path, preserve native ownership/fencing and make
direct/relayed/unknown status visible. Network/native attribution, controlled
comparison and a measured prototype remain required before rollout.
