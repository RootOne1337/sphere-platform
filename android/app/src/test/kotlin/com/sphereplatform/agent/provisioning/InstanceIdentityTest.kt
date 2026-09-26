package com.sphereplatform.agent.provisioning

import android.content.Context
import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.IOException

/** Настоящие SharedPreferences и копирование их содержимого, а не тест SHA-256 сам по себе. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class InstanceIdentityTest {
    private val context: Context = org.robolectric.RuntimeEnvironment.getApplication()
    private val prefs get() = context.getSharedPreferences("instance-test", Context.MODE_PRIVATE)

    @Test fun copiedPreferencesWithSameCardButDifferentVmSerialGetDifferentBinding() {
        prefs.edit().clear().commit()
        val originalReader = InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { "ldplayer-vm-001" })
        val original = originalReader.read()
        val cloneReader = InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { "ldplayer-vm-002" })
        assertNotEquals(original, cloneReader.read())
        assertEquals(InstanceBindingReader.CURRENT_VERSION, cloneReader.version())
    }

    @Test fun bitwiseCloneWithSameCardAndSameVmSerialIsNotFalselyClaimedAsUnique() {
        prefs.edit().clear().commit()
        val original = InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { "same-hypervisor-id" }).read()
        val clone = InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { "same-hypervisor-id" }).read()
        assertEquals(original, clone)
    }

    @Test fun emulatorWithoutStableSerialFailsClosedInsteadOfUsingCopiedAndroidOrMacIdentity() {
        prefs.edit().clear().commit()
        val reader = InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { null })
        assertThrows(IOException::class.java) { reader.read() }
        assertNull(prefs.getString("source_v2", null))
    }

    @Test fun oldMacBasedV2MarkerMigratesToSerialInsteadOfKeepingAmbiguousBinding() {
        prefs.edit().clear().putString("source_v2", "emulator_eth0").commit()
        val serial = "ldplayer-vm-migration-001"
        val upgraded = InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { serial })

        val first = upgraded.read()
        assertEquals("emulator_serial", prefs.getString("source_v2", null))
        assertEquals(first, InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { serial }).read())
    }

    @Test fun emulatorWithSerialButNoReadyNetworkCanBindWithoutUsingBootId() {
        prefs.edit().clear().commit()
        val reader = InstanceBindingReader(prefs, { "copied-android-id" },
            isEmulator = true, virtualSerial = { "ldplayer-vm-003" })
        val first = reader.read()
        assertEquals("emulator_serial", prefs.getString("source_v2", null))
        assertEquals(first, reader.read())
    }

    @Test fun processRestartAndAndroidIdChangeKeepVirtualMachineBinding() {
        prefs.edit().clear().commit()
        val serial = { "ldplayer-vm-004" }
        val original = InstanceBindingReader(prefs, { "old-android-id" }, isEmulator = true,
            virtualSerial = serial).read()
        val restarted = InstanceBindingReader(prefs, { "new-android-id" }, isEmulator = true,
            virtualSerial = serial).read()
        assertEquals(original, restarted)
    }

    @Test fun temporarilyMissingSelectedCardDoesNotFallBackToAnotherIdentity() {
        prefs.edit().clear().commit()
        var serial: String? = "ldplayer-vm-005"
        val original = InstanceBindingReader(prefs, { "id" }, isEmulator = true,
            virtualSerial = { serial }).read()
        serial = null
        val reader = InstanceBindingReader(prefs, { "id" }, isEmulator = true,
            virtualSerial = { serial })
        assertThrows(IOException::class.java) { reader.read() }
        serial = "ldplayer-vm-005"
        assertEquals(original, reader.read())
    }

    @Test fun placeholderAndMalformedSerialsCannotBecomeEmulatorBinding() {
        for (serial in listOf(null, "unknown", "none", "00:00", "invalid value")) {
            assertNull(InstanceBindingReader.normalizeVirtualSerial(serial))
        }
    }

    @Test fun physicalFallbackDoesNotSwitchWhenAnotherNetworkAppears() {
        prefs.edit().clear().commit()
        val first = InstanceBindingReader(prefs, { "physical-android-id" }).read()
        val next = InstanceBindingReader(prefs, { "physical-android-id" }).read()
        assertEquals(first, next)
    }

    @Test fun emulatorWithoutStableSerialWaitsInsteadOfPersistingCopiedAndroidId() {
        prefs.edit().clear().commit()
        var serial: String? = null
        val reader = InstanceBindingReader(prefs, { "copied-id" }, isEmulator = true,
            virtualSerial = { serial })
        assertThrows(IOException::class.java) { reader.read() }
        assertNull(prefs.getString("source_v2", null))
        serial = "ldplayer-vm-006"
        assertEquals(64, reader.read().length)
        assertEquals("emulator_serial", prefs.getString("source_v2", null))
    }

    @Test fun storedTemplateFingerprintSurvivesChangedAndroidProperties() {
        context.getSharedPreferences("sphere_clone_detector", Context.MODE_PRIVATE).edit().clear().commit()
        android.provider.Settings.Secure.putString(context.contentResolver, "android_id", "before")
        val fingerprint = CloneDetector(context).getFingerprint()
        android.provider.Settings.Secure.putString(context.contentResolver, "android_id", "after")
        assertEquals(fingerprint, CloneDetector(context).getFingerprint())
    }

    @Test fun guardReenrollsCopiedIdentityAndSkipsLaterReconnects() = runBlocking {
        val store = mockk<AuthTokenStore>(relaxed = true)
        every { store.enrollmentMutex } returns kotlinx.coroutines.sync.Mutex()
        every { store.getDeviceId() } returns "old-device"
        every { store.getToken() } returns "copied-access"
        var savedVersion = 1
        every { store.getInstanceBindingVersion() } answers { savedVersion }
        var saved = "a".repeat(64)
        every { store.getInstanceBinding() } answers { saved }
        val binding = "b".repeat(64)
        val reader = mockk<InstanceBindingReader> {
            every { read() } returns binding
            every { version() } returns InstanceBindingReader.CURRENT_VERSION
        }
        val provisioner = mockk<ZeroTouchProvisioner> {
            coEvery { discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig("https://isolated.invalid", "enrollment")
        }
        val registration = mockk<DeviceRegistrationClient> {
            coEvery { register(any(), any(), any(), any(), any(), any(), any(), any()) } answers {
                saved = binding
                savedVersion = InstanceBindingReader.CURRENT_VERSION
                mockk(relaxed = true)
            }
        }
        val guard = InstanceRegistrationGuard(store, reader, provisioner, registration)
        guard.ensureRegistered()
        guard.ensureRegistered()
        coVerify(exactly = 1) {
            registration.register("https://isolated.invalid", "enrollment", null, null, null, null,
                binding, InstanceBindingReader.CURRENT_VERSION)
        }
        verify(exactly = 0) { store.clearTokens() }
    }

    @Test fun migrationOutageKeepsCredentialsForOtaButDoesNotApproveIdentity() = runBlocking {
        val store = mockk<AuthTokenStore>(relaxed = true)
        every { store.enrollmentMutex } returns kotlinx.coroutines.sync.Mutex()
        every { store.getInstanceBinding() } returns null
        val reader = mockk<InstanceBindingReader> {
            every { read() } returns "b".repeat(64)
            every { version() } returns InstanceBindingReader.CURRENT_VERSION
        }
        val provisioner = mockk<ZeroTouchProvisioner> { coEvery { discoverConfig() } returns null }
        val registration = mockk<DeviceRegistrationClient>()
        val guard = InstanceRegistrationGuard(store, reader, provisioner, registration)
        val result = runCatching { guard.ensureRegistered() }
        assertTrue(result.exceptionOrNull() is IOException)
        verify(exactly = 0) { store.clearTokens() }
        coVerify(exactly = 0) { registration.register(any(), any(), any(), any(), any(), any(), any(), any()) }
    }
}
