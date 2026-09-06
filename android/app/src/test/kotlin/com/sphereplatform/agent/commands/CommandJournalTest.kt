package com.sphereplatform.agent.commands

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import io.mockk.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class CommandJournalTest {
    private val disk = mutableMapOf<String, String?>()
    private var writable = true
    private var legacy = emptySet<String>()
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
        return CommandJournal(prefs)
    }

    @Test fun restartDoesNotRepeatAnAmbiguousExecution() {
        journal().claim("task-1")
        val restarted = journal()
        val result = (restarted.claim("task-1") as CommandJournal.Claim.Existing).response
        assertEquals("failed", result["status"]?.jsonPrimitive?.content)
        assertEquals("execution_outcome_unknown_after_restart", result["error"]?.jsonPrimitive?.content)
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
}
