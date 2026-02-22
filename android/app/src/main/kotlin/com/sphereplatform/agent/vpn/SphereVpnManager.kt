package com.sphereplatform.agent.vpn

import javax.inject.Inject
import javax.inject.Singleton

/**
 * SphereVpnManager — stub для TZ-06 (Stage 6 VPN).
 * Реальная реализация находится в ветке stage/6-vpn.
 * При merge stage/6-vpn → develop этот класс будет заменён полной реализацией.
 */
@Singleton
class SphereVpnManager @Inject constructor() {

    suspend fun connect(config: String) {
        // TODO: интеграция с TZ-06 AmneziaWG VPN manager
    }

    fun disconnect() {
        // TODO: интеграция с TZ-06
    }

    fun reconnect() {
        // TODO: интеграция с TZ-06
    }

    fun isActive(): Boolean = false
}
