package com.sphereplatform.agent.commands

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import io.mockk.*
import org.junit.Assert.assertTrue
import org.junit.Test

/** Audit reproduction, outside the passing suite until the capacity design is fixed.
 * Copy into the commands test package and run this class through Gradle.
 * No APK/device/network actions; actual CommandJournal with an in-memory prefs adapter.
 */
class AuditAcknowledgedCapacityProbeTest {
    @Test fun acknowledgedTasksMustNotBlockTheNextFarmTask() {
        var disk: String? = null
        var staged: String? = null
        val prefs = mockk<EncryptedSharedPreferences>(relaxed = true)
        val editor = mockk<SharedPreferences.Editor>(relaxed = true)
        every { prefs.getString(any(), any()) } answers { disk }
        every { prefs.edit() } returns editor
        every { editor.putString(any(), any()) } answers { staged = secondArg(); editor }
        every { editor.commit() } answers { disk = staged; true }
        val journal = CommandJournal(prefs)
        repeat(512) {
            val id = "acknowledged-$it"
            assertTrue(journal.claim(id) is CommandJournal.Claim.Started)
            journal.complete(id, "completed", null, null)
            journal.acknowledge(id)
        }
        assertTrue(CommandJournal(prefs).claim("next-task-after-512-acks") is CommandJournal.Claim.Started)
    }
}
