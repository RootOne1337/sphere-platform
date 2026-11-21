package com.sphereplatform.agent.vpn

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Legacy firewall recovery only. Enabling a global OUTPUT/FORWARD switch is
 * prohibited because it can disconnect Sphere and native WebRTC. The future
 * app-scoped provider must implement selected-app fail-closed independently.
 */
@Singleton
class KillSwitchManager @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    @Volatile
    var isEnabled = false
        private set

    /** Global firewall activation is unavailable; recovery cleanup stays callable. */
    @Suppress("UNUSED_PARAMETER")
    suspend fun enable(
        vpnServerEndpoint: String,
        managementHosts: List<String> = emptyList(),
    ): Unit = withContext(Dispatchers.IO) {
        VpnExecutionPolicy.requireAppScopedProvider()
    }

    /**
     * Disable kill switch — restore normal traffic flow.
     */
    suspend fun disable() = withContext(Dispatchers.IO) {
        try {
            // Remove jump rules
            iptables("-D OUTPUT -j $CHAIN_NAME 2>/dev/null || true")
            iptables("-D FORWARD -j $CHAIN_NAME 2>/dev/null || true")

            // Flush and delete chain
            iptables("-F $CHAIN_NAME 2>/dev/null || true")
            iptables("-X $CHAIN_NAME 2>/dev/null || true")

            isEnabled = false
            Timber.i("Kill switch disabled")
        } catch (e: Exception) {
            Timber.e(e, "Failed to disable kill switch (may need manual cleanup)")
            isEnabled = false
        }
    }

    private companion object {
        const val CHAIN_NAME = "SPHERE_KILLSWITCH"
        /** Таймаут на одну iptables-команду через su. На слабых эмуляторах su может зависнуть. */
        const val ROOT_CMD_TIMEOUT_SECONDS = 30L
    }

    private fun iptables(args: String) {
        val process = Runtime.getRuntime().exec(arrayOf("su", "-c", "iptables $args"))
        // FIX C1: timeout — предотвращаем бесконечное зависание при stuck su-процессе
        val finished = process.waitFor(ROOT_CMD_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        if (!finished) {
            process.destroyForcibly()
            Timber.e("iptables $args → TIMEOUT after ${ROOT_CMD_TIMEOUT_SECONDS}s — процесс убит")
            return
        }
        val exitCode = process.exitValue()
        if (exitCode != 0) {
            val stderr = process.errorStream.bufferedReader().use { it.readText().take(500) }
            Timber.w("iptables $args → exit=$exitCode: $stderr")
        }
    }
}
