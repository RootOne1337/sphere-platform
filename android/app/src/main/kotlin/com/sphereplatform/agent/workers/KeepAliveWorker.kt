package com.sphereplatform.agent.workers

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.sphereplatform.agent.R
import com.sphereplatform.agent.provisioning.DeviceRegistrationClient
import com.sphereplatform.agent.provisioning.RegistrationException
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.root.RootAutoStart
import com.sphereplatform.agent.service.ServiceWatchdog
import com.sphereplatform.agent.service.SphereAgentService
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.withLock
import timber.log.Timber
import java.util.concurrent.TimeUnit

/**
 * Periodic recovery of enrollment and the agent service, once WorkManager can run.
 * Issued credentials plus an assigned device ID are required before requesting
 * service activation. Missing config or a failed registration leaves the next
 * periodic tick available. WorkManager timing and service start remain subject
 * to Android scheduling, permissions and force-stop/OEM restrictions.
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
         * ID уведомления для foreground-режима воркера.
         * Должен отличаться от [SphereAgentService.NOTIFICATION_ID] = 1.
         */
        private const val WORKER_NOTIFICATION_ID = 2

        /**
         * ID канала уведомлений для технического foreground воркера.
         * IMPORTANCE_MIN — без звука, без вибрации, не показывается в статус-баре.
         */
        private const val WORKER_CHANNEL_ID = "sphere_keepalive_worker"

        /**
         * Планирует периодический watchdog-тик каждые 15 минут.
         *
         * Вызывается из:
         * - [com.sphereplatform.agent.SphereApp.onCreate] — при любом создании процесса
         * - [com.sphereplatform.agent.BootReceiver.onReceive] — при загрузке устройства
         *
         * KEEP policy: если задача уже запланирована — не дублирует.
         * Без constraint на сеть: планирование допускает запуск
         * включая boot без сети. Запуск foreground service не требует сети.
         * Enrollment (HTTP-запросы) обрабатывает отсутствие сети самостоятельно.
         */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<KeepAliveWorker>(
                15, TimeUnit.MINUTES,
            ).build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
            Timber.i("KeepAliveWorker: запланирован (минимальный интервал 15 мин)")
        }
    }

    override suspend fun doWork(): Result = authStore.enrollmentMutex.withLock { doWorkLocked() }

    private suspend fun doWorkLocked(): Result {
        Timber.d("KeepAliveWorker: тик")

        // Request foreground execution; this is not proof that Android will
        // permit starting the agent service. Its start failure is handled below.
        try {
            setForeground(createForegroundInfo())
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // IllegalStateException: может упасть если WorkManager не поддерживает
            // setForeground() в данной конфигурации. Не фатально — startForegroundService
            // может сработать, если приложение всё равно на переднем плане.
            Timber.w(e, "KeepAliveWorker: setForeground не сработал — продолжаем без него")
        }

        val isEnrolled = ServiceWatchdog.isEnrolled(applicationContext)
        val hasToken = !authStore.getToken().isNullOrBlank() && authStore.getDeviceId() != null

        // ── Сценарий 1: Enrolled + есть токен → гарантируем работу сервиса ──
        if (hasToken) {
            if (!isEnrolled) ServiceWatchdog.markEnrolled(applicationContext)
            ensureServiceRunning()
            return Result.success()
        }

        // ── Сценарий 2: Enrolled но нет токена → невалидное состояние ──────
        if (isEnrolled && !hasToken) {
            Timber.w("KeepAliveWorker: enrolled=true, но credentials или device ID отсутствуют → пробуем enrollment заново")
        }

        // ── Сценарий 3: Не enrolled → Zero-Touch enrollment ────────────────
        return tryAutoEnrollment()
    }

    /**
     * Создаёт [ForegroundInfo] для продвижения воркера в foreground-режим.
     *
     * Уведомление имеет минимальный приоритет — не мелькает у пользователя.
     * Android 14+ (API 34): тип [ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC] должен быть
     * объявлен в манифесте для [androidx.work.impl.foreground.SystemForegroundService].
     */
    private fun createForegroundInfo(): ForegroundInfo {
        ensureWorkerNotificationChannel()
        val notification = NotificationCompat.Builder(applicationContext, WORKER_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_sphere)
            .setContentTitle("Sphere Platform")
            .setContentText("Запуск агента...")
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setSilent(true)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                WORKER_NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(WORKER_NOTIFICATION_ID, notification)
        }
    }

    /**
     * Создаёт канал уведомлений минимального приоритета для foreground-воркера.
     * Идемпотентно — повторные вызовы безопасны.
     */
    private fun ensureWorkerNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = applicationContext.getSystemService(NotificationManager::class.java)
            if (nm.getNotificationChannel(WORKER_CHANNEL_ID) == null) {
                val channel = NotificationChannel(
                    WORKER_CHANNEL_ID,
                    "Sphere Agent (служебное)",
                    NotificationManager.IMPORTANCE_MIN,
                ).apply {
                    description = "Технический канал для попыток восстановления агента"
                    setShowBadge(false)
                }
                nm.createNotificationChannel(channel)
            }
        }
    }

    /**
     * Запрашивает запуск [SphereAgentService] после получения identity.
     * Повторный запрос не означает подтверждение готовности сервиса или WS.
     */
    private fun ensureServiceRunning() {
        try {
            RootAutoStart.ensureRunning(applicationContext)
            SphereAgentService.start(applicationContext)
            ServiceWatchdog.schedule(applicationContext)
            Timber.d("KeepAliveWorker: запуск сервиса запрошен, watchdog запланирован")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Android 12+: ForegroundServiceStartNotAllowedException возможен
            // если WorkManager выполняет задачу в expedited/background context.
            // Не фатально — следующий тик через 15 мин повторит попытку.
            Timber.w(e, "KeepAliveWorker: не удалось запустить сервис — повторим через 15 мин")
        }
    }

    /**
     * Пытается пройти Zero-Touch enrollment.
     * Использует тот же enrollment mutex, что и [AutoEnrollmentWorker].
     */
    private suspend fun tryAutoEnrollment(): Result {
        return try {
            val config = provisioner.discoverConfig() ?: return Result.success()
            if (config.requiresRegistration) {
                // Auto-register через серверный endpoint
                val enrollmentKey = config.apiKey.takeIf { it.isNotBlank() }
                if (enrollmentKey == null) {
                    Timber.w("KeepAliveWorker: auto_register запрошен, но enrollment key не найден")
                    return Result.success()
                }
                Timber.i("KeepAliveWorker: авто-регистрация через ${config.serverUrl}")
                registrationClient.register(
                    serverUrl = config.serverUrl,
                    fallbackServerUrl = config.fallbackServerUrl,
                    enrollmentApiKey = enrollmentKey,
                )
            } else if (config.apiKey.isNotBlank()) {
                // Статический API-ключ из конфига/BuildConfig
                Timber.i("KeepAliveWorker: enrollment со статическим API-ключом (${config.source})")
                authStore.saveServerRoutes(config.serverUrl, config.fallbackServerUrl)
                config.deviceId?.let { authStore.saveDeviceId(it) }
                authStore.saveApiKey(config.apiKey)
            } else {
                Timber.d("KeepAliveWorker: конфиг без ключа и без auto_register")
                return Result.success()
            }

            // Enrollment успешен → активируем все защитные механизмы
            currentCoroutineContext().ensureActive()
            ServiceWatchdog.markEnrolled(applicationContext)
            ServiceWatchdog.schedule(applicationContext)
            ensureServiceRunning()

            Timber.i("KeepAliveWorker: enrollment сохранён, запуск агента запрошен.")
            Result.success()

        } catch (e: CancellationException) {
            throw e
        } catch (e: RegistrationException) {
            Timber.w("KeepAliveWorker: регистрация провалена: HTTP ${e.httpCode} — ${e.message}")
            // Следующий периодический тик снова попробует регистрацию.
            // Success завершает тик, но не отмечает устройство зарегистрированным.
            Result.success()
        } catch (e: Exception) {
            Timber.w(e, "KeepAliveWorker: enrollment ошибка — повторим через 15 мин")
            Result.success()
        }
    }
}
