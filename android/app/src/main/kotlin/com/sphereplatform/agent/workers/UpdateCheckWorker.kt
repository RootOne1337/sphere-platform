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
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.ota.OtaUpdatePayload
import com.sphereplatform.agent.ota.OtaUpdateService
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import timber.log.Timber
import java.util.concurrent.TimeUnit

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
    private val otaUpdateService: OtaUpdateService,
    private val httpClient: OkHttpClient,
) : CoroutineWorker(context, params) {

    companion object {
        private const val WORK_NAME = "sphere_update_check"

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

    override suspend fun doWork(): Result {
        val serverUrl = authStore.getServerUrl().trimEnd('/')
        val apiKey = authStore.getToken()

        if (serverUrl.isBlank() || apiKey.isNullOrBlank()) {
            Timber.d("UpdateCheckWorker: skipped (not enrolled)")
            return Result.success()
        }

        return try {
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
                    Timber.d("UpdateCheckWorker: server returned HTTP ${response.code} — no update info")
                    return@use Result.success()
                }
                val body = response.body?.string() ?: return@use Result.success()
                val json = JSONObject(body)

                if (!json.optBoolean("update_available", false)) {
                    Timber.i("UpdateCheckWorker: already on latest version ($versionCode)")
                    return@use Result.success()
                }

                val payload = OtaUpdatePayload(
                    download_url = json.getString("download_url"),
                    version = json.optString("version_name", "?"),
                    sha256 = json.optString("sha256", ""),
                    force = json.optBoolean("mandatory", false),
                )
                Timber.i("UpdateCheckWorker: update available → ${payload.version}, starting OTA")
                otaUpdateService.performUpdate(payload)
                Result.success()
            }
        } catch (e: Exception) {
            Timber.w(e, "UpdateCheckWorker: check failed")
            Result.retry()
        }
    }
}
