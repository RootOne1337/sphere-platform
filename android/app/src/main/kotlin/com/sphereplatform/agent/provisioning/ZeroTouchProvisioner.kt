package com.sphereplatform.agent.provisioning

import android.content.Context
import android.content.RestrictionsManager
import android.os.Environment
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.network.FallbackDns
import dagger.hilt.android.qualifiers.ApplicationContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import timber.log.Timber
import java.io.File
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * ZeroTouchProvisioner — автоматическое обнаружение конфигурации агента.
 *
 * Цепочка приоритетов (первый успешный источник выигрывает):
 *  1. Android Enterprise Managed Config (RestrictionsManager) — MDM/EMM политика
 *  2. Файл /sdcard/sphere-agent-config.json     — лёгкий adb push target
 *  3. Файл <appExternalFiles>/sphere-agent-config.json
 *  4. Файл <appInternalFiles>/sphere-agent-config.json
 *  5. HTTP Config Endpoint (GET BuildConfig.CONFIG_URL) — server auto-discovery
 *  6. BuildConfig.DEFAULT_SERVER_URL + DEFAULT_API_KEY — baked-in defaults (fallback)
 *
 * Для эмулятора:
 *   server_url = "http://10.0.2.2"  (Android эмулятор → host-машина loopback)
 *   Запустить после adb push:
 *     adb push sphere-agent-config.json /sdcard/sphere-agent-config.json
 *
 * Формат JSON-файла:
 * {
 *   "server_url": "http://10.0.2.2",
 *   "api_key": "your-api-key",
 *   "device_id": "optional-device-id"
 * }
 *
 * Managed Config ключи (для MDM/EMM политик):
 *   sphere_server_url, sphere_api_key, sphere_device_id
 *
 * HTTP Config Endpoint ответ:
 * {
 *   "server_url": "http://10.0.2.2:8000",
 *   "enrollment_allowed": true,
 *   "auto_register": true,
 *   "environment": "development"
 * }
 */
@Singleton
class ZeroTouchProvisioner @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    /**
     * Лёгкий HTTP-клиент для config endpoint (без авторизации, короткие таймауты).
     * Не использует основной OkHttpClient чтобы избежать circular dependency с AuthTokenStore.
     */
    private val configHttpClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            // FIX DNS: fallback на Google/Cloudflare DNS + DoH для эмуляторов
            .dns(FallbackDns())
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            // FIX: автоматический retry при обрыве TCP (connection reset, timeout)
            .retryOnConnectionFailure(true)
            .build()
    }

    companion object {
        /** FIX D5: Максимальный размер конфиг-файла/HTTP-ответа (защита от OOM). */
        private const val MAX_CONFIG_CHARS = 64 * 1024  // 64KB
    }

    data class ProvisionConfig(
        val serverUrl: String,
        val apiKey: String,
        val deviceId: String? = null,
        val source: String = "unknown",
        /** Флаг: сервер поддерживает auto_register → агент должен вызвать POST /devices/register */
        val autoRegisterEnabled: Boolean = false,
    )

    /**
     * Результат запроса к HTTP Config Endpoint.
     * Содержит server_url и enrollment_api_key для дальнейшего обнаружения.
     */
    data class ServerConfig(
        val serverUrl: String,
        val environment: String,
        val autoRegister: Boolean,
        val enrollmentAllowed: Boolean,
        val enrollmentApiKey: String?,
        val wsPath: String,
        val configPollIntervalSeconds: Int,
    )

    fun discoverConfig(): ProvisionConfig? {
        discoverFromManagedConfig()?.let {
            Timber.i("ZeroTouch: enrolled from Managed Config (MDM/EMM)")
            return it
        }
        discoverFromLocalFile()?.let {
            Timber.i("ZeroTouch: enrolled from local file [${it.source}]")
            return it
        }
        // HTTP Config Endpoint проверяется ПЕРЕД BuildConfig:
        // Cloudflare Quick Tunnel даёт новый URL при каждом рестарте,
        // поэтому динамический конфиг всегда приоритетнее захардкоженных defaults.
        discoverFromConfigEndpoint()?.let {
            Timber.i("ZeroTouch: discovered server via HTTP Config Endpoint")
            return it
        }
        discoverFromBuildConfig()?.let {
            Timber.i("ZeroTouch: enrolled from BuildConfig (flavor=${BuildConfig.FLAVOR_LABEL})")
            return it
        }
        Timber.d("ZeroTouch: no auto-provision config found — manual enrollment required")
        return null
    }

    /**
     * Запрашивает актуальную конфигурацию с сервера.
     * Используется при первом запуске и периодически для обнаружения смены server_url.
     *
     * @param apiKey опциональный API-ключ для получения org-scoped конфига
     * @return ServerConfig или null при ошибке
     */
    fun fetchServerConfig(apiKey: String? = null): ServerConfig? {
        val configUrl = BuildConfig.CONFIG_URL.takeIf { it.isNotBlank() } ?: return null
        return runCatching {
            val requestBuilder = Request.Builder().url(configUrl)
            apiKey?.let { requestBuilder.header("X-API-Key", it) }
            val request = requestBuilder.build()

            configHttpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Timber.w("ZeroTouch: config endpoint HTTP ${response.code}")
                    return@runCatching null
                }
                val body = response.body?.string()?.take(MAX_CONFIG_CHARS) ?: return@runCatching null
                val json = JSONObject(body)
                ServerConfig(
                    serverUrl = json.getString("server_url"),
                    environment = json.optString("environment", "unknown"),
                    autoRegister = json.optJSONObject("features")?.optBoolean("auto_register", false) ?: false,
                    enrollmentAllowed = json.optBoolean("enrollment_allowed", false),
                    enrollmentApiKey = json.optString("enrollment_api_key", "").takeIf { it.isNotBlank() },
                    wsPath = json.optString("ws_path", "/ws/android"),
                    configPollIntervalSeconds = json.optInt("config_poll_interval_seconds", 86400),
                )
            }
        }.getOrElse { e ->
            Timber.w(e, "ZeroTouch: failed to fetch config from endpoint")
            null
        }
    }

    // ── 1. Android Enterprise Managed Config (MDM push) ─────────────────────

    private fun discoverFromManagedConfig(): ProvisionConfig? = runCatching {
        val rm = context.getSystemService(Context.RESTRICTIONS_SERVICE) as? RestrictionsManager
            ?: return@runCatching null
        val bundle = rm.applicationRestrictions ?: return@runCatching null
        val serverUrl = bundle.getString("sphere_server_url")?.takeIf { it.isNotBlank() }
            ?: return@runCatching null
        val apiKey = bundle.getString("sphere_api_key")?.takeIf { it.isNotBlank() }
            ?: return@runCatching null
        ProvisionConfig(
            serverUrl = serverUrl,
            apiKey = apiKey,
            deviceId = bundle.getString("sphere_device_id")?.takeIf { it.isNotBlank() },
            source = "managed_config",
        )
    }.getOrNull()

    // ── 2‑4. JSON config file (multiple search paths) ───────────────────────

    private fun discoverFromLocalFile(): ProvisionConfig? {
        val searchPaths = buildList<File> {
            // /sdcard/sphere-agent-config.json — most accessible for adb push
            runCatching { Environment.getExternalStorageDirectory() }
                .getOrNull()?.let { add(File(it, "sphere-agent-config.json")) }
            // App external files dir — no MANAGE_EXTERNAL_STORAGE needed
            context.getExternalFilesDir(null)?.let { add(File(it, "sphere-agent-config.json")) }
            // Internal app storage — most secure, survives uninstall on some OEMs
            add(File(context.filesDir, "sphere-agent-config.json"))
        }
        for (file in searchPaths) {
            if (!file.exists()) continue
            runCatching {
                // FIX D5: Ограничиваем размер чтения файла (злонамеренный файл на /sdcard → OOM)
                val json = JSONObject(file.readText(Charsets.UTF_8).take(MAX_CONFIG_CHARS))
                val serverUrl = json.getString("server_url").takeIf { it.isNotBlank() }
                    ?: return@runCatching null
                val apiKey = json.getString("api_key").takeIf { it.isNotBlank() }
                    ?: return@runCatching null
                ProvisionConfig(
                    serverUrl = serverUrl,
                    apiKey = apiKey,
                    deviceId = json.optString("device_id").takeIf { it.isNotBlank() },
                    source = "file:${file.absolutePath}",
                )
            }.getOrElse { e ->
                Timber.w(e, "ZeroTouch: failed to parse config from ${file.absolutePath}")
                null
            }?.let { return it }
        }
        return null
    }

    // ── 5. BuildConfig baked-in defaults ────────────────────────────────────

    private fun discoverFromBuildConfig(): ProvisionConfig? {
        val url = BuildConfig.DEFAULT_SERVER_URL.takeIf { it.isNotBlank() } ?: return null
        val key = BuildConfig.DEFAULT_API_KEY.takeIf { it.isNotBlank() } ?: return null
        return ProvisionConfig(
            serverUrl = url,
            apiKey = key,
            deviceId = BuildConfig.DEFAULT_DEVICE_ID.takeIf { it.isNotBlank() },
            source = "buildconfig:${BuildConfig.FLAVOR_LABEL}",
        )
    }

    // ── 6. HTTP Config Endpoint (GET /api/v1/config/agent) ──────────────────

    /**
     * Запрашивает server_url через HTTP Config Endpoint.
     * Если auto_register включён → возвращает ProvisionConfig без API-ключа,
     * сигнализируя SetupActivity вызвать auto-registration flow.
     *
     * Это последний fallback: если MDM, файлы и BuildConfig не дали результата,
     * агент обращается к серверу напрямую для bootstrap.
     */
    private fun discoverFromConfigEndpoint(): ProvisionConfig? {
        val serverConfig = fetchServerConfig() ?: return null
        // Config endpoint возвращает enrollment_api_key для zero-touch регистрации.
        // Если ключ есть — агент может сразу вызвать POST /devices/register.
        val apiKey = serverConfig.enrollmentApiKey ?: ""
        return ProvisionConfig(
            serverUrl = serverConfig.serverUrl,
            apiKey = apiKey,
            source = "config_endpoint",
            autoRegisterEnabled = serverConfig.autoRegister,
        )
    }
}
