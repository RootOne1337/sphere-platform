package com.sphereplatform.agent.ota

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import timber.log.Timber
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * OtaUpdateService — самообновление агента.
 *
 * Порядок:
 * 1. Скачать APK с SSRF-защитой (только с хоста сервера управления, только HTTPS)
 * 2. Проверить SHA-256
 * 3. Установить через root (pm install) или PackageInstaller (fallback)
 * 4. Удалить APK после установки
 *
 * # Безопасность
 * - [validateDownloadUrl]: хост URL == хост сервера → нет утечки Bearer-токена
 * - Path traversal check: canonicalFile за пределами otaDir → exception
 * - SHA-256 mismatch → exception, APK удаляется
 * - Загрузка только с Bearer-токеном (не открытый URL)
 * - Только HTTPS
 */
@Singleton
class OtaUpdateService @Inject constructor(
    @ApplicationContext private val context: Context,
    private val httpClient: OkHttpClient,
    private val authStore: AuthTokenStore,
) {
    private val apkDir = File(context.filesDir, "ota")

    suspend fun performUpdate(payload: OtaUpdatePayload) {
        Timber.i("OTA: starting update → version=${payload.version}")
        val apkFile = downloadApk(payload)
        try {
            verifyChecksum(apkFile, payload.sha256)
            install(apkFile)
        } finally {
            // APK удаляется в любом случае после попытки установки
            apkFile.delete()
            Timber.d("OTA: APK deleted")
        }
    }

    private suspend fun downloadApk(payload: OtaUpdatePayload): File {
        apkDir.mkdirs()
        val dest = File(apkDir, "update_${payload.version}.apk")

        // Path traversal check
        val canonicalDest = dest.canonicalFile
        val canonicalDir = apkDir.canonicalFile
        check(canonicalDest.startsWith(canonicalDir)) {
            "Path traversal detected in OTA filename"
        }

        // БЕЗОПАСНОСТЬ: SSRF-защита — скачиваем только с нашего сервера.
        validateDownloadUrl(payload.download_url)

        val request = Request.Builder()
            .url(payload.download_url)
            .header("Authorization", "Bearer ${authStore.getToken()}")
            .build()

        withContext(Dispatchers.IO) {
            // FIX 7.2: response.use {} гарантирует закрытие при ошибках HTTP
            // (без use была утечка TCP-соединений в OkHttp connection pool)
            httpClient.newCall(request).execute().use { response ->
                check(response.isSuccessful) { "OTA download failed: ${response.code}" }
                response.body!!.byteStream().use { input ->
                    dest.outputStream().use { output ->
                        input.copyTo(output)
                    }
                }
            }
        }

        Timber.i("OTA: downloaded ${dest.length()} bytes → ${dest.name}")
        return dest
    }

    /**
     * SSRF-защита: download_url должен указывать на тот же хост, что и сервер управления.
     *
     * Без этой проверки: сервер мог бы передать произвольный URL → Bearer-токен
     * агента утёк бы на сторонний сервер.
     */
    private fun validateDownloadUrl(url: String) {
        require(url.startsWith("https://")) {
            "OTA download must use HTTPS, got: $url"
        }

        val serverUrl = authStore.getServerUrl()
        val serverHost = runCatching { java.net.URI(serverUrl).host }.getOrNull()
            ?: throw IllegalArgumentException("Cannot determine server host from: $serverUrl")
        val downloadHost = runCatching { java.net.URI(url).host }.getOrNull()
            ?: throw IllegalArgumentException("Invalid OTA download URL (no host): $url")

        require(downloadHost == serverHost) {
            "SSRF protection: download host '$downloadHost' != server host '$serverHost'"
        }
    }

    private fun verifyChecksum(file: File, expectedSha256: String) {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(8192)
            var read: Int
            while (input.read(buffer).also { read = it } != -1) {
                digest.update(buffer, 0, read)
            }
        }
        val computed = digest.digest().joinToString("") { "%02x".format(it) }
        check(computed == expectedSha256) {
            "SHA-256 mismatch: expected=$expectedSha256, got=$computed"
        }
        Timber.i("OTA: SHA-256 verified ✓")
    }

    private fun install(apkFile: File) {
        if (tryRootInstall(apkFile)) {
            Timber.i("OTA: root install SUCCESS")
            return
        }
        Timber.w("OTA: root install failed, falling back to PackageInstaller")
        installViaPackageInstaller(apkFile)
    }

    private fun tryRootInstall(apkFile: File): Boolean {
        return try {
            val process = Runtime.getRuntime().exec(
                arrayOf("su", "-c", "pm install -r -t ${apkFile.absolutePath}")
            )
            // FIX C1: Таймаут 120с — pm install может быть долгим на слабых эмуляторах,
            // но бесконечное ожидание недопустимо (su может зависнуть)
            val finished = process.waitFor(120, TimeUnit.SECONDS)
            if (!finished) {
                process.destroyForcibly()
                Timber.e("OTA: root install timed out after 120s")
                return false
            }
            val exitCode = process.exitValue()
            val output = process.inputStream.bufferedReader().use { it.readText().take(1024) }
            Timber.d("Root install exit=$exitCode output=$output")
            exitCode == 0 && output.contains("Success")
        } catch (e: Exception) {
            Timber.w(e, "Root install exception")
            false
        }
    }

    private fun installViaPackageInstaller(apkFile: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(
            PackageInstaller.SessionParams.MODE_FULL_INSTALL
        )
        val sessionId = installer.createSession(params)

        installer.openSession(sessionId).use { session ->
            session.openWrite("package", 0, apkFile.length()).use { output ->
                apkFile.inputStream().use { input -> input.copyTo(output) }
                session.fsync(output)
            }

            val intent = Intent(context, InstallReceiver::class.java)
            val pi = PendingIntent.getBroadcast(
                context,
                sessionId,
                intent,
                PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            session.commit(pi.intentSender)
        }
    }
}
