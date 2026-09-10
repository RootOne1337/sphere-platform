package com.sphereplatform.agent.provisioning

import com.sphereplatform.agent.network.forManagementRoute
import com.sphereplatform.agent.network.normalizeManagementUrl
import com.sphereplatform.agent.store.AuthTokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import timber.log.Timber
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * DeviceRegistrationClient — автоматическая регистрация устройства на сервере.
 *
 * Вызывает POST /api/v1/devices/register с:
 * - X-API-Key: enrollment key (из конфига провижена)
 * - Body: fingerprint, device_type, meta-данные устройства
 *
 * Сервер:
 * - Новое устройство → создаёт запись, выдаёт JWT (access + refresh)
 * - Повторный вызов с тем же fingerprint → идемпотентно возвращает существующее + новые токены
 *
 * После успешной регистрации:
 * - Сохраняет device_id, access_token, refresh_token в AuthTokenStore
 * - Агент может подключиться к WebSocket с полученным JWT
 */
@Singleton
class DeviceRegistrationClient @Inject constructor(
    private val httpClient: OkHttpClient,
    private val authStore: AuthTokenStore,
    private val cloneDetector: CloneDetector,
    private val json: Json,
) {

    companion object {
        /** Bound HTTP (including callback body parsing), not device or preference IO. */
        private const val REGISTRATION_TIMEOUT_MS = 10_000L
        private const val MAX_RESPONSE_BYTES = 64 * 1024
    }

    /**
     * Результат регистрации устройства.
     */
    data class RegistrationResult(
        val deviceId: String,
        val name: String,
        val accessToken: String,
        val refreshToken: String,
        val expiresIn: Long,
        val serverUrl: String,
        val isNew: Boolean,
    )

    /**
     * Регистрирует устройство на сервере.
     *
     * @param serverUrl URL сервера (например, http://10.0.2.2:8000)
     * @param enrollmentApiKey API-ключ с правом device:register
     * @param workstationId ID рабочей станции (опционально, для LDPlayer)
     * @param instanceIndex индекс экземпляра эмулятора (опционально)
     * @param location локация (опционально, для auto-naming на сервере)
     * @return RegistrationResult с токенами и device_id
     * @throws RegistrationException при ошибке сервера
     */
    suspend fun register(
        serverUrl: String,
        enrollmentApiKey: String,
        workstationId: String? = null,
        instanceIndex: Int? = null,
        location: String? = null,
        fallbackServerUrl: String? = null,
    ): RegistrationResult = withContext(Dispatchers.IO) {
        val fingerprint = cloneDetector.getFingerprint()
        val deviceType = cloneDetector.getDeviceType()

        val bodyMap = buildMap<String, Any> {
            put("fingerprint", fingerprint)
            put("device_type", deviceType)
            put("android_version", android.os.Build.VERSION.RELEASE)
            put("model", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
            workstationId?.let { put("workstation_id", it) }
            instanceIndex?.let { put("instance_index", it) }
            location?.let { put("location", it) }
            put("meta", buildMap<String, Any> {
                put("sdk_int", android.os.Build.VERSION.SDK_INT)
                put("board", android.os.Build.BOARD)
                put("is_emulator", cloneDetector.isEmulator())
            })
        }

        val bodyJson = json.encodeToString(
            kotlinx.serialization.json.JsonObject.serializer(),
            toJsonObject(bodyMap),
        )

        Timber.d("DeviceRegistration: POST /api/v1/devices/register fingerprint=${fingerprint.take(16)}...")

        val request = Request.Builder()
            .url("${serverUrl.trimEnd('/')}/api/v1/devices/register")
            .header("X-API-Key", enrollmentApiKey)
            .header("Content-Type", "application/json")
            .post(bodyJson.toRequestBody("application/json".toMediaType()))
            .build()

        val reply = withTimeoutOrNull(REGISTRATION_TIMEOUT_MS) {
            currentCoroutineContext().ensureActive()
            val call = httpClient.forManagementRoute(serverUrl).newCall(request)
            call.timeout().timeout(REGISTRATION_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            suspendCancellableCoroutine<RegistrationReply> { continuation ->
                continuation.invokeOnCancellation { call.cancel() }
                call.enqueue(object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        continuation.resumeWithException(e)
                    }

                    override fun onResponse(call: Call, response: Response) {
                        val parsed = try {
                            response.use {
                                if (!continuation.isActive) return
                                readRegistrationReply(it, serverUrl)
                            }
                        } catch (e: Exception) {
                            continuation.resumeWithException(e)
                            return
                        }
                        // Return values only: a late callback never writes credentials.
                        continuation.resume(parsed)
                    }
                })
            }
        } ?: throw IOException("Registration HTTP timed out")

        // Parent cancellation propagates; our own HTTP deadline remains retryable.
        currentCoroutineContext().ensureActive()
        val result = reply.result
        authStore.saveServerRoutes(result.serverUrl, fallbackServerUrl ?: reply.advertisedUrl)
        authStore.saveDeviceId(result.deviceId)
        authStore.saveTokens(result.accessToken, result.refreshToken, result.expiresIn)

        Timber.i(
            "DeviceRegistration: %s device_id=%s name=%s",
            if (result.isNew) "REGISTERED NEW" else "RE-ENROLLED",
            result.deviceId,
            result.name,
        )
        result
    }

    private data class RegistrationReply(val result: RegistrationResult, val advertisedUrl: String?)

    private fun readRegistrationReply(response: Response, serverUrl: String): RegistrationReply {
        if (!response.isSuccessful) {
            // Retry classification needs the status, not a potentially stalled error body.
            throw RegistrationException("Ошибка регистрации: HTTP ${response.code}", response.code)
        }
        val source = response.body?.source() ?: throw IOException("Empty registration response")
        if (source.request(MAX_RESPONSE_BYTES.toLong() + 1)) throw IOException("Registration response too large")
        val jsonResponse = json.parseToJsonElement(source.readUtf8()).jsonObject
        val result = RegistrationResult(
            deviceId = jsonResponse["device_id"]!!.jsonPrimitive.content,
            name = jsonResponse["name"]!!.jsonPrimitive.content,
            accessToken = jsonResponse["access_token"]!!.jsonPrimitive.content,
            refreshToken = jsonResponse["refresh_token"]!!.jsonPrimitive.content,
            expiresIn = jsonResponse["expires_in"]!!.jsonPrimitive.long,
            serverUrl = normalizeManagementUrl(serverUrl),
            isNew = jsonResponse["is_new"]!!.jsonPrimitive.boolean,
        )
        // Keep the successful LAN request route; advertised public URL is a candidate.
        val advertised = jsonResponse["server_url"]?.jsonPrimitive?.content
            ?.let { runCatching { normalizeManagementUrl(it) }.getOrNull() }
            ?.takeIf { it != result.serverUrl }
        return RegistrationReply(result, advertised)
    }

    /**
     * Конвертирует Map в kotlinx.serialization JsonObject.
     */
    @Suppress("UNCHECKED_CAST")
    private fun toJsonObject(map: Map<String, Any>): JsonObject {
        val content = map.mapValues { (_, value) ->
            when (value) {
                is String -> kotlinx.serialization.json.JsonPrimitive(value)
                is Int -> kotlinx.serialization.json.JsonPrimitive(value)
                is Long -> kotlinx.serialization.json.JsonPrimitive(value)
                is Boolean -> kotlinx.serialization.json.JsonPrimitive(value)
                is Map<*, *> -> toJsonObject(value as Map<String, Any>)
                else -> kotlinx.serialization.json.JsonPrimitive(value.toString())
            }
        }
        return JsonObject(content)
    }
}

/**
 * Исключение при ошибке регистрации устройства.
 */
class RegistrationException(
    message: String,
    val httpCode: Int = 0,
    val responseBody: String? = null,
) : Exception(message)
