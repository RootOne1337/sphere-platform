package com.sphereplatform.agent.provisioning

import android.content.Context
import android.content.RestrictionsManager
import android.os.Environment
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.network.FallbackDns
import com.sphereplatform.agent.network.normalizeManagementUrl
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

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
class ZeroTouchProvisioner internal constructor(
    private val context: Context,
    private val configUrl: String,
    private val mirrorUrls: List<String>,
    private val signedDiscovery: SignedDiscovery?,
    clientFactory: () -> OkHttpClient,
) {
    internal constructor(context: Context, configUrl: String, clientFactory: () -> OkHttpClient) :
        this(context, configUrl, emptyList(), null, clientFactory)

    internal constructor(context: Context, configUrl: String, mirrors: List<String>, clientFactory: () -> OkHttpClient) :
        this(context, configUrl, mirrors, null, clientFactory)

    @Inject constructor(@ApplicationContext context: Context) : this(
        context, BuildConfig.CONFIG_URL, BuildConfig.CONFIG_MIRROR_URLS.split(','),
        configuredSignedDiscovery(context), { createConfigHttpClient() },
    )

    /**
     * Лёгкий HTTP-клиент для config endpoint (без авторизации, короткие таймауты).
     * Не использует основной OkHttpClient чтобы избежать circular dependency с AuthTokenStore.
     */
    private val configHttpClient: OkHttpClient by lazy(clientFactory)

    companion object {
        /** HTTP is bounded before parsing; the legacy file path truncates characters after reading. */
        private const val MAX_CONFIG_CHARS = 64 * 1024  // 64KB
        private const val CONFIG_TIMEOUT_MS = 10_000L

        private fun configuredSignedDiscovery(context: Context): SignedDiscovery? {
            if (BuildConfig.DISCOVERY_PUBLIC_KEY.isBlank()) return null
            val urls = (listOf(BuildConfig.CONFIG_URL) + BuildConfig.CONFIG_MIRROR_URLS.split(','))
                .map { it.trim() }.filter { it.isNotEmpty() }.distinct()
            return SignedDiscovery(urls, SignedManifestVerifier(BuildConfig.DISCOVERY_INSTALLATION_ID,
                mapOf(BuildConfig.DISCOVERY_KEY_ID to BuildConfig.DISCOVERY_PUBLIC_KEY)),
                AtomicDiscoveryCache(File(context.filesDir, "signed-discovery.json")))
        }

        private fun createConfigHttpClient(): OkHttpClient = OkHttpClient.Builder()
            // FIX: FallbackDns — DNS-over-HTTPS для резолвинга на LDPlayer headless
            .dns(FallbackDns())
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()
    }

    data class ProvisionConfig(
        val serverUrl: String,
        val apiKey: String,
        val deviceId: String? = null,
        val source: String = "unknown",
        /** Флаг: сервер поддерживает auto_register → агент должен вызвать POST /devices/register */
        val autoRegisterEnabled: Boolean = false,
        val fallbackServerUrl: String? = null,
    ) {
        /** Only an explicitly assigned UUID can use the legacy static-key path. */
        val requiresRegistration: Boolean
            get() = autoRegisterEnabled || deviceId == null || !runCatching {
                java.util.UUID.fromString(deviceId).toString().equals(deviceId, ignoreCase = true)
            }.getOrDefault(false)
    }

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
        val fallbackServerUrl: String? = null,
        val verifiedInstallation: Boolean = false,
    )

    suspend fun discoverConfig(): ProvisionConfig? {
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
        // Strict discovery must never downgrade to an unsigned/baked HTTP route.
        if (signedDiscovery != null) return null
        discoverFromBuildConfig()?.let {
            Timber.i("ZeroTouch: enrolled from BuildConfig (flavor=${BuildConfig.FLAVOR_LABEL})")
            return it
        }
        Timber.d("ZeroTouch: no auto-provision config found — manual enrollment required")
        return null
    }

    /** Local route provisioning can be reapplied at service start without enrollment or HTTP. */
    internal fun discoverLocalConfig(): ProvisionConfig? =
        discoverFromManagedConfig(requireKey = false) ?: discoverFromLocalFile(requireKey = false)

    private val configUrls: List<String> = (listOf(configUrl) + mirrorUrls)
        .map { it.trim() }.filter { it.isNotEmpty() }.distinct().take(3)

    val hasConfigEndpoint: Boolean get() = configUrls.isNotEmpty() || signedDiscovery != null

    /**
     * Запрашивает актуальную конфигурацию с сервера.
     * Используется при первом запуске и периодически для обнаружения смены server_url.
     *
     * Публичный discovery не отправляет device/enrollment credentials на config host.
     * HTTP deadline и parent cancellation отменяют конкретный Call.
     * @return ServerConfig или null при ошибке
     */
    suspend fun fetchServerConfig(): ServerConfig? {
        if (signedDiscovery != null) {
            return try {
                signedDiscovery.fetch(::fetchConfigJson)?.let { verified -> ServerConfig(
                    serverUrl = verified.serverUrl, fallbackServerUrl = verified.fallbackServerUrl,
                    environment = "signed", autoRegister = true, enrollmentAllowed = false,
                    enrollmentApiKey = null, wsPath = "/ws/android", configPollIntervalSeconds = 120,
                    verifiedInstallation = true,
                ) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                Timber.w("ZeroTouch: signed discovery unavailable (%s)", e.javaClass.simpleName)
                null
            }
        }
        // Legacy explicitly configured sources retain the existing JSON contract.
        val perSourceBudget = CONFIG_TIMEOUT_MS / configUrls.size.coerceAtLeast(1)
        for (url in configUrls) {
            val json = fetchConfigJson(url, perSourceBudget) ?: continue
            try { return readServerConfig(json) }
            catch (e: Exception) { Timber.w("ZeroTouch: config rejected (%s)", e.javaClass.simpleName) }
        }
        return null
    }

    private suspend fun fetchConfigJson(url: String, timeoutMs: Long): JSONObject? {
        return try {
            withTimeoutOrNull(timeoutMs) {
                val request = Request.Builder().url(url).header("Accept", "application/json").build()
                val call = configHttpClient.newCall(request)
                call.timeout().timeout(timeoutMs, TimeUnit.MILLISECONDS)
                suspendCancellableCoroutine<JSONObject> { continuation ->
                    continuation.invokeOnCancellation { call.cancel() }
                    call.enqueue(object : Callback {
                        override fun onFailure(call: Call, e: IOException) {
                            continuation.resumeWithException(e)
                        }

                        override fun onResponse(call: Call, response: Response) {
                            val config = try {
                                response.use {
                                    if (!continuation.isActive) return
                                    readConfigJson(it)
                                }
                            } catch (e: Exception) {
                                continuation.resumeWithException(e)
                                return
                            }
                            // Values only: a late response never writes the selected route.
                            continuation.resume(config)
                        }
                    })
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w("ZeroTouch: config fetch failed (%s)", e.javaClass.simpleName)
            null
        }
    }

    private fun readConfigJson(response: Response): JSONObject {
        check(response.isSuccessful) { "Config HTTP ${response.code}" }
        val source = response.body?.source() ?: error("Missing config body")
        check(!source.request(MAX_CONFIG_CHARS.toLong() + 1)) { "Config response too large" }
        return JSONObject(source.readUtf8())
    }

    private fun readServerConfig(json: JSONObject): ServerConfig {
        val serverUrl = json.getString("server_url").trim().trimEnd('/')
        val parsedUrl = serverUrl.toHttpUrlOrNull() ?: error("Invalid config server URL")
        check(parsedUrl.username.isEmpty() && parsedUrl.password.isEmpty() &&
            parsedUrl.query == null && parsedUrl.fragment == null) { "Invalid config server URL" }
        return ServerConfig(
            serverUrl = serverUrl,
            environment = json.optString("environment", "unknown"),
            autoRegister = json.optJSONObject("features")?.optBoolean("auto_register", false) ?: false,
            enrollmentAllowed = json.optBoolean("enrollment_allowed", false),
            enrollmentApiKey = json.nonBlankString("enrollment_api_key"),
            wsPath = json.optString("ws_path", "/ws/android"),
            configPollIntervalSeconds = json.optInt("config_poll_interval_seconds", 86400),
            fallbackServerUrl = if (json.isNull("fallback_server_url")) null else
                json.optString("fallback_server_url").takeIf { it.isNotBlank() }?.let(::normalizeManagementUrl),
        )
    }

    // ── 1. Android Enterprise Managed Config (MDM push) ─────────────────────

    private fun discoverFromManagedConfig(requireKey: Boolean = true): ProvisionConfig? = runCatching {
        val rm = context.getSystemService(Context.RESTRICTIONS_SERVICE) as? RestrictionsManager
            ?: return@runCatching null
        val bundle = rm.applicationRestrictions ?: return@runCatching null
        val serverUrl = bundle.getString("sphere_server_url")?.takeIf { it.isNotBlank() }
            ?: return@runCatching null
        val apiKey = bundle.getString("sphere_api_key")?.takeIf { it.isNotBlank() } ?: ""
        if (requireKey && apiKey.isBlank()) return@runCatching null
        ProvisionConfig(
            serverUrl = serverUrl,
            apiKey = apiKey,
            deviceId = bundle.getString("sphere_device_id")?.takeIf { it.isNotBlank() },
            source = "managed_config",
            fallbackServerUrl = bundle.getString("sphere_fallback_server_url")?.takeIf { it.isNotBlank() }
                ?.let(::normalizeManagementUrl),
        )
    }.getOrNull()

    // ── 2‑4. JSON config file (multiple search paths) ───────────────────────

    private fun discoverFromLocalFile(requireKey: Boolean = true): ProvisionConfig? {
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
                val apiKey = json.nonBlankString("api_key") ?: json.nonBlankString("enrollment_api_key") ?: ""
                if (requireKey && apiKey.isBlank()) return@runCatching null
                ProvisionConfig(
                    serverUrl = serverUrl,
                    apiKey = apiKey,
                    deviceId = json.nonBlankString("device_id"),
                    source = "file:${file.absolutePath}",
                    autoRegisterEnabled = json.optJSONObject("features")?.optBoolean("auto_register", false) ?: false,
                    fallbackServerUrl = if (json.isNull("fallback_server_url")) null else
                        json.optString("fallback_server_url").takeIf { it.isNotBlank() }?.let(::normalizeManagementUrl),
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
            fallbackServerUrl = BuildConfig.DEFAULT_FALLBACK_SERVER_URL.takeIf { it.isNotBlank() },
        )
    }

    // ── 6. HTTP Config Endpoint (GET /api/v1/config/agent) ──────────────────

    /**
     * Запрашивает server_url через HTTP Config Endpoint.
     * Returns the selected routes together with their bound enrollment credential.
     * Callers must not fetch another document to obtain a key for this route.
     *
     * MDM и локальные файлы имеют приоритет; HTTP проверяется перед BuildConfig.
     */
    private suspend fun discoverFromConfigEndpoint(): ProvisionConfig? {
        val serverConfig = fetchServerConfig() ?: return null
        // Public discovery can contain routes only. A baked credential may be
        // reused only for one of its explicitly provisioned installation routes.
        val baked = discoverFromBuildConfig()?.takeIf { config ->
            normalizeManagementUrl(serverConfig.serverUrl) in
                listOfNotNull(config.serverUrl, config.fallbackServerUrl).map(::normalizeManagementUrl)
        }
        val apiKey = if (serverConfig.verifiedInstallation) BuildConfig.DEFAULT_API_KEY else
            serverConfig.enrollmentApiKey ?: baked?.apiKey ?: ""
        val fallback = if (!serverConfig.verifiedInstallation && serverConfig.enrollmentApiKey == null && baked != null) {
            listOfNotNull(baked.serverUrl, baked.fallbackServerUrl)
                .map(::normalizeManagementUrl).firstOrNull { it != normalizeManagementUrl(serverConfig.serverUrl) }
        } else serverConfig.fallbackServerUrl
        return ProvisionConfig(
            serverUrl = serverConfig.serverUrl,
            apiKey = apiKey,
            source = "config_endpoint",
            autoRegisterEnabled = serverConfig.autoRegister,
            fallbackServerUrl = fallback,
        )
    }

    private fun JSONObject.nonBlankString(name: String): String? =
        (opt(name) as? String)?.takeIf { it.isNotBlank() }
}
