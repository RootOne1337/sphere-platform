package com.sphereplatform.agent.workers

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.sphereplatform.agent.provisioning.DeviceRegistrationClient
import com.sphereplatform.agent.provisioning.RegistrationException
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.service.ServiceWatchdog
import com.sphereplatform.agent.service.SphereAgentService
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import timber.log.Timber
import java.util.concurrent.TimeUnit

/**
 * KeepAliveWorker — периодический рабочий процесс для гарантированного автостарта агента.
 *
 * ЗАЧЕМ ЭТО НУЖНО:
 * На Android после установки APK приложение находится в «Stopped State» — все implicit
 * broadcast (включая BOOT_COMPLETED) заблокированы. BootReceiver НЕ срабатывает.
 * AlarmManager-алармы теряются при reboot. OneTimeWorkRequest не повторяется.
 *
 * KeepAliveWorker решает эту проблему:
 * - Планируется как [PeriodicWorkRequest] при ПЕРВОМ запуске приложения
 * - WorkManager хранит задачи в SQLite и использует системный [android.app.job.JobScheduler]
 *   с setPersisted(true) → задача ПЕРЕЖИВАЕТ reboot на уровне ОС
 * - JobScheduler НЕ проверяет FLAG_STOPPED → задача выполняется даже если приложение
 *   ни разу не получало BOOT_COMPLETED
 * - При каждом тике (15 мин) проверяет состояние агента и восстанавливает его
 *
 * ПЯТИСЛОЙНАЯ ЗАЩИТА:
 * 1. BOOT_COMPLETED → BootReceiver (стандартный путь, после снятия Stopped State)
 * 2. AlarmManager → ServiceWatchdog (каждые 5 мин, после enrollment)
 * 3. **KeepAliveWorker** → JobScheduler/WorkManager (каждые 15 мин, ВСЕГДА)
 * 4. START_STICKY → ОС перезапускает убитый foreground service
 * 5. AutoEnrollmentWorker → немедленная попытка enrollment при первом boot
 *
 * Тик выполняет одно из:
 * - enrolled + есть token → запускает [SphereAgentService]
 * - enrolled + нет token → сбрасывает enrollment, пытается заново
 * - не enrolled → пытается Zero-Touch enrollment через [ZeroTouchProvisioner]
 */
@HiltWorker
class KeepAliveWorker @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted params: WorkerParameters,
    private val provisioner: ZeroTouchProvisioner,
    private val registrationClient: DeviceRegistrationClient,
    private val authStore: AuthTokenStore,
) : CoroutineWorker(context, params) {

    companion object {
        private const val WORK_NAME = "sphere_keep_alive"

        /**
         * Планирует периодический watchdog-тик каждые 15 минут.
         *
         * Вызывается из:
         * - [com.sphereplatform.agent.SphereApp.onCreate] — при любом создании процесса
         * - [com.sphereplatform.agent.BootReceiver.onReceive] — при загрузке устройства
         *
         * KEEP policy: если задача уже запланирована — не дублирует.
         * Требует сеть (CONNECTED) — без сети enrollment невозможен.
         */
        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = PeriodicWorkRequestBuilder<KeepAliveWorker>(
                15, TimeUnit.MINUTES,
            ).setConstraints(constraints).build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
            Timber.i("KeepAliveWorker: запланирован (каждые 15 мин, setPersisted=true)")
        }
    }

    override suspend fun doWork(): Result {
        Timber.d("KeepAliveWorker: тик")

        val isEnrolled = ServiceWatchdog.isEnrolled(applicationContext)
        val hasToken = authStore.getToken() != null

        // ── Сценарий 1: Enrolled + есть токен → гарантируем работу сервиса ──
        if (isEnrolled && hasToken) {
            ensureServiceRunning()
            return Result.success()
        }

        // ── Сценарий 2: Enrolled но нет токена → невалидное состояние ──────
        // SharedPrefs injection через deploy-скрипт поставила enrolled=true,
        // но EncryptedSharedPreferences (AuthTokenStore) пуст → enrollment не завершён.
        // Сбрасываем enrolled и пробуем полный enrollment заново.
        if (isEnrolled && !hasToken) {
            Timber.w("KeepAliveWorker: enrolled=true, но токен отсутствует → пробуем enrollment заново")
        }

        // ── Сценарий 3: Не enrolled → Zero-Touch enrollment ────────────────
        return tryAutoEnrollment()
    }

    /**
     * Гарантирует что [SphereAgentService] запущен.
     * Вызов startForegroundService идемпотентен — если сервис уже работает, ничего не произойдёт.
     */
    private fun ensureServiceRunning() {
        try {
            SphereAgentService.start(applicationContext)
            ServiceWatchdog.schedule(applicationContext)
            Timber.d("KeepAliveWorker: сервис запущен/подтверждён, watchdog запланирован")
        } catch (e: Exception) {
            // Android 12+: ForegroundServiceStartNotAllowedException возможен
            // если WorkManager выполняет задачу в expedited/background context.
            // Не фатально — следующий тик через 15 мин повторит попытку.
            Timber.w(e, "KeepAliveWorker: не удалось запустить сервис — повторим через 15 мин")
        }
    }

    /**
     * Пытается пройти Zero-Touch enrollment.
     * Полностью повторяет логику [AutoEnrollmentWorker] но в контексте периодического тика.
     */
    private fun tryAutoEnrollment(): Result {
        val config = provisioner.discoverConfig()
        if (config == null) {
            Timber.d("KeepAliveWorker: конфигурация не найдена — повторим через 15 мин")
            return Result.success()
        }

        return try {
            if (config.autoRegisterEnabled && config.apiKey.isBlank()) {
                // Auto-register через серверный endpoint
                val serverConfig = provisioner.fetchServerConfig()
                val enrollmentKey = serverConfig?.enrollmentApiKey
                if (enrollmentKey == null) {
                    Timber.w("KeepAliveWorker: auto_register запрошен, но enrollment key не найден")
                    return Result.success()
                }
                Timber.i("KeepAliveWorker: авто-регистрация через ${config.serverUrl}")
                registrationClient.register(
                    serverUrl = config.serverUrl,
                    enrollmentApiKey = enrollmentKey,
                )
            } else if (config.apiKey.isNotBlank()) {
                // Статический API-ключ из конфига/BuildConfig
                Timber.i("KeepAliveWorker: enrollment со статическим API-ключом (${config.source})")
                authStore.saveServerUrl(config.serverUrl)
                config.deviceId?.let { authStore.saveDeviceId(it) }
                authStore.saveApiKey(config.apiKey)
            } else {
                Timber.d("KeepAliveWorker: конфиг без ключа и без auto_register")
                return Result.success()
            }

            // Enrollment успешен → активируем все защитные механизмы
            ServiceWatchdog.markEnrolled(applicationContext)
            ServiceWatchdog.schedule(applicationContext)
            ensureServiceRunning()

            Timber.i("KeepAliveWorker: enrollment успешен! Агент активирован.")
            Result.success()

        } catch (e: RegistrationException) {
            Timber.w("KeepAliveWorker: регистрация провалена: HTTP ${e.httpCode} — ${e.message}")
            // 4xx ошибки (кроме 429) — не ретраим в рамках этого тика
            // Но PeriodicWork всё равно повторится через 15 мин
            Result.success()
        } catch (e: Exception) {
            Timber.w(e, "KeepAliveWorker: enrollment ошибка — повторим через 15 мин")
            Result.success()
        }
    }
}
