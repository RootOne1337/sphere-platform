# AUD-119 · APK must keep accepting work after 512 acknowledgements

**Severity: High · operational availability and replay protection.**

## Reproduction and root cause

The real `CommandJournal` in APK 1.2.5 retains every acknowledged command in the
same encrypted JSON map as running and unacknowledged commands. Its 512-entry
admission limit therefore rejects the next command with
`command_journal_capacity_exhausted` after 512 successful acknowledgements.
Restarting the APK reloads the same full map. The limit is reached even with a
healthy server and no undelivered results; a two-minute task cadence reaches it
in about 17 hours. The earlier 2 h 35 min run could not expose this limit.

The [original failing probe](probes/AuditAcknowledgedCapacityProbeTest.kt) is a
historical reproduction against the old one-argument constructor, deliberately
outside the standard test source set. The maintained regression now lives in
`CommandJournalTest.acknowledgedTasksDoNotExhaustCapacityAndOldDuplicatesSurviveRestart`.

## Fix and storage contract

- Keep only running/unacknowledged records in the existing encrypted preferences.
  Preserve the 512 pending-entry, 1 MiB serialized journal and 64 KiB result limits.
  A server outage with an exhausted pending buffer still rejects new work; it
  never discards an unacknowledged result to make room.
- Store acknowledged command IDs, terminal status and acknowledgement timestamp
  in an indexed SQLite database under the application's `noBackupFilesDir`.
  No command output, error text or credential enters that database. Duplicate
  acknowledged commands receive the stored status; full evidence is already
  committed on the server that sent the acknowledgement.
- Retain compact receipts for at least seven days **after acknowledgement**.
  Age-index cleanup runs at most hourly on admission. Lookups do not load seven
  days of history into memory. Rows have no arbitrary 512-entry ceiling; disk
  usage depends on task rate, and expired pages can be reused by SQLite.
- Commit the SQLite receipt before removing the encrypted pending record.
  Retry after a crash between commits sees both copies. Historical acknowledged
  records migrate in one SQLite transaction before the old map is compacted.
  Pending and ambiguous running records retain their previous semantics.
- Bind the database identity to encrypted preferences. Missing/replaced/corrupt
  storage fails closed; the default Android corruption handler that deletes the
  database is replaced. No command executes on an assumed empty replacement.
- `DagRunner`'s compatibility flush uses the same injected singleton journal as
  `CommandDispatcher`, rather than constructing a separate snapshot.

SQLite uses synchronous full commits and transactions. Platform API references:
[SQLiteDatabase](https://developer.android.com/reference/android/database/sqlite/SQLiteDatabase),
[DatabaseErrorHandler](https://developer.android.com/reference/android/database/DatabaseErrorHandler).

## Affected files and regression coverage

- `android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandJournal.kt`: admission, ACK compaction and migration.
- `android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandReceiptStore.kt`: indexed durable receipt storage.
- `android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt`: shared journal identity.
- `CommandJournalTest`: 2,048 ACKs plus restart/old failed duplicate; full v1
  migration; failure before/between store commits; 512 retained pending results;
  one ACK frees exactly one slot; corrupted legacy journal; ambiguous execution.
- `CommandReceiptStoreTest`: actual Android SQLite under Robolectric, 2,048
  journal cycles and reopen, transaction rollback, conflicting outcomes,
  seven-day boundary, missing/corrupt/replaced database, identity write failure,
  concurrent duplicate admission, and exclusion of private error text from SQLite.
- `CommandDeliveryTest.failedAcknowledgementWriteKeepsResultAndDoesNotCrashApplicationScope`:
  an injected ACK write failure escaped the launch coroutine before the fix (one
  failed test). `CommandDispatcher` now catches that storage exception, retains
  the result, and accepts a later ACK without crashing the application.
- Dispatcher and DAG regressions continue to cover command delivery and execution.
- [JournalStorageProbe.java](../../../scripts/pilot/android/JournalStorageProbe.java)
  is a separate native Android acceptance probe using a fresh UUID-named encrypted
  preferences file, keystore alias and SQLite database. It migrates 512 ACKs,
  commits 2,048 more, reopens storage, checks duplicates and a retained pending
  result, then removes only its own fixture. It performs no device actions.
  It is not part of the APK or normal boot path.

## Acceptance and residual risk

**Source acceptance:** 577 dev tests pass; enterprise has 576 passed and one
existing baked-route fixture skipped because that build has no baked server/key.
Both flavors have 43 suites and zero failures/errors. The ACK failure probe fails
before containment and passes in the full run after the fix.
[Machine-readable results](evidence/android-journal-capacity-regression.json).
Installed-device acceptance is recorded separately; it is still pending at this
source checkpoint. Do not infer a completed overnight/fleet test from a
successful build or a small number of real tasks.

The seven-day deduplication window is finite; delayed redelivery after expiry
still requires the server's task lifecycle and TTL checks. Loss of application
data, forced APK downgrade or restoration of inconsistent app storage is not a
supported recovery procedure. Do not downgrade to an APK that lacks this receipt
store; use a forward version for rollback fixes. Rooted users can erase both
stores, which no application-local journal can prevent.

Disk exhaustion blocks new execution instead of risking duplicate side effects.
Clock jumps can affect time-based retention. Rate/fleet disk, energy and sustained
latency acceptance still require a measured representative workload. This change
does not add a second independent ingress, prove eight-hour uptime, or fix Task
Engine's incomplete history (AUD-120).
