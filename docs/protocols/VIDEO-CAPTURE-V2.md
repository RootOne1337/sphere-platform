# Binary video capture identity, version 2

Initial checkpoint: **source canary, not installed on 3015**, 7 October 2026.
Later integration and installation are tracked in
[CURRENT-STATE](../operations/CURRENT-STATE.md) and
[live integration](../audits/2026-10-08/CONTINUOUS-INPUT-LIVE-INTEGRATION.md).
This extends the existing relay v1 H.264 envelope without changing the NAL payload,
encoding, bitrate, dimensions or aspect ratio. It is a prerequisite for
continuous input; it does not enable continuous input by itself.
The byte layout below describes the WebSocket relay envelope, not every video
transport. Direct video uses a separate negotiated peer and capture binding; its
metadata and media delivery cannot be inferred from this relay header.

## Exact bytes

All multibyte integers use big endian. No variable-length strings or JSON are
inserted into the encoded access unit.

| Byte range | Type | Meaning |
| --- | --- | --- |
| 0 | u8 | Version 2 |
| 1 | u8 | Bit 0: keyframe hint; all other bits reserved/zero |
| 2–9 | i64 | Existing milliseconds since capture start |
| 10–13 | u32 | Original NAL payload length; does not include header |
| 14–29 | 16 bytes | Non-nil capture UUID, network byte order |
| 30 onward | bytes | Original H.264 Annex-B access unit |

When capture geometry is available and the canary is enabled, a new capture session
gets a new random epoch on each start, including a same-size restart. If geometry
is unavailable, `StreamingManagerImpl` has no input session/epoch and falls back
to v1 packets even with the canary flag. The UUID in the JSON input offer and in the v2 frame represents the
same identity. Actual displayed width/height come from the decoded VideoFrame,
not a trusted header assertion. Timestamp remains stream-relative; it is not
browser wall-clock latency or an input execution timestamp. The packager uses
the difference between two `System.currentTimeMillis()` readings: it is not a
monotonic clock or the encoder's presentation timestamp. A wall-clock correction
can make the difference negative; the browser parser rejects such a packet.

Payload bound: **1 MiB**; v2 overhead: **30 bytes**, 16 more than v1. No
screenshots, frame logs, history files or persistent per-frame objects are
introduced. The decoder retains at most the existing eight pending pictures,
2 MiB encoded data and 500ms decode age; each pending entry has one bounded
capture identity.

Independent fixture, timestamp12345ms, UUID00112233-4455-6677-8899-aabbccddeeff,
six-byte Annex-B IDR payload `000000016542`:

```text
020100000000000030390000000600112233445566778899aabbccddeeff000000016542
```

## APK emission boundary

[FramePackager](../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/FramePackager.kt)
retains v1 when no epoch is supplied. Only an explicit debug continuous canary
adds v2 in StreamingManagerImpl. The epoch and start clock are captured when
the encoder is created; a late old encoder callback cannot read a replacement
epoch from mutable manager state. An obsolete capture token is rejected before
publication. A restart racing after this check can still leave an old packet
in transit, but that packet keeps its old identity.

Cached SPS/PPS replay uses the active encoder's epoch. Packager rejects nil
UUID, empty v2 payload and payload exceeding the common decoder limit.
Default/release emission remains v1. Release canary flag refusal remains in
force; no production capability is advertised by these changes.

## Server compatibility and backpressure

[frames.py](../../backend/websocket/frames.py) unwraps v1/v2 before classifying
NALs. The original packet object/bytes remain unchanged through VideoFrame and
the queue. UUID bytes that happen to contain an Annex-B start code must never
be scanned as SPS/PPS/IDR.

Recognized truncated, wrong-size, nil-epoch, reserved-flag or oversized v2
envelopes have no trusted keyframe/configuration classification. This is a
classifier boundary, **not a new ingress rejection endpoint**: an unknown
packet may still traverse transport, where the browser rejects it. The server
classifier does not validate timestamps; the browser additionally enforces a safe
nonnegative microsecond value. Classification does not prove browser acceptance. Raw Annex-B
compatibility remains. Normal queue recovery still waits for a true IDR.

## Browser output boundary

[parseSphereFrame](../../frontend/lib/sphere-frame.ts) validates fixed header,
length, version and safe nonnegative microsecond timestamp; for v2 it also
checks reserved flags and non-nil identity. It returns a view of the original NAL bytes; it does not clone a
large access unit to extract metadata.

[H264Decoder](../../frontend/lib/h264-decoder.ts) ties each submitted picture
to its capture epoch. On any epoch change, including same-resolution or
v2→v1, it retires the old codec, clears pending pictures and SPS/PPS, and calls
the existing recovery callback before new decoding. Fresh SPS/PPS and IDR are
required. Obsolete-generation outputs are closed once without rendering.

`lastRenderedCapture` becomes available only after the current-generation
`onFrame` callback returns successfully with valid display dimensions. Header
receipt, SPS/PPS, decode submission and failed/stale output do not provide it.
Reset, recovery and generation replacement clear this binding. A reset inside
the rendering callback cannot publish readiness afterwards. Callback/getter
copies prevent outside mutation of the cached identity.

v1 produces no invented epoch and keeps the existing one-argument rendering
callback. New v2 rendering optionally provides `{captureEpoch, frameWidth,
frameHeight}`. This is local evidence for the displayed source, **not** an
Android input ACK, owner lease or permission grant. The current
[DeviceStream](../../frontend/components/sphere/DeviceStream.tsx) uses the
rendered capture binding in continuous-input admission. Actual availability
depends on negotiated capabilities, authorization and the installed artifacts;
source integration alone does not establish the behavior of a running viewer.
For direct video, capture identity is separately parsed from a session-bound
[`SV1` binding](../../frontend/src/features/stream/directVideoProtocol.ts); the
Android encoded-viewer path uses encoder presentation timestamps. Do not parse
direct RTP as this 30-byte WebSocket header or treat an advertised direct binding
as proof of decoding or display.

## Initial 7 October acceptance boundary

The fixed fixture, malformed bytes, configuration classification, queue pass
through, same-size restart, late old output, failed rendering, mutation,
reset/error/v1 transition and legacy decoder behavior have independent unit
coverage. See [validation evidence](../audits/2026-10-07/VIDEO-CAPTURE-V2-EVIDENCE.json).

At that checkpoint, real Kotlin pipe/encoder acceptance, scoped server receipts, non-retrying
multiworker owner lease, browser pointermove/loss cleanup, recording semantics
and latency/resource soak remained open. No live browser→server→APK→display
acceptance was claimed and no runtime image or production agent was replaced
by that checkpoint. Later work must be assessed using its own evidence and
limitations; see [current work status](../operations/WORK-STATUS.md) and
[continuous input server](CONTINUOUS-INPUT-SERVER.md).

## Subsequent exact-source CI and server component

Source3dc2456 passed all five hosted runs (Android push/PR, frontend, backend,
preview). A separately flagged debug artifact also built, without installation;
the earlier default APK was retained before overwriting Gradle's mutable output.
See [exact CI and both artifact hashes](../audits/2026-10-08/VIDEO-CAPTURE-V2-CI.json).

At the subsequent 8 October checkpoint the
[server lease/delivery component](CONTINUOUS-INPUT-SERVER.md) had independent
real Redis and socket-fence unit acceptance but not yet public route/subscription
integration. Current source registers the runtime and handles continuous input
in the [stream router](../../backend/api/ws/stream/router.py). These source and
historical test results do not establish current installed runtime acceptance.

## Source review boundary

On 1 November 2026 the relay contract was compared with
[`FramePackager`](../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/FramePackager.kt),
[`StreamingManagerImpl`](../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt),
[`frames.py`](../../backend/websocket/frames.py),
[`sphere-frame.ts`](../../frontend/lib/sphere-frame.ts) and
[`h264-decoder.ts`](../../frontend/lib/h264-decoder.ts). Relevant existing tests
include [FramePackagerTest](../../android/app/src/test/kotlin/com/sphereplatform/agent/streaming/FramePackagerTest.kt)
and [sphere-frame.test](../../frontend/__tests__/stream/sphere-frame.test.ts); they
were not rerun here. No installed APK, browser, network or device was checked.
