# DAG control identity and cancellation limits

The management WebSocket uses two identities for a DAG control:

```json
{
  "type": "CANCEL_DAG",
  "command_id": "user_cancel_22222222-2222-4222-8222-222222222222",
  "signed_at": 1788717000,
  "ttl_seconds": 30,
  "payload": {"task_id": "22222222-2222-4222-8222-222222222222"}
}
```

`payload.task_id` identifies the execution to control. `command_id` identifies
the control receipt and must not be a task UUID. The current server result
handler persists UUID command results as DAG outcomes; reusing the task ID for
stop could falsely complete a task if cancellation rolled back after delivery.
User stop, scheduler stop and watchdog stop use prefixed control IDs. The
timestamp above is illustrative; senders generate a fresh timestamp.

The Android dispatcher requires a nonblank string target for CANCEL_DAG,
PAUSE_DAG and RESUME_DAG. It returns `invalid_task_target` for a missing/malformed
target and `task_not_running` when that ID is not the active execution. There is
no implicit fallback to whichever DAG currently occupies the device.

DagRunner matches the target and changes its control flags under the same lock
used to establish and clear the active execution. Cleanup runs on success,
parse failure and coroutine failure. A late cancel/pause/resume for task A cannot
modify task B. An accepted control returns `completed` with
`result.control_accepted=true` and the target task ID. This is completion of the
control request, **not confirmation that device effects have stopped**.

Cancellation is cooperative. A checkpoint runs before each action/retry,
including nested loop bodies; pause waits at that boundary until resume or cancel.
A cancellation observed during the final action produces `success=false` with
`CANCELLED`/`cancelled_by_user`, so the dispatcher persists a failed DAG receipt.
The separate control ACK still records acceptance only. The current synchronous,
root or Lua action may continue until it returns. Checkpoint-to-action races are
possible; root pipe flushes do not prove execution or shell exit status. Pause
does not freeze node/global timeout budgets. Duplicate DAG delivery replays the
durable terminal receipt without restarting a cancelled scenario.

Coroutine cancellation from a suspended loop action now propagates out of the
body instead of becoming a recoverable action failure. A real runner regression
cancels a sleeping action and verifies that the following tap is never invoked.
This does not interrupt synchronous root execution or turn a wire control receipt
into a physical stop acknowledgement. Loop diagnostics retain at most 200 entries
without skipping subsequent actions; see AUD-40/41 in the audit report.

## Server transactions and remaining failure cases

TaskService cancel/force-stop lock and refresh the tenant-scoped task row before
checking its status. A concurrently completed/failed/timed-out task returns 409
without another queue or command effect. Ordinary GETs do not take this lock.

Batch DELETE authorizes the organization, locks QUEUED/ASSIGNED tasks in UUID
order, then locks/refreshes the batch. Only PENDING/RUNNING batches are mutable;
terminal batches return 409 before queue effects. Result writers acquire Task
before TaskBatch, and cancellation retains that order. Cancelled tasks receive a
UTC finished_at; RUNNING tasks continue. ASSIGNED may already be in transit.
Wave production has a separate lifecycle and still needs cancellation/status
recovery work. See AUD-43 and test_batch_cancellation.py for the proven boundary.

Scheduler cancellation locks eligible tenant Task/PipelineRun rows in stable ID
order and refreshes them before mutation. A concurrently committed terminal row
is excluded after the lock wait, with no queue/control effect for that row.
The latest execution lookup also retains the schedule organization. Stop signing
time is generated after waiting so a long SQL wait does not consume its TTL.
The scheduler still uses prefixed control IDs and explicit task targets.
Pipeline row cancellation does not itself stop an in-flight child task or fence
all executor writes. See AUD-44 and test_scheduler_cancellation.py.

These changes do not introduce a cancellation outbox. In particular:

- TaskService still sends the running stop before its caller commits. A failed
  commit can leave SQL RUNNING after the APK accepted cancellation. Distinct
  control IDs prevent a forged success outcome, but do not reconcile the states.
- Redis failure can still abort cancellation, and transport acceptance does not
  prove device receipt. Watchdog sends after timeout commit, without a durable
  retry/stop acknowledgement. The scheduler has its own cancellation path.
- A stop delivered before the DAG becomes active is rejected, not persisted as
  a future cancellation intent. ASSIGNED work may already be in transit.
- Controls are not durably deduplicated or ordered within the same execution.
  A delayed resume for the same task may override a later pause. TTL is only an
  age bound, not an execution generation or ordering guarantee.
- Other pipeline writers, wave producer recovery, stale RUNNING reconciliation
  and post-commit effects remain open. A new task must not be treated as proof the old one has
  physically stopped.

## Rollout and verification

Update all backend workers before adopting the Android target requirement: old
watchdogs send no `payload.task_id`, which the new APK rejects. Pause/resume
integrations must also send a target and a distinct control ID. Old APKs still
ignore the target, so delayed-control protection requires the APK update too.
Mixed versions do not provide the complete guarantee. No production rollout was
performed during this audit.

`ControlCommandTargetTest` exercises the real dispatcher, journal and DAG runner
through their WebSocket callback with virtual coroutine time and fake OS/storage.
It verifies delayed controls, valid cancellation/pause/resume, malformed targets
and active-state cleanup. Six additional cases cover loop/nested cancellation,
pause/resume within a body, cancellation while paused, final-action outcome,
retry backoff and replay of a cancelled task. PostgreSQL tests in `test_cancellation_commands.py`
deliver a real control ACK through the backend handler after injected Redis/SQL
failure; `test_cancellation_serialization.py` uses two concurrent DB sessions.
These are runtime logic tests, not physical-device stop or emulator capacity
measurements. See AUD-35–37 and AUD-40–44 in the [audit report](../audits/2026-09-05/AUDIT-REPORT.md).
