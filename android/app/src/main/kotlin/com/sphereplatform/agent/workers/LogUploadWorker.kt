package com.sphereplatform.agent.workers

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.sphereplatform.agent.logging.CrashHandler
import com.sphereplatform.agent.logging.FileLoggingTree
import com.sphereplatform.agent.logging.LogcatCollector
import com.sphereplatform.agent.provisioning.InstanceRegistrationGuard
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.CancellationException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.util.concurrent.ThreadLocalRandom
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
    private val instanceRegistrationGuard: InstanceRegistrationGuard,
    private val loggingTree: FileLoggingTree,
    private val logcatCollector: LogcatCollector,
    private val httpClient: OkHttpClient,
) : CoroutineWorker(context, params) {

    private data class CrashLogSnapshot(
        val file: File,
        val text: String,
        val length: Long,
        val lastModified: Long,
    )

    companion object {
        private const val WORK_NAME = "sphere_log_upload"
        internal const val IMMEDIATE_WORK_NAME = "sphere_log_upload_immediate"
        internal const val CRASH_UPLOAD_WORK_NAME = "sphere_crash_log_upload"
        private const val MAX_CRASH_LOG_BYTES = 128 * 1024
        private const val MAX_IMMEDIATE_JITTER_MS = 120_000L
        // Backend rejects a log entry above 512 KiB. Leave room for its
        // upload separator and keep the entire request below that hard limit.
        private const val MAX_UPLOAD_BYTES = 480 * 1024

        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = PeriodicWorkRequestBuilder<LogUploadWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build()

            val workManager = WorkManager.getInstance(context)
            workManager.enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
            Timber.d("LogUploadWorker scheduled (every 15 min)")

            schedulePendingCrashUpload(context, workManager)
        }

        /** Upload a fresh OTA installer result promptly, while spreading fleet callbacks over two minutes. */
        fun scheduleImmediate(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val request = OneTimeWorkRequestBuilder<LogUploadWorker>()
                .setConstraints(constraints)
                .setInitialDelay(
                    ThreadLocalRandom.current().nextLong(MAX_IMMEDIATE_JITTER_MS + 1),
                    TimeUnit.MILLISECONDS,
                )
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                IMMEDIATE_WORK_NAME,
                ExistingWorkPolicy.KEEP,
                request,
            )
            Timber.d("LogUploadWorker immediate diagnostic upload queued")
        }

        /** Upload a persisted crash on the next process start, without waiting for
         * the 15-minute periodic diagnostics window. WorkManager retries while
         * offline and KEEP coalesces boot/package-replacement bursts.
         */
        internal fun schedulePendingCrashUpload(context: Context) {
            schedulePendingCrashUpload(context, WorkManager.getInstance(context))
        }

        private fun schedulePendingCrashUpload(context: Context, workManager: WorkManager) {
            val crashFile = CrashHandler.crashLogFile(context)
            if (!crashFile.isFile || crashFile.length() == 0L) return

            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val request = OneTimeWorkRequestBuilder<LogUploadWorker>()
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build()

            workManager.enqueueUniqueWork(
                CRASH_UPLOAD_WORK_NAME,
                ExistingWorkPolicy.KEEP,
                request,
            )
            Timber.i("LogUploadWorker: pending crash upload queued")
        }
    }

    override suspend fun doWork(): Result {
        try {
            // The Android app-data copied by an emulator clone includes the master's
            // tokens. Fail closed before refresh or upload until clone rebind succeeds.
            if (authStore.getToken().isNullOrBlank()) {
                Timber.d("LogUploadWorker: skipped (not enrolled yet)")
                return Result.success()
            }
            instanceRegistrationGuard.ensureRegistered()

            val serverUrl = authStore.getServerUrl().trimEnd('/')
            val apiKey = authStore.getFreshToken()
            val deviceId = authStore.getDeviceId()
            if (serverUrl.isBlank() || apiKey.isNullOrBlank() || deviceId.isNullOrBlank()) {
                Timber.d("LogUploadWorker: skipped (not enrolled yet)")
                return Result.success()
            }

            val crashSnapshot = readCrashLogSnapshot()
            val fileLogs = loggingTree.readRecentLogs(32 * 1024)
            val priorityLifecycleLogs = withoutFileTailDuplicates(
                fileLogs,
                loggingTree.readRecentWebSocketLifecycleLogs(32 * 1024),
            )

            val logs = capUtf8Tail(buildString {
                append("=== FILE LOGS ===\n")
                append(fileLogs)
                append("\n=== SPHERE LOGCAT ===\n")
                append(logcatCollector.collectSphereOnly(lines = 300))
                append("\n=== PRIORITY WS LIFECYCLE ===\n")
                append(priorityLifecycleLogs)
                append("\n=== RECENT SPHERE CRASH ===\n")
                append(crashSnapshot?.text ?: "No persisted uncaught crash record")
            })

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
                    if (crashSnapshot != null && !deleteUploadedCrashSnapshot(crashSnapshot)) {
                        Timber.w("LogUploadWorker: crash log changed during upload; retaining it")
                    }
                    Timber.i("LogUploadWorker: uploaded ${logs.length} bytes (HTTP ${response.code})")
                    return Result.success()
                } else {
                    Timber.w("LogUploadWorker: server returned HTTP ${response.code}")
                    return Result.retry()
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "LogUploadWorker: upload failed")
            return Result.retry()
        }
    }

    private fun readCrashLogSnapshot(): CrashLogSnapshot? {
        val file = CrashHandler.crashLogFile(applicationContext)
        if (!file.isFile) return null
        return runCatching {
            RandomAccessFile(file, "r").use { input ->
                val length = input.length()
                val count = minOf(length, MAX_CRASH_LOG_BYTES.toLong()).toInt()
                val bytes = ByteArray(count)
                input.seek(length - count)
                input.readFully(bytes)
                CrashLogSnapshot(
                    file = file,
                    text = String(bytes, StandardCharsets.UTF_8),
                    length = length,
                    lastModified = file.lastModified(),
                )
            }
        }.onFailure { error ->
            Timber.w(error, "LogUploadWorker: could not read persisted crash record")
        }.getOrNull()
    }

    private fun deleteUploadedCrashSnapshot(snapshot: CrashLogSnapshot): Boolean {
        return runCatching {
            if (!snapshot.file.isFile) return@runCatching true
            // Do not remove a newer record that appeared while the HTTP upload ran.
            if (snapshot.file.length() != snapshot.length ||
                snapshot.file.lastModified() != snapshot.lastModified
            ) return@runCatching false
            snapshot.file.delete() || !snapshot.file.exists()
        }.getOrDefault(false)
    }

    private fun withoutFileTailDuplicates(fileLogs: String, priorityLogs: String): String {
        val fileLifecycleLines = fileLogs.lineSequence()
            .filter { it.contains("ws_lifecycle ") }
            .toSet()
        val missingLines = priorityLogs.lineSequence()
            .filter { it.contains("ws_lifecycle ") && it !in fileLifecycleLines }
            .toList()
        return if (missingLines.isEmpty()) "" else missingLines.joinToString(separator = "\n", postfix = "\n")
    }

    private fun capUtf8Tail(value: String): String {
        val bytes = value.toByteArray(StandardCharsets.UTF_8)
        if (bytes.size <= MAX_UPLOAD_BYTES) return value
        val tail = bytes.copyOfRange(bytes.size - MAX_UPLOAD_BYTES, bytes.size)
        val decoder = StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.IGNORE)
            .onUnmappableCharacter(CodingErrorAction.IGNORE)
        return decoder.decode(ByteBuffer.wrap(tail)).toString()
    }

}
