package com.sphereplatform.agent.workers

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
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

/**
 * AutoEnrollmentWorker — фоновый рабочий процесс для Zero-Touch регистрации устройства.
 * 
 * Если устройство не зарегистрировано (isEnrolled == false) и происходит перезагрузка,
 * [com.sphereplatform.agent.BootReceiver] ставит эту задачу в очередь.
 * 
 * Рабочий процесс:
 * 1. Ищет конфигурацию (файлы, MDM, серверный конфиг).
 * 2. Если конфигурация найдена:
 *    а) При autoRegister=true → вызывает API регистрации, сохраняет JWT токены.
 *    б) Иначе → сохраняет статический API ключ.
 * 3. Отмечает enrolled=true в настройках.
 * 4. Запускает Foreground Service агента.
 */
@HiltWorker
class AutoEnrollmentWorker @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted params: WorkerParameters,
    private val provisioner: ZeroTouchProvisioner,
    private val registrationClient: DeviceRegistrationClient,
    private val authStore: AuthTokenStore,
) : CoroutineWorker(context, params) {

    companion object {
        private const val WORK_NAME = "sphere_auto_enroll"

        /**
         * Планирует одноразовую фоновую задачу по авто-регистрации.
         * Требуется подключение к сети.
         */
        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = OneTimeWorkRequestBuilder<AutoEnrollmentWorker>()
                .setConstraints(constraints)
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                WORK_NAME,
                ExistingWorkPolicy.REPLACE,
                request,
            )
            Timber.i("AutoEnrollmentWorker scheduled")
        }
    }

    override suspend fun doWork(): Result {
        // Если уже зарегистрированы — ничего делать не нужно
        if (ServiceWatchdog.isEnrolled(context) && authStore.getToken() != null) {
            Timber.d("AutoEnrollmentWorker: skipped, already enrolled")
            return Result.success()
        }

        Timber.i("AutoEnrollmentWorker: started")

        val config = provisioner.discoverConfig()
        if (config == null) {
            Timber.w("AutoEnrollmentWorker: configuration not found. Manual enrollment required.")
            return Result.success() // Нет смысла повторять без конфига
        }

        return try {
            // Если включена автоматическая регистрация через config_endpoint
            if (config.autoRegisterEnabled && config.apiKey.isBlank()) {
                val enrollmentKey = getEnrollmentKeyFromConfig(config.serverUrl)
                if (enrollmentKey == null) {
                    Timber.w("AutoEnrollmentWorker: auto_register requested, but no enrollment key found")
                    return Result.failure()
                }

                Timber.i("AutoEnrollmentWorker: attempting to register with server ${config.serverUrl}")
                registrationClient.register(
                    serverUrl = config.serverUrl,
                    enrollmentApiKey = enrollmentKey,
                )
            } else {
                // Классический flow — используем предоставленный API ключ
                if (config.apiKey.isBlank()) {
                    Timber.w("AutoEnrollmentWorker: config contains no api_key and auto_register is false")
                    return Result.failure()
                }

                Timber.i("AutoEnrollmentWorker: using static API Key from config")
                authStore.saveServerUrl(config.serverUrl)
                config.deviceId?.let { authStore.saveDeviceId(it) }
                authStore.saveApiKey(config.apiKey)
            }

            // --- Успех! Маркируем энролмент и запускаем сервис ---
            ServiceWatchdog.markEnrolled(context)
            ServiceWatchdog.schedule(context)

            try {
                SphereAgentService.start(context)
                Timber.i("AutoEnrollmentWorker: successfully started SphereAgentService!")
            } catch (e: Exception) {
                Timber.e(e, "AutoEnrollmentWorker: enrolled, but failed to start service (Android 12+ restriction?)")
            }

            Result.success()

        } catch (e: RegistrationException) {
            Timber.w("AutoEnrollmentWorker: Registration failed: HTTP ${e.httpCode} - ${e.message}")
            // Если ошибка 4xx (например невалидный ключ), лучше не ретраить, а завершить с отказом
            return if (e.httpCode in 400..499) Result.failure() else Result.retry()
        } catch (e: Exception) {
            Timber.e(e, "AutoEnrollmentWorker: unexpected error")
            Result.retry() // Сетевые ошибки — повторяем позже
        }
    }

    private fun getEnrollmentKeyFromConfig(serverUrl: String): String? {
        val serverConfig = provisioner.fetchServerConfig()
        return serverConfig?.enrollmentApiKey
    }
}
