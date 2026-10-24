package com.sphereplatform.agent.commands

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import io.mockk.*
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors

/** Android SQLite transactions/files, persisted preferences and real CommandJournal. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class CommandReceiptStoreTest {
    @get:Rule val folder = TemporaryFolder()
    private lateinit var prefs: SharedPreferences
    private lateinit var file: File
    private val stores = mutableListOf<CommandReceiptStore>()
    private fun store() = CommandReceiptStore(file, prefs).also { stores.add(it) }
    private fun journal(store: CommandReceiptStore): CommandJournal {
        val encrypted = mockk<EncryptedSharedPreferences>()
        every { encrypted.getString(any(), any()) } answers { prefs.getString(firstArg(), secondArg()) }
        every { encrypted.getStringSet(any(), any()) } answers { prefs.getStringSet(firstArg(), secondArg()) }
        every { encrypted.edit() } answers { prefs.edit() }
        return CommandJournal(encrypted, store)
    }

    @Before fun setup() {
        prefs = RuntimeEnvironment.getApplication().getSharedPreferences(UUID.randomUUID().toString(), Context.MODE_PRIVATE)
        file = File(folder.root, "receipts.db")
    }
    @After fun close() { stores.forEach { it.close() } }

    @Test fun thousandsOfAcknowledgementsRemainDeduplicatedOnDiskAfterRestart() {
        val firstStore = store()
        val first = journal(firstStore)
        repeat(2_048) {
            assertTrue(first.claim("task-$it") is CommandJournal.Claim.Started)
            first.complete("task-$it", if (it == 0) "failed" else "completed", "private error", null)
            first.acknowledge("task-$it")
        }
        firstStore.close()
        val reopened = store()
        val second = journal(reopened)
        assertEquals("failed", (second.claim("task-0") as CommandJournal.Claim.Existing).response["status"]!!.jsonPrimitive.content)
        assertEquals("completed", reopened.find("task-2047"))
        assertTrue(second.claim("next") is CommandJournal.Claim.Started)
        assertFalse(file.readBytes().toString(Charsets.ISO_8859_1).contains("private error"))
        assertTrue(file.length() < 1024 * 1024)
    }

    @Test fun transactionFailureRollsBackEveryImportedReceipt() {
        val db = store()
        assertThrows(IllegalArgumentException::class.java) { db.record(listOf(
            CommandReceiptStore.Receipt("first", "completed", 1),
            CommandReceiptStore.Receipt("bad", "running", 2),
        )) }
        db.close()
        assertNull(store().find("first"))
    }

    @Test fun retryDoesNotOverwriteOutcomeOrExtendRetention() {
        val db = store()
        db.record(listOf(CommandReceiptStore.Receipt("first", "failed", 100)))
        db.record(listOf(CommandReceiptStore.Receipt("first", "failed", 200)))
        assertThrows(IllegalStateException::class.java) {
            db.record(listOf(CommandReceiptStore.Receipt("first", "completed", 300)))
        }
        assertEquals("failed", db.find("first"))
        db.prune(CommandReceiptStore.RETENTION_MS + 101)
        assertNull(db.find("first"))
    }

    @Test fun pruningRetainsFullSevenDaysAndUsesAgeIndex() {
        val db = store()
        db.record(listOf(CommandReceiptStore.Receipt("expired", "completed", 99),
            CommandReceiptStore.Receipt("boundary", "completed", 100),
            CommandReceiptStore.Receipt("recent", "failed", 101)))
        db.prune(CommandReceiptStore.RETENTION_MS + 100)
        assertNull(db.find("expired"))
        assertEquals("completed", db.find("boundary"))
        assertEquals("failed", db.find("recent"))
    }

    @Test fun missingDatabaseDoesNotSilentlyResetReplayProtection() {
        val db = store()
        db.record(listOf(CommandReceiptStore.Receipt("first", "completed", 1)))
        db.close()
        assertTrue(file.delete())
        val failure = assertThrows(IllegalStateException::class.java) { journal(store()).claim("first") }
        assertEquals("command_receipts_database_missing", failure.message)
        assertFalse(file.exists())
    }

    @Test fun corruptDatabaseIsPreservedAndPreventsExecution() {
        store().find("first")
        stores.last().close()
        val corrupt = "deliberately corrupt SQLite fixture".toByteArray()
        file.writeBytes(corrupt)
        assertThrows(Exception::class.java) { journal(store()).claim("new-task") }
        assertArrayEquals(corrupt, file.readBytes())
    }

    @Test fun wrongDatabaseIdentityPreventsExecution() {
        store().find("first")
        stores.last().close()
        prefs.edit().putString(CommandReceiptStore.IDENTITY_KEY, "different-database").commit()
        val failure = assertThrows(IllegalStateException::class.java) { journal(store()).claim("new-task") }
        assertEquals("command_receipts_database_identity_mismatch", failure.message)
    }

    @Test fun identityWriteFailureClosesDatabaseAndCanRecover() {
        val unwritable = mockk<SharedPreferences>()
        val editor = mockk<SharedPreferences.Editor>()
        every { unwritable.getString(any(), any()) } returns null
        every { unwritable.edit() } returns editor
        every { editor.putString(any(), any()) } returns editor
        every { editor.commit() } returns false
        val db = CommandReceiptStore(file, unwritable).also { stores.add(it) }
        assertThrows(IllegalStateException::class.java) { db.find("first") }
        assertNull(store().find("first"))
        assertNotNull(prefs.getString(CommandReceiptStore.IDENTITY_KEY, null))
    }

    @Test fun concurrentDeliveryAdmitsOneExecution() {
        val first = journal(store())
        val executor = Executors.newFixedThreadPool(8)
        try {
            val futures = (1..32).map { executor.submit<CommandJournal.Claim> { first.claim("one-task") } }
            assertEquals(1, futures.count { it.get() is CommandJournal.Claim.Started })
            first.complete("one-task", "completed", null, null)
            first.acknowledge("one-task")
            assertTrue(journal(store()).claim("one-task") is CommandJournal.Claim.Existing)
        } finally { executor.shutdownNow() }
    }
}
