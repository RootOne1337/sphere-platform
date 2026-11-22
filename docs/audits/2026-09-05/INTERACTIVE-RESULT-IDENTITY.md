# AUD-121 · Interactive replies were mistaken for durable task results

**Medium · operational diagnostics and unnecessary SQL work · 20 September 2026.**

## Root cause and reproduction

`backend/api/v1/devices/router.py::_request_interactive_command` assigned a bare
UUID to shell, logcat and reboot requests without creating a SQL Task. The Android
result handler uses bare UUIDs for durable tasks: received/running opened task
lookup sessions, and completed/failed called TaskService. Each successful terminal
reply therefore produced `task.result.not_found` after already satisfying the
waiting HTTP request. The original night contained 1,555 such warnings, distinct
from its 164 real DAG IDs. [Original analysis](NIGHT-RUN-ANALYSIS.md).

On deployed backend `03b161e`, six harmless echo commands and six Sphere-log
requests across the two installed APKs succeeded and produced exactly 12 missing-
task warnings in their observation window. No Android settings or games changed.

The saved PostgreSQL/Redis regression exercises the actual result handler on a
different worker, including received, running and completed replies. Four RPC
cases and two timeout/duplicate cases fail before the fix: result callbacks open
SQL task sessions despite having no durable task. An early test edit also removed
a JSON import needed by an existing test; it was restored before the recorded
six-failure baseline. That harness failure is not counted as a product defect.

## Minimal fix and compatibility

The producer now generates `interactive_<uuid>` correlation IDs. This uses the
existing distinction between UUID tasks and prefixed control receipts. Publication
to the device-specific Redis response channel still occurs before task routing;
the same correlation ID survives immediate, late and repeated responses without
depending on a live HTTP waiter or an expiring Redis classification key.

No result warning is silenced. A genuinely unknown task UUID still reaches the
existing tenant/device-scoped lookup, warns, and receives no durable ACK. Foreign
task results and failed PostgreSQL commits also receive no ACK. Interactive
responses do not claim durable storage and are not added to the Android DAG
journal. Existing Android command IDs are strings; no APK change is required.

Affected source: device REST router. Existing Android WS and TaskService result
handlers are unchanged. Regression source:
`tests/production/test_interactive_command_routing.py`.

## Validation and acceptance boundary

Six failing regressions precede the fix. **52 related tests passed**: real Redis
cross-worker RPC, offline and foreign-device rejection, reboot progress/timeout,
late duplicates with and without Redis, unknown UUID diagnostics, PostgreSQL
durable ACK/rollback/isolation, device diagnostics, deadline, cancellation and
Android WS handlers. [Evidence](evidence/interactive-identity-regression.json).

Backend `eacf692` is installed on the new pilot; frontend remains `03b161e` and
both APKs remain 1.2.7 / 10207. The same 12 native RPCs succeeded with **zero**
missing-task warnings, versus 12 before. Each APK then completed the existing
reviewed 13-node system-UI DAG with ordered native receipts and unchanged PID.
The two durable completions appear in the same container log window, positively
verifying collection rather than interpreting an empty log as success. Browser
polling displayed both new tasks and total 192 without reload. No active task or
pipeline remains. [Runtime evidence](evidence/interactive-identity-runtime.json).

The first rollout reverted on transient public-route readiness: the helper did
not retry `PublicationError`. Its bounded read-only retry now includes that
exception and still verifies the installation identity. The repeat deployment
preserved all other container IDs/images/start times/status/mounts and the OTA
catalog. The failed attempt remains recorded.

Local Ruff passed. Local mypy reported an existing inferred logcat-payload type
error, reproduced against the archived baseline router, plus existing full-tree
Windows/environment type errors. All GitHub source workflows passed, including
lint/mypy, backend unit/real-service tests, image bootstrap, Android and frontend.
[Exact source CI archive](evidence/ci-eacf692-summary.json).

Legacy interactive UUID replies already in flight may still emit a final warning
after rollout. Direct third-party command producers must use non-task IDs for RPC.
Interactive commands remain live-only and non-durable: loss after a side effect
can leave the caller with an unknown outcome. This fix does not introduce retries
or claim exactly-once execution, overnight stability or fleet capacity.
