# DAG control identity and cancellation limits

**20 September update (AUD-129, source only):** stop persists cancellation in SQL.
QUEUED can finish locally (HTTP200); ASSIGNED/RUNNING return HTTP202 and remain
active until a terminal DAG receipt. Network failure does not discard the intent.
This supersedes AUD-128's temporary HTTP503 contract. It is not yet installed on
the pilot. [Evidence and rollout](../audits/2026-09-20/DURABLE-CANCELLATION.md).

The management WebSocket uses two identities for a DAG control:

```json
{
  "type": "CANCEL_DAG",
  "command_id": "user_cancel_22222222-2222-4222-8222-222222222222",
  "signed_at": 1788717000,
  "ttl_seconds": 30,
  "payload": {"task_id": "22222222-2222-4222-8222-222222222222", "durable": true}
}
```

`payload.task_id` identifies the execution to control. `command_id` identifies
the control receipt and must not be a task UUID. The current server result
handler persists UUID command results as DAG outcomes; reusing the task ID for
stop could falsely complete a task if cancellation rolled back after delivery.
User stop, scheduler stop and watchdog stop use prefixed control IDs. The
timestamp above is illustrative; senders generate a fresh timestamp.

Live shell/logcat/reboot RPCs use `interactive_<uuid>` correlation IDs. They have
no SQL Task row and no durable `result_ack`. Replies still publish to the
device-specific Redis result channel before the existing non-task check. This
distinction survives a timed-out HTTP waiter and requires no Redis classification
cache. Bare UUIDs continue through task ownership/storage checks; unknown UUIDs
still warn. Legacy in-flight RPC UUIDs may warn once during rollout.
See [AUD-121 reproduction and limits](../audits/2026-09-05/INTERACTIVE-RESULT-IDENTITY.md).

The Android dispatcher requires a nonblank string target for CANCEL_DAG,
PAUSE_DAG and RESUME_DAG. It returns `invalid_task_target` for a missing/malformed
target. Legacy controls return `task_not_running` when that ID is not active.
Durable CANCEL_DAG first saves a journal fence: unseen tasks receive a cancelled
receipt without executing, active tasks stop cooperatively, terminal receipts are
replayed, interrupted executions report an unknown outcome. There is no fallback
to whichever DAG currently occupies the device.

DagRunner matches the target and changes its control flags under the same lock
used to establish and clear the active execution. Cleanup runs on success,
parse failure and coroutine failure. A late cancel/pause/resume for task A cannot
modify task B. An accepted control returns `completed` with
`result.control_accepted=true` and the target task ID. This is completion of the
control request, **not confirmation that device effects have stopped**.

Cancellation is cooperative. A checkpoint runs before each action/retry,
including nested loop bodies; pause waits at that boundary until resume or cancel.
A cancellation observed during the final action produces `success=false` with
`CANCELLED`/`cancelled_by_user` and `cancelled=true`; the dispatcher persists a failed
DAG wire receipt, which the backend stores as SQL CANCELLED.
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
before TaskBatch, and cancellation retains that order. QUEUED tasks receive a
UTC finished_at; ASSIGNED retains an active status with a cancel intent. RUNNING
tasks continue by the existing batch policy. CANCELLED batch stops wave admission;
it does not claim all already-running children have stopped.
Wave submission now keeps a batch active until device outcomes arrive and counts
admission failures under the result aggregation lock. It does not emit a false
completion webhook. Parent commit precedes worker launch. Producer/cancel share
a PostgreSQL transaction advisory lock before task/device row locks: cancellation
waits for in-flight admission, then sees its committed tasks; later waves re-read
tenant/status after waiting. Late results/timeouts keep CANCELLED while updating
counters. Producer crash recovery and durable outcome notifications remain open.
See AUD-43/AUD-45–47 and the batch cancellation/startup/wave outcome tests.

Scheduler cancellation locks eligible tenant Task/PipelineRun rows in stable ID
order and refreshes them before mutation. A concurrently committed terminal row
is excluded after the lock wait, with no queue/control effect for that row.
The latest execution lookup also retains the schedule organization. Stop signing
time is generated after waiting so a long SQL wait does not consume its TTL.
The scheduler saves cancellation intent instead of publishing in its transaction.
The dispatcher commits a bounded attempt lease before publishing; retries use the
same target/control ID with a fresh timestamp, at least five seconds apart.
Publish/control ACK never finishes a task. Pending cancellation blocks subsequent
dispatch and ordinary stale-task expiry. SQL rollback publishes nothing.

Pipeline cancellation locks Task before PipelineRun, fences child admission and
waits for terminal child/nested runs. A fresh executor reconciles saved cancellation
without replaying pipeline steps. UI exposes the pending intent instead of hiding
the still-active run. Parallel native task children are rejected before admission.

Remaining failure cases:

- A process/root outcome reported as unknown remains active for reconciliation;
  no automatic unlock or APK result ACK can discard that evidence.
- Ordinary watchdog timeout without a saved cancellation retains its older
  contract: TIMEOUT and best-effort stop do not prove physical termination.
- Legacy pipeline `action` publication has no native terminal task receipt;
  cancellation cannot withdraw an already-published action.
- Controls are not durably deduplicated or ordered within the same execution.
  A delayed resume for the same task may override a later pause. TTL is only an
  age bound, not an execution generation or ordering guarantee.
- Other pipeline writers, wave producer recovery, stale RUNNING reconciliation
  and post-commit effects remain open. A new task must not be treated as proof the old one has
  physically stopped.

## Rollout and verification

Pause new admission for coordinated rollout. Install and verify the APK journal
fence on canaries, apply both nullable-column migrations, then update every backend
worker and frontend. Existing 1.2.7 supports targeted controls but not the new
durable pre-arrival fence. Older legacy agents may ignore targets altogether.
Mixed workers/agents do not provide the complete contract. Do not downgrade away
pending intent columns before reconciling active work. Native fault acceptance
and 32-device capacity remain open; this change did not update pilot runtime.

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
