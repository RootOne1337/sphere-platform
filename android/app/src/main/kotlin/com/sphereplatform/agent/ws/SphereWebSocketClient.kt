package com.sphereplatform.agent.ws

import com.sphereplatform.agent.store.AuthTokenStore
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import javax.inject.Inject
import javax.inject.Singleton

/**
 * SphereWebSocketClient — stub для SPLIT-1.
 * Полная реализация в TZ-07 SPLIT-2 (WebSocket Client).
 */
@Singleton
class SphereWebSocketClient @Inject constructor(
    private val httpClient: OkHttpClient,
    private val authStore: AuthTokenStore,
    private val json: Json,
) {
    suspend fun connect(deviceId: String) {
        // TODO: SPLIT-2 — реализация WebSocket подключения к бэкенду
    }

    suspend fun disconnect() {
        // TODO: SPLIT-2 — корректное закрытие WebSocket соединения
    }
}
