package com.sphereplatform.agent.provisioning

import android.content.Context
import android.content.RestrictionsManager
import android.os.Environment
import com.sphereplatform.agent.BuildConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import org.json.JSONObject
import timber.log.Timber
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * ZeroTouchProvisioner — автоматическое обнаружение конфигурации агента.
 *
 * Цепочка приоритетов (первый успешный источник выигрывает):
 *  1. Android Enterprise Managed Config (RestrictionsManager) — MDM/EMM politika
 *  2. Файл /sdcard/sphere-agent-config.json     — lёgkiy adb push target
 *  3. Файл <appExternalFiles>/sphere-agent-config.json
 *  4. Файл <appInternalFiles>/sphere-agent-config.json
 *  5. BuildConfig.DEFAULT_SERVER_URL + DEFAULT_API_KEY — baked-in defaults
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
 */
@Singleton
class ZeroTouchProvisioner @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    data class ProvisionConfig(
        val serverUrl: String,
        val apiKey: String,
        val deviceId: String? = null,
        val source: String = "unknown",
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
        discoverFromBuildConfig()?.let {
            Timber.i("ZeroTouch: enrolled from BuildConfig (flavor=${BuildConfig.FLAVOR_LABEL})")
            return it
        }
        Timber.d("ZeroTouch: no auto-provision config found — manual enrollment required")
        return null
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
                val json = JSONObject(file.readText(Charsets.UTF_8))
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
}
