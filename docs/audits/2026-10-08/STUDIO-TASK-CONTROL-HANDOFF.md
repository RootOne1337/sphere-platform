# Studio: handoff from manual input to a saved task

8 October 2026. Source implemented and locally tested; installation and real
task canary pending. The installed UI remains `a8945e4`, API `9610523`,
PH011 pilot APK 10249. This is a continuation of SF26-05/06, not closure of the
product ledger (9 accepted / 41 open).

## Reproduced source defect

The workbench's `run()` sets a read-only render gate and immediately posts
`/tasks`. Rendering that gate subsequently retires the native continuous owner.
Task dispatch could therefore race with a still-held native pointer or an
in-flight root hierarchy read. A disabled button alone does not prove release.

## Resulting order

1. A synchronous request guard pins the selected script, saved version/hash,
   device and auth token. Repeated clicks cannot create another attempt.
2. A new, viewer-local handoff ID locks pointer, wheel, keyboard and navigation.
   The UI says that Android is being released and the task is not created yet.
3. The stream retires its native owner. Readiness requires its known native
   RELEASE, or no native owner, and an owned picture on the current open socket.
   Unknown input/release and loss of the active surface fail closed.
4. The wrapper additionally waits for this viewer's current hierarchy request
   and native screenshot verification. It blocks new reads/captures. Changing
   the screenshot lock does not abort HTTP, revoke its file or alter PNG bytes.
   A failed read or unverified screenshot blocks task preparation. A hierarchy
   request aborted on permission/socket invalidation is also insufficient:
   a later successful owned hierarchy read must clear that viewer's abort fence.
5. Only the matching attempt's readiness may resolve the wait. Immediately
   before POST, the workbench checks the current script/version/hash/token,
   execution permission, page visibility and pending key/text commands again.
   The backend's expected-current-version check remains the publication fence.
6. Exactly one POST follows. Task ownership and version in its response must
   match. A lost POST response remains uncertain; no automatic retry is added.

Preparation has a 55-second maximum, allowing the existing 50-second hierarchy
deadline. It does not extend the native 3-second release gate or the 100-second
screenshot deadline. An unfinished screenshot at 55 seconds can reject
preparation while the original capture continues. Expiry never proves release,
aborts the Android command, creates a task or turns into an unknown server commit.

A definitive preparation failure reports **"Задание не создано"** and allows an
explicit corrected attempt. Errors after submitting POST retain the existing
known-rejection versus uncertain-result distinction. Auth remount/unmount
settles the pending wait without submitting from the obsolete component.

## Meaningful regressions

The initial workbench regressions failed 3 cases / passed 21 against the prior
source: immediate POST before readiness, failure misclassification and changed
version during preparation. Final focused checks passed **237 tests / 7 suites**:

- Workbench: exact handoff ID, stale readiness ignored, one pinned POST,
  blocked preparation versus uncertain POST, bounded expiry, version/run
  authority recheck, hidden page and old auth session, existing close guards.
- Stream: held DOWN retires without replay; only known RELEASE permits readiness;
  missing or unknown release blocks the task; input remains locked after release.
- Wrapper: hierarchy drain without abort or overlap; failed drain is blocked;
  readiness cannot migrate between attempts; pending/unverified capture blocks.
- Native screenshot: execution lock drains an existing request without abort,
  retains the verified original download and blocks a second capture.
- Existing continuous controller, navigation and ordered recorder regressions.

Nonincremental TypeScript passed after the final source edit. Local
socket/decoder/native receipts are fixtures.
Hosted exact-source build/image admission and a real installed browser→task
canary are required before this document can claim installed acceptance.

## Boundaries still open

This establishes a handoff for the current Studio viewer. It is not a distributed
exclusive lease against another tab, operator or external API caller. It does
not reconcile a POST whose response is lost or prove cancellation of remote
Android SHELL after transport failure. No task execution, video latency or
frame-atomic playback is inferred from the readiness callback.

Rich observation bundles, trajectory recording, fleet fault/soak and durable
launch reconciliation remain separate audit work. Native root exit 1 and host
storage/corruption incidents remain unresolved.

[Recorder implementation](STUDIO-RECORDER-MODE.md) ·
[Installed recorder acceptance](STUDIO-RECORDER-INSTALLED-ACCEPTANCE.md) ·
[Canonical runtime state](../../operations/CURRENT-STATE.md)
