# SPLIT-5 — OTA Updates (Self-Update)

**ТЗ-родитель:** TZ-07-Android-Agent  
**Ветка:** `stage/7-android`  
**Задача:** `SPHERE-040`  
**Исполнитель:** Android  
**Оценка:** 1 день  
**Блокирует:** —
**Интеграция при merge:** TZ-08 PC Agent работает независимо; при merge согласовать OTA-протокол

---

## Цель Сплита

Получать команду OTA-обновления от сервера, скачивать APK с SHA-256 проверкой, устанавливать через PackageInstaller (root) или сессию UserInstall.

---

## Шаг 1 — OTA Command Payload

```kotlin
// AndroidAgent/ota/OtaUpdatePayload.kt
@Serializable
data class OtaUpdatePayload(
    val download_url: String,
    val version: String,
    val sha256: String,
    val force: Boolean = false,
)
```

---

## Шаг 2 — OtaUpdateService

```kotlin
// AndroidAgent/ota/OtaUpdateService.kt
@Singleton
class OtaUpdateService @Inject constructor(
    @ApplicationContext private val context: Context,
    private val httpClient: OkHttpClient,
    private val authStore: AuthTokenStore,
) {
    private val apkDir = File(context.filesDir, "ota")
    
    suspend fun performUpdate(payload: OtaUpdatePayload) {
        Timber.i("OTA: starting update to ${payload.version}")
        
        val apkFile = downloadApk(payload)
        verifyChecksum(apkFile, payload.sha256)
        install(apkFile)
    }
    
    private suspend fun downloadApk(payload: OtaUpdatePayload): File {
        apkDir.mkdirs()
        val dest = File(apkDir, "update_${payload.version}.apk")
        
        // Защита от path traversal
        val canonicalDest = dest.canonicalFile
        val canonicalDir = apkDir.canonicalFile
        check(canonicalDest.startsWith(canonicalDir)) { "Path traversal detected" }
        
        // БЕЗОПАСНОСТЬ: SSRF-защита — скачиваем только с нашего сервера.
        // Без этой проверки: сервер мог бы указать произвольный URL и получить
        // Bearer-токен пользователя на сторонний сервер.
        validateDownloadUrl(payload.download_url)
        
        // Загрузка с токеном (только с нашего сервера — проверено выше)
        val request = Request.Builder()
            .url(payload.download_url)
            .header("Authorization", "Bearer ${authStore.getToken()}")
            .build()
        
        withContext(Dispatchers.IO) {
            // FIX 7.2: БЫЛО — response.body!!.byteStream().use { ... }
            //   → response НЕ закрывался при ошибках HTTP!
            //   → Утечка TCP-соединений в OkHttp connection pool
            // СТАЛО — response.use {} гарантирует закрытие
            httpClient.newCall(request).execute().use { response ->
                check(response.isSuccessful) { "Download failed: ${response.code}" }
                
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
     * БЕЗОПАСНОСТЬ: SSRF-защита.
     * download_url должен указывать на тот же хост, что и сервер управления.
     * Защищает от утечки Bearer-токена на сторонний сервер.
     */
    private fun validateDownloadUrl(url: String) {
        val serverUrl = authStore.getServerUrl()
        val serverHost = runCatching { java.net.URI(serverUrl).host }.getOrNull()
            ?: throw IllegalArgumentException("Cannot determine server host from: $serverUrl")
        val downloadHost = runCatching { java.net.URI(url).host }.getOrNull()
            ?: throw IllegalArgumentException("Invalid download URL (no host): $url")
        require(downloadHost == serverHost) {
            "SSRF protection: download host '$downloadHost' != server host '$serverHost'"
        }
        require(url.startsWith("https://")) {
            "OTA download must use HTTPS, got: $url"
        }
    }
    
    private fun verifyChecksum(file: File, expectedSha256: String) {
        val digest = MessageDigest.getInstance("SHA-256")
        val computed = file.inputStream().use { input ->
            val buffer = ByteArray(8192)
            var read: Int
            while (input.read(buffer).also { read = it } != -1) {
                digest.update(buffer, 0, read)
            }
            digest.digest().joinToString("") { "%02x".format(it) }
        }
        
        check(computed == expectedSha256) {
            "SHA-256 mismatch: expected=$expectedSha256, got=$computed"
        }
        
        Timber.i("OTA: SHA-256 verified ✓")
    }
    
    private fun install(apkFile: File) {
        // Попытка root-установки (тихая, LDPlayer / KernelSU)
        if (tryRootInstall(apkFile)) return
        
        // Fallback — PackageInstaller (требует подтверждения пользователя,
        // но на Android 11+ можно с INSTALL_PACKAGES + FLAG_REQUEST_UPDATE)
        installViaPackageInstaller(apkFile)
    }
    
    private fun tryRootInstall(apkFile: File): Boolean {
        val process = Runtime.getRuntime().exec(
            arrayOf("su", "-c", "pm install -r -t ${apkFile.absolutePath}")
        )
        val exitCode = process.waitFor()
        val output = process.inputStream.bufferedReader().readText()
        Timber.d("Root install exit=$exitCode output=$output")
        return exitCode == 0 && output.contains("Success")
    }
    
    private fun installViaPackageInstaller(apkFile: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        val sessionId = installer.createSession(params)
        
        installer.openSession(sessionId).use { session ->
            session.openWrite("package", 0, apkFile.length()).use { output ->
                apkFile.inputStream().use { input ->
                    input.copyTo(output)
                }
            }
            
            val intent = Intent(context, InstallReceiver::class.java)
            val pi = PendingIntent.getBroadcast(context, 0, intent, PendingIntent.FLAG_MUTABLE)
            session.commit(pi.intentSender)
        }
    }
}

// AndroidAgent/ota/InstallReceiver.kt
class InstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -1)
        if (status == PackageInstaller.STATUS_SUCCESS) {
            Timber.i("OTA: install SUCCESS, restarting…")
        } else {
            val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
            Timber.e("OTA: install FAILED status=$status: $msg")
        }
    }
}
```

---

## Шаг 3 — CommandDispatcher integration

```kotlin
// В CommandDispatcher.dispatch() добавить case:
CommandType.OTA_UPDATE -> {
    val otaPayload = json.decodeFromJsonElement<OtaUpdatePayload>(cmd.payload)
    otaUpdateService.performUpdate(otaPayload)
    buildJsonObject { put("status", "download_complete") }
}
```

---

## Шаг 4 — AndroidManifest

```xml
<!-- AndroidManifest.xml -->
<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />
<uses-permission android:name="android.permission.INSTALL_PACKAGES" />

<receiver
    android:name=".ota.InstallReceiver"
    android:exported="false" />
```

---

## Критерии готовности

- [ ] SHA-256 mismatch → exception, файл удаляется, ack "failed"
- [ ] Path traversal check: canonicalFile за пределами otaDir → exception
- [ ] **SSRF-защита**: `validateDownloadUrl()` — хост URL == хост сервера управления (authStore.getServerUrl())
- [ ] OTA download только по HTTPS
- [ ] Root install: `pm install -r` — тихая установка без UI
- [ ] Fallback PackageInstaller Sessions API работает на API 26+
- [ ] Загрузка только с Bearer токеном (не открытый URL)
- [ ] APK-файл удаляется после успешной/неуспешной установки
