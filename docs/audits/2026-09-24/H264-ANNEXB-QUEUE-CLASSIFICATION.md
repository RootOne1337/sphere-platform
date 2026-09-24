# AUD-167 · Backend queue misclassified 3-byte H.264 NAL units

**Updated 25 September 2026 · P1 video availability · backend fix deployed; remote acceptance OPEN.**

[Remote ingress investigation](REMOTE-INGRESS-AB.md) ·
[First-frame recovery](../2026-09-20/STREAM-FIRST-FRAME.md) ·
[Fleet32 gate](../2026-09-20/FLEET32-PREFLIGHT.md)

## Finding

The backend recognized only the 4-byte Annex-B start code (`00 00 00 01`) when it
classified queued video frames. Android's H.264 splitter accepts both 3-byte and
4-byte Annex-B start codes, and its Sphere wire frame has a 14-byte header before
the NAL payload. A frame with a 3-byte prefix was therefore marked `UNKNOWN` by
`VideoFrame`, even when its wire header marked it as a keyframe.

`VideoStreamQueue` treats only IDR, SPS, and PPS as critical. It removes non-critical
frames older than 200 ms and drops them first under queue pressure. A WAN-delayed
3-byte IDR could consequently be evicted as if it were a disposable P-frame. That
can leave a viewer waiting for a picture while a faster local route still appears
healthy.

This is a confirmed source-level queue defect and a credible contributor to the
remote-only symptom. The saved PH006 sample contains only SPS/PPS packets and no
raw IDR bytes, so it does **not** prove that those particular remote packets used
3-byte prefixes or that this defect alone caused the incident. Cloudflare and the
Android capture/encoder path remain separate open boundaries.

## Reproduction

The regression test builds actual Sphere wire frames: version and flags, an
8-byte timestamp, a 4-byte payload length, then an Annex-B NAL. Against the old
parser, all four 3-byte NAL classifications failed (`IDR`, `P`, `SPS`, `PPS`),
while the corresponding 4-byte cases passed. A second test aged a 3-byte IDR by
10 seconds and inserted a newer frame. The old queue classified the IDR as
non-critical and evicted it under the 200 ms latency policy.

The pre-fix run of `tests/test_ws/test_video_queue.py` was **red: 5 failed, 26
passed**. This proves the parser and queue behavior without relying on tunnel
assumptions or a production stream.

### Reproduction against the running pilot image

At **2026-09-24 17:08 UTC**, the same synthetic packet was evaluated in a separate
Python process inside the running backend container
`sphere-pilot-20260911-backend:ff87b56dbbd7`. It contained a valid 14-byte Sphere
header with the keyframe bit set and a three-byte `00 00 01 65` IDR payload. The
live image classified it as `UNKNOWN` (`nal_type=0`, `critical=false`); the
four-byte-prefix control was classified as IDR (`nal_type=5`, `critical=true`).
An in-memory queue test aged that IDR by ten seconds and inserted a P-frame; the
running image logged one stale-frame eviction and dropped the IDR. No service
state, database, or remote device was changed by this probe.

This confirmed that the then-active `ff87b56` image contained the queue defect.
The fix was later built and deployed as
`sphere-pilot-20260911-backend:b2562ca04f5f`; the running container reports
healthy. A read-only probe inside that running image constructed a complete
Sphere wire packet with a three-byte IDR prefix and verified `nal_type=5` and
`is_critical=true`; a four-byte P-frame control verified `nal_type=1` and
`is_critical=false`. This confirms the deployed classifier behavior. It does
**not** prove that PH006/PH008 sent an IDR: the saved remote capture contains no
raw IDR bytes.

## Fix

`backend/websocket/frames.py` now:

- unwraps a complete Sphere wire frame using its version, 14-byte header and
  declared payload length before inspecting H.264 bytes;
- recognizes both 3-byte and 4-byte Annex-B start codes;
- preserves the wire keyframe flag as a priority fallback, while keeping SPS/PPS
  critical based on their NAL types.

The queue's existing frame-count, byte and latency bounds are unchanged. Malformed
or unknown non-keyframes remain droppable, and the flag does not make the queue
unbounded.

## Verification

- After the fix, `tests/test_ws/test_video_queue.py` and
  `tests/test_ws/test_video_queue_limits.py`: **33 passed**.
- Combined stream regression set covering Android WS handlers, viewer keyframe
  routing, bridge, frame queues, metrics and Pub/Sub recovery: **83 passed**.
- Ruff passed for the modified backend module and queue tests.
- The focused Android capture lifecycle and command-delivery suite passed **32
  tests**; Android source and APK were not changed by this fix.
- `git diff --check` passed.
- Pilot candidate image `sphere-pilot-20260911-backend:b2562ca04f5f` was built
  from an allowlisted `git archive`; the packaged `frames.py` SHA-256 matched
  the source. In a separate read-only container with networking disabled, the
  three-byte IDR classified as critical and survived the stale-queue scenario;
  the four-byte control also passed and the queue dropped zero frames.

## Acceptance and residual risk

The queue fix is deployed to the running pilot. The remote fleet's installed APK
versions and exact H.264 start-code bytes remain unverified. One remote canary
must show an IDR reaching backend ingress and then the viewer, with an actual
decoded frame on both the initial connection and one reconnect. Keep the
Cloudflare A/B question open until the same canary is measured across the Android
egress path; changing only viewer ingress does not isolate that path.
