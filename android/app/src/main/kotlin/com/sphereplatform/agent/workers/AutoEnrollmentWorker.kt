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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.withLock
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
 *    а) При autoRegister=true или без назначенного UUID → регистрирует устройство.
 *    б) Иначе → сохраняет явный UUID и статический API ключ (legacy).
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
        internal const val WORK_NAME = "sphere_auto_enroll"

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
                ExistingWorkPolicy.KEEP,
                request,
            )
            Timber.i("AutoEnrollmentWorker scheduled")
        }
    }

    override suspend fun doWork(): Result = authStore.enrollmentMutex.withLock { doWorkLocked() }

    private suspend fun doWorkLocked(): Result {
        Timber.i("AutoEnrollmentWorker: started")

        return try {
            // A missing marker or earlier FGS rejection must not rotate issued credentials again.
            if (!authStore.getToken().isNullOrBlank() && authStore.getDeviceId() != null) return activate()
            val config = provisioner.discoverConfig() ?: return Result.retry()
            if (config.requiresRegistration) {
                val enrollmentKey = config.apiKey.takeIf { it.isNotBlank() }
                if (enrollmentKey == null) {
                    Timber.w("AutoEnrollmentWorker: auto_register requested, but no enrollment key found")
                    return Result.retry()
                }

                Timber.i("AutoEnrollmentWorker: attempting to register with server ${config.serverUrl}")
                registrationClient.register(
                    serverUrl = config.serverUrl,
                    fallbackServerUrl = config.fallbackServerUrl,
                    enrollmentApiKey = enrollmentKey,
                )
            } else {
                // Классический flow — используем предоставленный API ключ
                if (config.apiKey.isBlank()) {
                    Timber.w("AutoEnrollmentWorker: config contains no api_key and auto_register is false")
                    return Result.failure()
                }

                Timber.i("AutoEnrollmentWorker: using static API Key from config")
                authStore.saveServerRoutes(config.serverUrl, config.fallbackServerUrl)
                config.deviceId?.let { authStore.saveDeviceId(it) }
                authStore.saveApiKey(config.apiKey)
            }

            activate()

        } catch (e: CancellationException) {
            throw e
        } catch (e: RegistrationException) {
            Timber.w("AutoEnrollmentWorker: Registration failed: HTTP ${e.httpCode} - ${e.message}")
            // Если ошибка 4xx (например невалидный ключ), лучше не ретраить, а завершить с отказом
            return if (e.httpCode in 400..499 && e.httpCode !in setOf(408, 429)) Result.failure() else Result.retry()
        } catch (e: Exception) {
            Timber.e(e, "AutoEnrollmentWorker: unexpected error")
            Result.retry() // Сетевые ошибки — повторяем позже
        }
    }

    private suspend fun activate(): Result {
        currentCoroutineContext().ensureActive()
        ServiceWatchdog.markEnrolled(context)
        ServiceWatchdog.schedule(context)
        SphereAgentService.start(context)
        return Result.success()
    }

}
