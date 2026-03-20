package com.sphereplatform.agent.workers

import android.content.Context
import android.content.SharedPreferences
import androidx.work.ListenableWorker
import androidx.work.WorkerParameters
import com.sphereplatform.agent.provisioning.DeviceRegistrationClient
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.store.AuthTokenStore
import io.mockk.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Тесты KeepAliveWorker — периодический watchdog для гарантированного автостарта.
 *
 * Покрытие:
 *  - enrolled + token → Result.success()
 *  - enrolled + no token → попытка enrollment (невалидное состояние)
 *  - not enrolled + config found + apiKey → enrollment + Result.success()
 *  - not enrolled + no config → Result.success() (повторит через 15 мин)
 *  - enrollment exception → Result.success() (не failure, чтобы periodic не отменился)
 */
class KeepAliveWorkerTest {

    private lateinit var context: Context
    private lateinit var params: WorkerParameters
    private lateinit var provisioner: ZeroTouchProvisioner
    private lateinit var registrationClient: DeviceRegistrationClient
    private lateinit var authStore: AuthTokenStore
    private lateinit var watchdogPrefs: SharedPreferences
    private lateinit var watchdogEditor: SharedPreferences.Editor

    private val enrolledStorage = mutableMapOf<String, Any?>()

    @Before
    fun setUp() {
        context = mockk(relaxed = true)
        params = mockk(relaxed = true)
        provisioner = mockk(relaxed = true)
        registrationClient = mockk(relaxed = true)
        authStore = mockk(relaxed = true)

        // Мокаем SharedPreferences для ServiceWatchdog.isEnrolled()
        watchdogEditor = mockk(relaxed = true) {
            every { putBoolean(any(), any()) } answers {
                enrolledStorage[firstArg()] = secondArg<Boolean>()
                this@mockk
            }
        }
        watchdogPrefs = mockk(relaxed = true) {
            every { getBoolean("enrolled", false) } answers {
                enrolledStorage["enrolled"] as? Boolean ?: false
            }
            every { edit() } returns watchdogEditor
        }

        // Device Protected Storage (DE) — основное хранилище enrolled-флага после фикса
        val deContext = mockk<Context>(relaxed = true)
        every { deContext.getSharedPreferences("sphere_watchdog", Context.MODE_PRIVATE) } returns watchdogPrefs
        every { context.createDeviceProtectedStorageContext() } returns deContext

        // Credential Encrypted (CE) — fallback для обратной совместимости
        every { context.getSharedPreferences("sphere_watchdog", Context.MODE_PRIVATE) } returns watchdogPrefs
        every { context.applicationContext } returns context
    }

    private fun createWorker(): KeepAliveWorker {
        return KeepAliveWorker(context, params, provisioner, registrationClient, authStore)
    }

    // ── Сценарий 1: enrolled + token → запуск сервиса → success ──────────

    @Test
    fun `enrolled with token returns success`() = runTest {
        enrolledStorage["enrolled"] = true
        every { authStore.getToken() } returns "valid_token"

        val worker = createWorker()
        val result = worker.doWork()

        assertEquals(ListenableWorker.Result.success(), result)
    }

    // ── Сценарий 2: enrolled without token → пытается enrollment ─────────

    @Test
    fun `enrolled without token tries enrollment`() = runTest {
        enrolledStorage["enrolled"] = true
        every { authStore.getToken() } returns null
        every { provisioner.discoverConfig() } returns null

        val worker = createWorker()
        val result = worker.doWork()

        assertEquals(ListenableWorker.Result.success(), result)
        // discoverConfig вызван (попытка enrollment)
        verify { provisioner.discoverConfig() }
    }

    // ── Сценарий 3: not enrolled + apiKey config → enrollment ────────────

    @Test
    fun `not enrolled with config enrolls successfully`() = runTest {
        enrolledStorage["enrolled"] = false
        every { authStore.getToken() } returns null
        every { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(
            serverUrl = "http://test-server:8000",
            apiKey = "test_api_key",
            deviceId = "test-device-1",
            source = "buildconfig:dev",
        )

        val worker = createWorker()
        val result = worker.doWork()

        assertEquals(ListenableWorker.Result.success(), result)
        // Проверяем что enrollment прошёл
        verify { authStore.saveServerUrl("http://test-server:8000") }
        verify { authStore.saveApiKey("test_api_key") }
        verify { authStore.saveDeviceId("test-device-1") }
    }

    // ── Сценарий 4: not enrolled + no config → success (повторит позже) ──

    @Test
    fun `not enrolled without config returns success`() = runTest {
        enrolledStorage["enrolled"] = false
        every { authStore.getToken() } returns null
        every { provisioner.discoverConfig() } returns null

        val worker = createWorker()
        val result = worker.doWork()

        assertEquals(ListenableWorker.Result.success(), result)
        // НЕ пытается enrollment
        verify(exactly = 0) { authStore.saveApiKey(any()) }
    }

    // ── Сценарий 5: enrollment exception → success (не failure!) ─────────

    @Test
    fun `enrollment exception still returns success`() = runTest {
        enrolledStorage["enrolled"] = false
        every { authStore.getToken() } returns null
        every { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(
            serverUrl = "http://unreachable:8000",
            apiKey = "key",
            source = "test",
        )
        every { authStore.saveServerUrl(any()) } throws RuntimeException("Сеть недоступна")

        val worker = createWorker()
        val result = worker.doWork()

        // КРИТИЧНО: PeriodicWork НИКОГДА не должен возвращать failure(),
        // иначе WorkManager отменит всю периодическую задачу!
        assertEquals(ListenableWorker.Result.success(), result)
    }

    // ── Сценарий 6: auto-register config (apiKey пустой) → server config ─

    @Test
    fun `auto register with enrollment key from server`() = runTest {
        enrolledStorage["enrolled"] = false
        every { authStore.getToken() } returns null
        every { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(
            serverUrl = "http://test-server:8000",
            apiKey = "",
            source = "config_endpoint",
            autoRegisterEnabled = true,
        )
        every { provisioner.fetchServerConfig() } returns ZeroTouchProvisioner.ServerConfig(
            serverUrl = "http://test-server:8000",
            environment = "dev",
            autoRegister = true,
            enrollmentAllowed = true,
            enrollmentApiKey = "enroll_key_123",
            wsPath = "/ws/android",
            configPollIntervalSeconds = 86400,
        )
        coEvery { registrationClient.register(any(), any()) } returns mockk(relaxed = true)

        val worker = createWorker()
        val result = worker.doWork()

        assertEquals(ListenableWorker.Result.success(), result)
        coVerify { registrationClient.register("http://test-server:8000", "enroll_key_123") }
    }

    // ── Сценарий 7: autoRegister + apiKey → static save + register() upgrade ──

    @Test
    fun `auto register with apiKey saves static then upgrades via register`() = runTest {
        enrolledStorage["enrolled"] = false
        every { authStore.getToken() } returns null
        every { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(
            serverUrl = "https://sphere.example.com",
            apiKey = "sphr_dev_enrollment_key_2025",
            source = "config_endpoint",
            autoRegisterEnabled = true,
        )
        coEvery { registrationClient.register(any(), any()) } returns mockk(relaxed = true)

        val worker = createWorker()
        val result = worker.doWork()

        assertEquals(ListenableWorker.Result.success(), result)
        // Static key saved FIRST (baseline)
        verify { authStore.saveServerUrl("https://sphere.example.com") }
        verify { authStore.saveApiKey("sphr_dev_enrollment_key_2025") }
        // Then register() called for UUID upgrade
        coVerify { registrationClient.register("https://sphere.example.com", "sphr_dev_enrollment_key_2025") }
    }

    // ── Сценарий 8: autoRegister + apiKey, register() fails → static key preserved ──

    @Test
    fun `auto register upgrade failure preserves static key`() = runTest {
        enrolledStorage["enrolled"] = false
        every { authStore.getToken() } returns null
        every { provisioner.discoverConfig() } returns ZeroTouchProvisioner.ProvisionConfig(
            serverUrl = "https://sphere.example.com",
            apiKey = "sphr_dev_enrollment_key_2025",
            source = "file:/sdcard/sphere-agent-config.json",
            autoRegisterEnabled = true,
        )
        coEvery { registrationClient.register(any(), any()) } throws RuntimeException("Server unreachable")

        val worker = createWorker()
        val result = worker.doWork()

        // Enrollment still succeeds (static key saved even though register failed)
        assertEquals(ListenableWorker.Result.success(), result)
        verify { authStore.saveServerUrl("https://sphere.example.com") }
        verify { authStore.saveApiKey("sphr_dev_enrollment_key_2025") }
    }
}
