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
         * ID уведомления для foreground-режима воркера (Android 12+ обход FGS-ограничений).
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
         * БЕЗ constraint на сеть: воркер должен запускаться ПРИ ЛЮБЫХ УСЛОВИЯХ,
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
            Timber.i("KeepAliveWorker: запланирован (каждые 15 мин, setPersisted=true)")
        }
    }

    override suspend fun doWork(): Result {
        Timber.d("KeepAliveWorker: тик")

        // ── БЕЗУСЛОВНЫЙ запуск через root (если доступен) ──────────────────
        // Это ГЛАВНЫЙ механизм автостарта на рутованных эмуляторах (LDPlayer).
        // WorkManager PeriodicWork через JobScheduler — ЕДИНСТВЕННОЕ что
        // переживает ребут без записи в /system. При каждом тике:
        // 1. Снимает stopped state
        // 2. Запускает сервис через am startservice (root обходит FGS-ограничения)
        // 3. Отправляет BOOT_COMPLETED для BootReceiver (активирует ВСЕ механизмы)
        // Идемпотентно — если сервис уже работает, ничего лишнего не произойдёт.
        RootAutoStart.ensureRunning(applicationContext)

        // ── БЕЗУСЛОВНЫЙ запуск сервиса через Java API ──────────────────────
        // На API 28 (LDPlayer Android 9) нет FGS-ограничений — startForegroundService
        // работает из любого контекста. Запускаем ВСЕГДА, не только при enrollment.
        // Сервис при отсутствии token не подключится к WS, но будет жив.
        ensureServiceRunning()

        // ── Продвигаем воркер в foreground для обхода FGS-ограничений Android 12+ ─────────
        // Android 12+ (API 31) запрещает startForegroundService() из фонового контекста.
        // WorkManager воркеры выполняются в фоне → SphereAgentService.start() молча падает
        // с ForegroundServiceStartNotAllowedException, которое глотается в catch-блоке.
        // setForeground() превращает ЭТОТ воркер в foreground service, после чего запуск
        // ДРУГОГО foreground service (SphereAgentService) становится разрешённым.
        // Android 14+ (API 34): требует объявления foregroundServiceType в манифесте
        // для androidx.work.impl.foreground.SystemForegroundService.
        try {
            setForeground(createForegroundInfo())
        } catch (e: Exception) {
            // IllegalStateException: может упасть если WorkManager не поддерживает
            // setForeground() в данной конфигурации. Не фатально — startForegroundService
            // может сработать, если приложение всё равно на переднем плане.
            Timber.w(e, "KeepAliveWorker: setForeground не сработал — продолжаем без него")
        }

        val isEnrolled = ServiceWatchdog.isEnrolled(applicationContext)
        val hasToken = authStore.getToken() != null

        // ── Сценарий 1: Enrolled + есть токен → гарантируем работу сервиса ──
        if (isEnrolled && hasToken) {
            return Result.success()
        }

        // ── Сценарий 2: Enrolled но нет токена → невалидное состояние ──────
        if (isEnrolled && !hasToken) {
            Timber.w("KeepAliveWorker: enrolled=true, но токен отсутствует → пробуем enrollment заново")
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
                    description = "Технический канал для гарантированного запуска агента при загрузке"
                    setShowBadge(false)
                }
                nm.createNotificationChannel(channel)
            }
        }
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
    private suspend fun tryAutoEnrollment(): Result {
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
                // Статический API-ключ из конфига/BuildConfig — сохраняем СРАЗУ (без HTTP)
                Timber.i("KeepAliveWorker: enrollment со статическим API-ключом (${config.source})")
                authStore.saveServerUrl(config.serverUrl)
                config.deviceId?.let { authStore.saveDeviceId(it) }
                authStore.saveApiKey(config.apiKey)

                // Upgrade: пробуем register() чтобы получить UUID device_id + JWT.
                // register() сохранит UUID + JWT в authStore, перезаписав static key.
                // При неудаче — static key остаётся как baseline.
                if (config.autoRegisterEnabled) {
                    try {
                        Timber.i("KeepAliveWorker: upgrade → register() для UUID device_id + JWT")
                        registrationClient.register(
                            serverUrl = config.serverUrl,
                            enrollmentApiKey = config.apiKey,
                        )
                    } catch (e: Exception) {
                        Timber.d(e, "KeepAliveWorker: register() upgrade не удался — static key сохранён")
                    }
                }
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
