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
    private val nic = "wlan0|0|00:db:00:00:00:01"

    @Test fun copiedPreferencesWithDifferentVirtualCardsGetDifferentBinding() {
        prefs.edit().clear().commit()
        val original = InstanceBindingReader(prefs, { nic }, { "copied-android-id" }).read()
        // Клон получает все сохранённые настройки, но другую виртуальную карту.
        val clone = InstanceBindingReader(prefs, { "wlan0|0|00:db:00:00:00:02" }, { "copied-android-id" }).read()
        assertNotEquals(original, clone)
    }

    @Test fun processRestartAndAndroidIdChangeKeepVirtualMachineBinding() {
        prefs.edit().clear().commit()
        val original = InstanceBindingReader(prefs, { nic }, { "old-android-id" }).read()
        val restarted = InstanceBindingReader(prefs, { nic }, { "new-android-id" }).read()
        assertEquals(original, restarted)
    }

    @Test fun temporarilyMissingSelectedCardDoesNotFallBackToAnotherIdentity() {
        prefs.edit().clear().commit()
        val original = InstanceBindingReader(prefs, { nic }, { "id" }).read()
        var snapshot = ""
        val reader = InstanceBindingReader(prefs, { snapshot }, { "id" })
        assertThrows(IOException::class.java) { reader.read() }
        snapshot = nic
        assertEquals(original, reader.read())
    }

    @Test fun randomizedAndPlaceholderAddressesCannotBecomeBinding() {
        assertTrue(InstanceBindingReader.parsePermanentAddresses("wlan0|3|00:db:00:00:00:01").isEmpty())
        for (mac in listOf("02:00:00:00:00:00", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:00:00:00:00:01")) {
            assertNull(InstanceBindingReader.normalizeAddress(mac))
        }
    }

    @Test fun physicalFallbackDoesNotSwitchWhenAnotherNetworkAppears() {
        prefs.edit().clear().commit()
        val first = InstanceBindingReader(prefs, { "" }, { "physical-android-id" }).read()
        val next = InstanceBindingReader(prefs, { nic }, { "physical-android-id" }).read()
        assertEquals(first, next)
    }

    @Test fun emulatorBootWithoutNetworkWaitsInsteadOfPersistingCopiedAndroidId() {
        prefs.edit().clear().commit()
        var snapshot = ""
        val reader = InstanceBindingReader(prefs, { snapshot }, { "copied-id" }, requireVirtualNic = true)
        assertThrows(IOException::class.java) { reader.read() }
        assertNull(prefs.getString("source_v1", null))
        snapshot = nic
        assertEquals(64, reader.read().length)
        assertEquals("wlan0", prefs.getString("source_v1", null))
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
        var saved = "a".repeat(64)
        every { store.getInstanceBinding() } answers { saved }
        val binding = "b".repeat(64)
        val reader = mockk<InstanceBindingReader> { every { read() } returns binding }
        val provisioner = mockk<ZeroTouchProvisioner> {
            coEvery { discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig("https://isolated.invalid", "enrollment")
        }
        val registration = mockk<DeviceRegistrationClient> {
            coEvery { register(any(), any(), any(), any(), any(), any(), any()) } answers {
                saved = binding
                mockk(relaxed = true)
            }
        }
        val guard = InstanceRegistrationGuard(store, reader, provisioner, registration)
        guard.ensureRegistered()
        guard.ensureRegistered()
        coVerify(exactly = 1) { registration.register("https://isolated.invalid", "enrollment", null, null, null, null, binding) }
        verify(exactly = 0) { store.clearTokens() }
    }

    @Test fun migrationOutageKeepsCredentialsForOtaButDoesNotApproveIdentity() = runBlocking {
        val store = mockk<AuthTokenStore>(relaxed = true)
        every { store.enrollmentMutex } returns kotlinx.coroutines.sync.Mutex()
        every { store.getInstanceBinding() } returns null
        val reader = mockk<InstanceBindingReader> { every { read() } returns "b".repeat(64) }
        val provisioner = mockk<ZeroTouchProvisioner> { coEvery { discoverConfig() } returns null }
        val registration = mockk<DeviceRegistrationClient>()
        val guard = InstanceRegistrationGuard(store, reader, provisioner, registration)
        val result = runCatching { guard.ensureRegistered() }
        assertTrue(result.exceptionOrNull() is IOException)
        verify(exactly = 0) { store.clearTokens() }
        coVerify(exactly = 0) { registration.register(any(), any(), any(), any(), any(), any(), any()) }
    }
}
