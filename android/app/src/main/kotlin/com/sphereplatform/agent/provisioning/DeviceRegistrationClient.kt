package com.sphereplatform.agent.provisioning

import com.sphereplatform.agent.store.AuthTokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

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
        /** FIX D5: Максимальный размер ответа сервера при регистрации (защита от OOM). */
        private const val MAX_RESPONSE_CHARS = 64 * 1024
        /** Количество попыток регистрации (с exponential backoff). */
        private const val MAX_RETRIES = 3
        /** Начальная задержка перед retry (мс), удваивается при каждой попытке. */
        private const val INITIAL_RETRY_DELAY_MS = 2_000L
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
    ): RegistrationResult = withContext(Dispatchers.IO) {
        var lastException: Exception? = null

        for (attempt in 1..MAX_RETRIES) {
            try {
                return@withContext doRegister(
                    serverUrl, enrollmentApiKey, workstationId, instanceIndex, location,
                )
            } catch (e: RegistrationException) {
                // 4xx клиентские ошибки — повтор бессмысленен (кроме 429 Too Many Requests)
                if (e.httpCode in 400..499 && e.httpCode != 429) throw e
                lastException = e
            } catch (e: Exception) {
                // Сетевые ошибки (таймаут, DNS, connection refused) — пробуем ещё
                lastException = e
            }

            if (attempt < MAX_RETRIES) {
                val backoffMs = INITIAL_RETRY_DELAY_MS * (1L shl (attempt - 1))
                Timber.w(
                    "DeviceRegistration: попытка %d/%d не удалась, retry через %dмс: %s",
                    attempt, MAX_RETRIES, backoffMs, lastException?.message,
                )
                delay(backoffMs)
            }
        }

        Timber.e(lastException, "DeviceRegistration: все %d попыток исчерпаны", MAX_RETRIES)
        throw lastException ?: RegistrationException("Все попытки регистрации исчерпаны")
    }

    /**
     * Выполняет одну попытку регистрации устройства на сервере.
     */
    private suspend fun doRegister(
        serverUrl: String,
        enrollmentApiKey: String,
        workstationId: String? = null,
        instanceIndex: Int? = null,
        location: String? = null,
    ): RegistrationResult {
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

        httpClient.newCall(request).execute().use { response ->
            // FIX D5: Ограничиваем размер ответа (защита от OOM)
            val responseBody = response.body?.string()?.take(MAX_RESPONSE_CHARS)
                ?: throw RegistrationException("Пустой ответ сервера", response.code)

            if (!response.isSuccessful) {
                Timber.w("DeviceRegistration: HTTP ${response.code}: $responseBody")
                throw RegistrationException(
                    "Ошибка регистрации: HTTP ${response.code}",
                    response.code,
                    responseBody,
                )
            }

            val jsonResponse = json.parseToJsonElement(responseBody).jsonObject
            val result = RegistrationResult(
                deviceId = jsonResponse["device_id"]!!.jsonPrimitive.content,
                name = jsonResponse["name"]!!.jsonPrimitive.content,
                accessToken = jsonResponse["access_token"]!!.jsonPrimitive.content,
                refreshToken = jsonResponse["refresh_token"]!!.jsonPrimitive.content,
                expiresIn = jsonResponse["expires_in"]!!.jsonPrimitive.long,
                serverUrl = jsonResponse["server_url"]?.jsonPrimitive?.content ?: serverUrl,
                isNew = jsonResponse["is_new"]!!.jsonPrimitive.boolean,
            )

            // Сохраняем полученные данные в хранилище
            authStore.saveServerUrl(result.serverUrl)
            authStore.saveDeviceId(result.deviceId)
            authStore.saveTokens(result.accessToken, result.refreshToken, result.expiresIn)

            Timber.i(
                "DeviceRegistration: %s device_id=%s name=%s",
                if (result.isNew) "REGISTERED NEW" else "RE-ENROLLED",
                result.deviceId,
                result.name,
            )

            return result
        }
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
