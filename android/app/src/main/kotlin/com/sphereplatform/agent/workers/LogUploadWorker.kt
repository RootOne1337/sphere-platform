package com.sphereplatform.agent.workers

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.sphereplatform.agent.logging.FileLoggingTree
import com.sphereplatform.agent.logging.LogcatCollector
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber
import java.util.concurrent.TimeUnit

/**
 * LogUploadWorker — периодически загружает накопленные логи на сервер.
 *
 * Расписание: каждые 15 минут при наличии сети.
 * Retry: экспоненциальная backoff (15s, 30s, 1m, ...).
 *
 * Endpoint: POST {serverUrl}/api/v1/logs/upload
 *   Headers: X-API-Key, X-Device-Id
 *   Body: text/plain (лог-строки)
 *
 * @Hilt: AssistedInject + HiltWorkerFactory
 */
@HiltWorker
class LogUploadWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val authStore: AuthTokenStore,
    private val loggingTree: FileLoggingTree,
    private val logcatCollector: LogcatCollector,
    private val httpClient: OkHttpClient,
) : CoroutineWorker(context, params) {

    companion object {
        private const val WORK_NAME = "sphere_log_upload"

        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = PeriodicWorkRequestBuilder<LogUploadWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
            Timber.d("LogUploadWorker scheduled (every 15 min)")
        }
    }

    override suspend fun doWork(): Result {
        val serverUrl = authStore.getServerUrl().trimEnd('/')
        val apiKey = authStore.getToken()
        val deviceId = authStore.getDeviceId()

        if (serverUrl.isBlank() || apiKey.isNullOrBlank() || deviceId.isNullOrBlank()) {
            Timber.d("LogUploadWorker: skipped (not enrolled yet)")
            return Result.success()
        }

        return try {
            val logs = buildString {
                append("=== FILE LOGS ===\n")
                append(loggingTree.readRecentLogs(32 * 1024))
                append("\n=== SPHERE LOGCAT ===\n")
                append(logcatCollector.collectSphereOnly(lines = 300))
            }

            // FIX D3: device_id вынесен из URL в заголовок X-Device-Id.
            // В URL он логируется nginx access log, Cloudflare dashboard — утечка.
            val url = "$serverUrl/api/v1/logs/upload"
            val body = logs.toRequestBody("text/plain; charset=utf-8".toMediaType())
            val request = Request.Builder()
                .url(url)
                .addHeader("X-API-Key", apiKey)
                .addHeader("X-Device-Id", deviceId)
                .post(body)
                .build()

            httpClient.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    Timber.i("LogUploadWorker: uploaded ${logs.length} bytes (HTTP ${response.code})")
                    Result.success()
                } else {
                    Timber.w("LogUploadWorker: server returned HTTP ${response.code}")
                    Result.retry()
                }
            }
        } catch (e: Exception) {
            Timber.w(e, "LogUploadWorker: upload failed")
            Result.retry()
        }
    }
}
