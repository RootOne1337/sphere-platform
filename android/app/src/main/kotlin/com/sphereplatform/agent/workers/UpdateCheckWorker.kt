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
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.ota.OtaUpdatePayload
import com.sphereplatform.agent.ota.OtaUpdateService
import com.sphereplatform.agent.ota.OtaUserActionRequiredException
import com.sphereplatform.agent.provisioning.InstanceRegistrationGuard
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import timber.log.Timber
import java.util.concurrent.ThreadLocalRandom
import java.util.concurrent.TimeUnit

private const val MAX_RESPONSE_CHARS = 64 * 1024  // 64KB — защита от OOM

/**
 * UpdateCheckWorker — периодически проверяет наличие новой версии APK.
 *
 * Расписание: каждые 6 часов при наличии сети.
 *
 * Endpoint: GET {serverUrl}/api/v1/updates/latest
 *   Query params: platform=android, flavor={FLAVOR_LABEL}, version_code={VERSION_CODE}
 *   Headers: X-API-Key
 *
 * Ответ JSON (update_available=true → автоустановка):
 * {
 *   "update_available": true,
 *   "version_code": 20260223,
 *   "version_name": "1.5.0",
 *   "download_url": "https://...",
 *   "sha256": "abc123...",
 *   "mandatory": false
 * }
 */
@HiltWorker
class UpdateCheckWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val authStore: AuthTokenStore,
    private val instanceRegistrationGuard: InstanceRegistrationGuard,
    private val otaUpdateService: OtaUpdateService,
    private val httpClient: OkHttpClient,
) : CoroutineWorker(context, params) {

    companion object {
        private const val WORK_NAME = "sphere_update_check"
        internal const val IMMEDIATE_WORK_NAME = "sphere_update_check_immediate"
        private const val MAX_IMMEDIATE_JITTER_MS = 120_000L

        /**
         * Request a prompt OTA catalog check at app start and after an authenticated
         * management reconnect. CONNECTED keeps it queued through offline periods;
         * KEEP coalesces reconnect bursts into one pending check.
         */
        fun scheduleImmediate(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = OneTimeWorkRequestBuilder<UpdateCheckWorker>()
                .setConstraints(constraints)
                // Spread a fleet-wide boot/reconnect over two minutes instead of
                // stampeding the catalog and artifact store at the same instant.
                .setInitialDelay(
                    ThreadLocalRandom.current().nextLong(MAX_IMMEDIATE_JITTER_MS + 1),
                    TimeUnit.MILLISECONDS,
                )
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                IMMEDIATE_WORK_NAME,
                ExistingWorkPolicy.KEEP,
                request,
            )
            Timber.d("UpdateCheckWorker immediate check queued")
        }

        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val request = PeriodicWorkRequestBuilder<UpdateCheckWorker>(6, TimeUnit.HOURS)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
            Timber.d("UpdateCheckWorker scheduled (every 6h)")
        }
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            // A golden-image clone contains the master's issued credentials. Never
            // refresh or use them until this VM has claimed its own device identity.
            if (authStore.getToken().isNullOrBlank()) {
                Timber.d("UpdateCheckWorker: skipped (not enrolled)")
                return@withContext Result.success()
            }
            instanceRegistrationGuard.ensureRegistered()

            // Refresh may suspend while discovery changes the active management route.
            // Read the route afterwards, and include refresh failures in retry policy.
            val apiKey = authStore.getFreshToken()
            val serverUrl = authStore.getServerUrl().trimEnd('/')
            if (serverUrl.isBlank() || apiKey.isNullOrBlank()) {
                Timber.d("UpdateCheckWorker: skipped (not enrolled)")
                return@withContext Result.success()
            }
            val flavor = BuildConfig.FLAVOR_LABEL
            val versionCode = BuildConfig.VERSION_CODE
            val url = "$serverUrl/api/v1/updates/latest" +
                "?platform=android&flavor=$flavor&version_code=$versionCode"

            val request = Request.Builder()
                .url(url)
                .addHeader("X-API-Key", apiKey)
                .get()
                .build()

            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Timber.w("UpdateCheckWorker: HTTP %d; retry with WorkManager backoff", response.code)
                    return@use Result.retry()
                }
                val body = response.body ?: return@use Result.retry()
                val source = body.source()
                check(!source.request(MAX_RESPONSE_CHARS.toLong() + 1)) { "Update response too large" }
                val json = JSONObject(source.readUtf8())

                if (!json.getBoolean("update_available")) {
                    Timber.i("UpdateCheckWorker: already on latest version ($versionCode)")
                    return@use Result.success()
                }

                // A delayed/cached catalog response must not reinstall or downgrade
                // an APK which already has the advertised version.
                if (json.getInt("version_code") <= versionCode) {
                    Timber.i("UpdateCheckWorker: ignoring stale release metadata")
                    return@use Result.success()
                }

                val payload = OtaUpdatePayload(
                    download_url = json.getString("download_url"),
                    version = json.optString("version_name", "?"),
                    version_code = json.getInt("version_code"),
                    sha256 = json.optString("sha256", ""),
                    force = json.optBoolean("mandatory", false),
                )
                Timber.i("UpdateCheckWorker: update available → ${payload.version}, starting OTA")
                otaUpdateService.performUpdate(payload)
                Result.success()
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: OtaUserActionRequiredException) {
            // The receiver already persisted/upload-queued the exact OS status.
            // Do not retry into repeated installer prompts while Android awaits approval.
            Timber.w("UpdateCheckWorker: PackageInstaller awaits user action (session=${e.sessionId})")
            Result.success()
        } catch (e: Exception) {
            Timber.w(e, "UpdateCheckWorker: check failed")
            Result.retry()
        }
    }
}
