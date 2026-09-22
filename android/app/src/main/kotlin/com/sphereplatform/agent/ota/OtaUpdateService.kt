package com.sphereplatform.agent.ota

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.net.ProtocolException
import java.net.SocketTimeoutException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException
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
 * - Staging filename generated locally; version metadata never selects a path
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
    private val updateMutex = Mutex()

    init {
        // Self-install replaces this process before finally can run. Hilt creates
        // one instance per agent process, before either OTA caller starts work.
        // Delete only our staging files; never recurse into application storage.
        runCatching {
            apkDir.listFiles { file ->
                file.isFile && file.name.startsWith("update_") && file.name.endsWith(".apk")
            }?.forEach { file ->
                if (file.delete()) Timber.i("OTA: removed abandoned staging file ${file.name}")
                else Timber.w("OTA: could not remove abandoned staging file ${file.name}")
            }
        }.onFailure { Timber.w(it, "OTA: abandoned staging cleanup failed") }
    }

    companion object {
        /**
         * FIX D6: Максимальный размер APK (200MB).
         * Защита от злоумышленного/взломанного сервера, который может вернуть
         * произвольно большой файл и заполнить /data на эмуляторе.
         */
        private const val MAX_APK_SIZE_BYTES = 200L * 1024 * 1024
    }

    suspend fun performUpdate(payload: OtaUpdatePayload) = withContext(Dispatchers.IO) {
        // Periodic checks and WebSocket commands share this singleton. Waiting
        // callers remain cancellable and cannot overwrite an installer's input.
        updateMutex.withLock {
            Timber.i("OTA: starting update → version=${payload.version}")
            check(apkDir.isDirectory || apkDir.mkdirs()) { "Cannot create OTA staging directory" }
            val apkFile = File.createTempFile("update_", ".apk", apkDir)
            try {
                downloadApk(payload, apkFile)
                verifyChecksum(apkFile, payload.sha256)
                currentCoroutineContext().ensureActive()
                install(apkFile)
            } finally {
                // Includes partial downloads, cancellation and failed installs.
                if (!apkFile.delete() && apkFile.exists()) Timber.w("OTA: staging cleanup failed")
                else Timber.d("OTA: APK deleted")
            }
        }
    }

    private suspend fun downloadApk(payload: OtaUpdatePayload, dest: File) = coroutineScope {
        // БЕЗОПАСНОСТЬ: SSRF-защита — скачиваем только с нашего сервера.
        validateDownloadUrl(payload.download_url)

        val request = Request.Builder()
            .url(payload.download_url)
            .header("Authorization", "Bearer ${authStore.getToken()}")
            .build()

        // A proxy can reset a large HTTP/2 body after returning headers. Retry
        // once over HTTP/1.1; outputStream() truncates any partial first attempt.
        val clients = listOf(
            httpClient,
            httpClient.newBuilder().protocols(listOf(Protocol.HTTP_1_1)).build(),
        )
        for ((attempt, client) in clients.withIndex()) {
            val call = client.newCall(request)
            // Blocking execute/read must be interrupted when WorkManager or the
            // command scope stops. A child observes cancellation while IO is blocked;
            // coroutineScope waits for the IO/writer to close before staging deletion.
            val cancellation = launch(start = CoroutineStart.UNDISPATCHED) {
                try { awaitCancellation() } finally { call.cancel() }
            }
            try {
                // FIX 7.2: response.use {} гарантирует закрытие при ошибках HTTP
                call.execute().use { response ->
                    check(response.isSuccessful) { "OTA download failed: ${response.code}" }
                    // FIX D6: Проверяем Content-Length перед скачиванием — защита от переполнения /data
                    val body = response.body ?: throw IOException("OTA response body missing")
                    val contentLength = body.contentLength()
                    if (contentLength > MAX_APK_SIZE_BYTES) {
                        throw IllegalStateException(
                            "OTA APK слишком большой: ${contentLength / (1024 * 1024)}MB > ${MAX_APK_SIZE_BYTES / (1024 * 1024)}MB"
                        )
                    }
                    body.byteStream().use { input ->
                        dest.outputStream().use { output ->
                            // FIX D6: Контроль размера при копировании (Content-Length может быть -1)
                            val buffer = ByteArray(8192)
                            var totalRead = 0L
                            var read: Int
                            while (input.read(buffer).also { read = it } != -1) {
                                currentCoroutineContext().ensureActive()
                                totalRead += read
                                if (totalRead > MAX_APK_SIZE_BYTES) {
                                    throw IllegalStateException(
                                        "OTA APK превысил лимит ${MAX_APK_SIZE_BYTES / (1024 * 1024)}MB при скачивании"
                                    )
                                }
                                output.write(buffer, 0, read)
                            }
                        }
                    }
                }
                Timber.i("OTA: downloaded ${dest.length()} bytes → ${dest.name}")
                return@coroutineScope
            } catch (error: IOException) {
                currentCoroutineContext().ensureActive()
                if (attempt == clients.lastIndex) throw error
                Timber.w(
                    "OTA: transport failure (${classifyTransportFailure(error)}); retrying once over HTTP/1.1",
                )
                delay(250L)
            } finally {
                cancellation.cancel()
            }
        }
    }

    private fun classifyTransportFailure(error: IOException): String = when {
        error is SSLException -> "tls_failure"
        error is ProtocolException || error.message.orEmpty().contains("PROTOCOL_ERROR", ignoreCase = true) ->
            "protocol_failure"
        error is SocketTimeoutException -> "timeout"
        else -> "io_failure"
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

    private suspend fun verifyChecksum(file: File, expectedSha256: String) {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(8192)
            var read: Int
            while (input.read(buffer).also { read = it } != -1) {
                currentCoroutineContext().ensureActive()
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
            // FIX F4: Экранирование пути — одинарные кавычки предотвращают
            // неожиданный shell splitting/globbing если путь содержит пробелы.
            // Путь контролируется агентом, но defensive coding обязателен.
            val safePath = apkFile.absolutePath.replace("'", "'\\''")
            val process = Runtime.getRuntime().exec(
                arrayOf("su", "-c", "pm install -r -t '$safePath'")
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
