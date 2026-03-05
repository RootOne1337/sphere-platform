package com.sphereplatform.agent.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import com.sphereplatform.agent.ws.SphereWebSocketClient
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * NetworkChangeHandler — мониторинг изменений сетевого подключения.
 *
 * При восстановлении сети вызывает [SphereWebSocketClient.forceReconnectNow],
 * прерывая текущий backoff delay для немедленного переподключения.
 *
 * Критично для сокращения downtime при переключении Wi-Fi/LTE на Яндокс/LDPlayer.
 */
@Singleton
class NetworkChangeHandler @Inject constructor(
    @ApplicationContext private val context: Context,
    private val wsClient: SphereWebSocketClient,
) {
    private var registered = false
    // FIX AUDIT-2.7: Сохраняем callback для корректной unregister()
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    fun register() {
        if (registered) return
        registered = true

        val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Timber.i("Network available — forcing WS reconnect")
                // FIX ARCH-7: не ждём backoff, reconnect немедленно
                if (!wsClient.isConnected) {
                    wsClient.forceReconnectNow()
                }
            }

            override fun onLost(network: Network) {
                Timber.w("Network lost — WS will receive onFailure automatically")
                // WebSocket получит onFailure/onClosed автоматически от OkHttp
            }
        }
        networkCallback = callback
        connectivityManager.registerNetworkCallback(request, callback)
    }

    /**
     * FIX AUDIT-2.7: Корректная отписка — вызывается из SphereAgentService.onDestroy.
     * Без этого NetworkCallback остаётся зарегистрированным → утечка ресурсов.
     */
    fun unregister() {
        if (!registered) return
        try {
            val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
            networkCallback?.let { connectivityManager.unregisterNetworkCallback(it) }
        } catch (e: Exception) {
            Timber.w(e, "NetworkChangeHandler: unregister failed")
        } finally {
            registered = false
            networkCallback = null
        }
    }
}
