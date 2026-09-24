package com.sphereplatform.agent.commands

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import io.mockk.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class CommandJournalTest {
    @Test fun oversizedCancelledResultStillCarriesPhysicalStopConfirmation() {
        val instance = journal()
        instance.claim("large-cancelled")
        val terminal = instance.complete("large-cancelled", "failed", null, buildJsonObject {
            put("success", false); put("cancelled", true); put("output", "x".repeat(100_000))
        })
        assertTrue(terminal["result"]!!.jsonObject["cancelled"]!!.jsonPrimitive.boolean)
        assertTrue(terminal["result"]!!.jsonObject["result_truncated"]!!.jsonPrimitive.boolean)
        assertEquals(terminal, journal().pending().single())
    }
    @Test fun durableCancelBeforeDeliverySurvivesRestartAndBlocksExecution() {
        val terminal = journal().requestCancellation("task-1")!!
        assertTrue(terminal["result"]!!.jsonObject["cancelled"]!!.jsonPrimitive.boolean)
        val restarted = journal()
        assertEquals(terminal, (restarted.claim("task-1") as CommandJournal.Claim.Existing).response)
        assertEquals(terminal, restarted.pending().single())
        restarted.acknowledge("task-1")
        assertTrue(journal().claim("task-1") is CommandJournal.Claim.Existing)
    }

    @Test fun cancelDuringClaimDoesNotForgeATerminalReceipt() {
        val journal = journal()
        journal.claim("task-1")
        assertNull(journal.requestCancellation("task-1"))
        assertTrue(journal.isCancellationRequested("task-1"))
        assertEquals("running", (journal.claim("task-1") as CommandJournal.Claim.Existing).response["status"]!!.jsonPrimitive.content)
        val recovered = journal().pending().single()
        assertEquals("execution_outcome_unknown_after_restart", recovered["error"]!!.jsonPrimitive.content)
        assertNull(recovered["result"])
    }

    @Test fun cancellationCannotReplaceACompletedOutcomeOrCancelAnotherActiveTask() {
        val journal = journal()
        journal.claim("old")
        val done = journal.complete("old", "completed", null, null)
        journal.claim("current")
        assertEquals(done, journal.requestCancellation("old"))
        assertNotNull(journal.requestCancellation("future"))
        assertFalse(journal.isCancellationRequested("current"))
    }

    @Test fun cancellationWriteFailureDoesNotAcknowledgeOrForgetExecution() {
        val journal = journal()
        journal.claim("task-1")
        writable = false
        assertThrows(IllegalStateException::class.java) { journal.requestCancellation("task-1") }
        assertFalse(journal.isCancellationRequested("task-1"))
    }
    private val disk = mutableMapOf<String, String?>()
    private var writable = true
    private var legacy = emptySet<String>()
    private val receipts = ReceiptStoreFixture()
    private fun journal(): CommandJournal {
        val prefs = mockk<EncryptedSharedPreferences>(relaxed = true)
        val editor = mockk<SharedPreferences.Editor>(relaxed = true)
        val staged = mutableMapOf<String, String?>()
        var stagedLegacy: Set<String>? = null
        every { prefs.getString(any(), any()) } answers { disk[firstArg()] }
        every { prefs.getStringSet(any(), any()) } answers { legacy }
        every { prefs.edit() } answers { staged.clear(); stagedLegacy = null; editor }
        every { editor.putString(any(), any()) } answers { staged[firstArg()] = secondArg(); editor }
        every { editor.putStringSet(any(), any()) } answers { stagedLegacy = secondArg(); editor }
        every { editor.commit() } answers {
            if (writable) { disk.putAll(staged); stagedLegacy?.let { legacy = it } }
            writable
        }
        return CommandJournal(prefs, receipts.store)
    }

    @Test fun restartDoesNotRepeatAnAmbiguousExecution() {
        journal().claim("task-1")
        val restarted = journal()
        val result = (restarted.claim("task-1") as CommandJournal.Claim.Existing).response
        assertEquals("failed", result["status"]?.jsonPrimitive?.content)
        assertEquals("execution_outcome_unknown_after_restart", result["error"]?.jsonPrimitive?.content)
    }

    @Test fun interruptedOtaInstallIsCompletedAfterNewVersionStarts() {
        journal().claim("ota-command", acknowledgeWhenQueued = true, otaTargetVersionCode = 10220)

        val restarted = journal()
        restarted.reconcileCompletedOtaInstalls(installedVersionCode = 10220)

        val receipt = restarted.pending().single()
        assertEquals("completed", receipt["status"]?.jsonPrimitive?.content)
        assertEquals(10220, receipt["result"]?.jsonObject?.get("installed_version_code")?.jsonPrimitive?.int)
        assertEquals(receipt, (restarted.claim(
            "ota-command", acknowledgeWhenQueued = true, otaTargetVersionCode = 10220,
        ) as CommandJournal.Claim.Existing).response)
    }

    @Test fun interruptedOtaInstallIsNeverReportedSuccessfulAtOldVersion() {
        journal().claim("ota-command", acknowledgeWhenQueued = true, otaTargetVersionCode = 10220)

        val restarted = journal()
        restarted.reconcileCompletedOtaInstalls(installedVersionCode = 10219)

        val receipt = restarted.pending().single()
        assertEquals("failed", receipt["status"]?.jsonPrimitive?.content)
        assertEquals("execution_outcome_unknown_after_restart", receipt["error"]?.jsonPrimitive?.content)
    }

    @Test fun pendingResultSurvivesRestartAndFailedDeliveryUntilServerReceipt() {
        val first = journal()
        first.claim("task-1")
        first.complete("task-1", "failed", "fixture failure", null)
        val restarted = journal()
        repeat(3) { assertEquals(1, restarted.pending().size) }
        restarted.acknowledge("task-1")
        assertTrue(journal().pending().isEmpty())
        assertTrue(journal().claim("task-1") is CommandJournal.Claim.Existing)
    }

    @Test fun writeFailurePreventsExecutionReceipt() {
        writable = false
        assertThrows(IllegalStateException::class.java) { journal().claim("task-1") }
        assertTrue(disk.isEmpty())
    }

    @Test fun lateReceiptCannotAcknowledgeAnActiveTask() {
        val journal = journal()
        journal.claim("task-1")
        journal.acknowledge("task-1")
        journal.complete("task-1", "completed", null, null)
        assertEquals(1, journal.pending().size)
    }

    @Test fun oversizedResultIsKeptAsValidBoundedJson() {
        val journal = journal()
        journal.claim("task-1")
        journal.complete("task-1", "completed", null, buildJsonObject { put("output", "x".repeat(100_000)) })
        val pending = journal().pending().single()
        assertTrue(pending["result"]!!.jsonObject["result_truncated"]!!.jsonPrimitive.boolean)
        assertTrue(pending.toString().length < 1000)
    }

    @Test fun unknownRunningReceiptsAreReportedAfterReconnectWithoutRedelivery() {
        journal().claim("task-1")
        assertEquals("failed", journal().pending().single()["status"]!!.jsonPrimitive.content)
    }

    @Test fun capacityDoesNotEvictUnacknowledgedResults() {
        val journal = journal()
        repeat(512) { journal.claim("task-$it"); journal.complete("task-$it", "completed", null, null) }
        assertThrows(IllegalStateException::class.java) { journal.claim("overflow") }
        assertEquals(512, journal().pending().size)
    }

    @Test fun legacyFailedResultMigratesWithoutLossOrSuccessPromotion() {
        legacy = setOf("""{"command_id":"old-task","result":{"success":false}}""")
        val pending = journal().pending().single()
        assertEquals("failed", pending["status"]!!.jsonPrimitive.content)
        assertTrue(legacy.isEmpty())
        assertEquals(pending, journal().pending().single())
    }

    @Test fun failedMigrationKeepsLegacyEvidence() {
        legacy = setOf("""{"command_id":"old-task","result":{"success":true}}""")
        writable = false
        journal().pending()
        assertEquals(1, legacy.size)
        assertTrue(disk.isEmpty())
    }

    @Test fun acknowledgedTasksDoNotExhaustCapacityAndOldDuplicatesSurviveRestart() {
        val first = journal()
        repeat(2_048) {
            val id = "ack-$it"
            assertTrue(first.claim(id) is CommandJournal.Claim.Started)
            first.complete(id, if (it == 0) "failed" else "completed", null, null)
            first.acknowledge(id)
        }
        val restarted = journal()
        assertEquals("failed", (restarted.claim("ack-0") as CommandJournal.Claim.Existing).response["status"]!!.jsonPrimitive.content)
        assertTrue(restarted.pending().isEmpty())
        assertTrue(restarted.claim("new-task") is CommandJournal.Claim.Started)
        assertTrue(disk.getValue("command_journal_v1")!!.length < 100)
    }

    private fun seedAcknowledgedV1() {
        disk["command_journal_v1"] = buildJsonObject {
            repeat(512) { n -> put("old-$n", buildJsonObject {
                put("created_at", System.currentTimeMillis())
                put("acknowledged", true)
                put("response", buildJsonObject { put("status", if (n == 0) "failed" else "completed") })
            }) }
        }.toString()
    }

    @Test fun fullOldJournalMigratesAndStillRejectsDuplicates() {
        seedAcknowledgedV1()
        val first = journal()
        assertTrue(first.claim("new-task") is CommandJournal.Claim.Started)
        assertEquals(512, receipts.rows.size)
        assertEquals("failed", (journal().claim("old-0") as CommandJournal.Claim.Existing).response["status"]!!.jsonPrimitive.content)
        assertEquals("execution_outcome_unknown_after_restart", journal().pending().single()["error"]!!.jsonPrimitive.content)
    }

    @Test fun failedReceiptMigrationLeavesAllOldEvidenceAndAdmitsNoTask() {
        seedAcknowledgedV1()
        val before = disk.toMap()
        receipts.writable = false
        assertThrows(IllegalStateException::class.java) { journal().claim("new-task") }
        assertEquals(before, disk)
        receipts.writable = true
        assertTrue(journal().claim("new-task") is CommandJournal.Claim.Started)
    }

    @Test fun migrationInterruptedBetweenStoresCanResumeWithoutReplay() {
        seedAcknowledgedV1()
        val before = disk.toMap()
        writable = false
        assertThrows(IllegalStateException::class.java) { journal().claim("new-task") }
        assertEquals(before, disk)
        assertEquals(512, receipts.rows.size)
        writable = true
        assertTrue(journal().claim("old-0") is CommandJournal.Claim.Existing)
        assertTrue(journal().claim("new-task") is CommandJournal.Claim.Started)
    }

    @Test fun failedAckStorageNeverDiscardsPendingResults() {
        val first = journal()
        first.claim("task")
        val result = first.complete("task", "failed", "original error", null)
        receipts.writable = false
        assertThrows(IllegalStateException::class.java) { first.acknowledge("task") }
        assertEquals(result, journal().pending().single())
        receipts.writable = true
        writable = false
        assertThrows(IllegalStateException::class.java) { first.acknowledge("task") }
        assertEquals(result, journal().pending().single())
        writable = true
        journal().acknowledge("task")
        assertTrue(journal().pending().isEmpty())
        assertTrue(journal().claim("task") is CommandJournal.Claim.Existing)
    }

    @Test fun acknowledgingOneOf512PendingResultsReleasesOneSlotOnly() {
        val first = journal()
        repeat(512) { first.claim("task-$it"); first.complete("task-$it", "completed", null, null) }
        first.acknowledge("task-0")
        assertTrue(first.claim("new-task") is CommandJournal.Claim.Started)
        first.complete("new-task", "completed", null, null)
        assertThrows(IllegalStateException::class.java) { first.claim("overflow") }
        assertEquals(512, journal().pending().size)
        assertTrue(journal().claim("task-0") is CommandJournal.Claim.Existing)
    }

    @Test fun malformedOldJournalFailsClosed() {
        disk["command_journal_v1"] = "broken json"
        assertThrows(Exception::class.java) { journal() }
        assertEquals("broken json", disk["command_journal_v1"])
    }
}
