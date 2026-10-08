# Studio: explicit recorder intent and native release

8 October2026. Source prepared; installed acceptance required separately.

## Problem and final behavior

The workbench permanently observes HTTP key/text receipts so that pending
commands and late ACKs can retain their original review slot after Stop.
DeviceStream incorrectly inferred recording from those observer callbacks.
Consequently normal Studio control could never negotiate continuous gestures.

`recordingMode` now expresses intent explicitly through Workbench→SingleDeviceStream
→DeviceStream. Receipt observers remain attached in every mode. Start retires
this viewer's native owner; discrete recording accepts input only after native
RELEASE3. The laboratory shows preparation while a frame/release is pending.
Stop returns to automatic capability negotiation. No extra gesture toggle.

An unfinished discrete drag is discarded on mode/inspection/lock changes; its
UP cannot become a new swipe. A pending capability does not create an owner
after Start. A missing release fences recording after3 seconds and reports
recording_release_unknown; an unknown release never unlocks the recorder.
Wheel uses the current recording intent, not a callback captured in an earlier
render. Key/text ACK observations and close guards remain attached after Stop.

## Verification

Before implementation:6 failed/92 passed across pointer, inspector and workbench
regressions. After implementation:201 passed in6 suites; nonincremental
TypeScript passed. Existing recorder tests now specify explicit recording intent.

New cases exercise permanent observers with MOVE before UP, Start during held
touch, missing/unknown native release, unfinished recording drag during Stop,
forwarding intent and readiness, late ACK after Stop, and preparation status.
The socket/decoder/native receipts in these tests are fixtures; they do not
establish installed Android execution or browser behavior.

## Limits and next work

This fixes ordinary control and discrete recording handoff. It does not add
continuous trajectory recording, native PNG/XPath/crop/pixel evidence bundles
or frame-synchronous playback. Those remain in
[recorder roadmap](STUDIO-RECORDER-NEXT-P1.md).

The task-launch path also needs a separate audited handoff: creating a task
currently sets a read-only gate while the request is submitted, but does not
await this viewer's native release before task creation. A pending launch or
unknown outcome must never be replayed. That boundary is OPEN; it is not
claimed as covered by the recorder mode fix.

SF26-05/06 and ledger9accepted/41open remain unchanged until their full
acceptance criteria are met. Root SHELL exit1 and host storage incidents OPEN.
