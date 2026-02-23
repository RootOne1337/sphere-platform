package com.sphereplatform.agent.vpn

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * KillSwitchManager — TZ-06 SPLIT-4.
 *
 * Ensures all traffic is blocked when VPN tunnel drops unexpectedly.
 * Uses iptables rules (requires root) to drop non-tunnel traffic.
 *
 * Chain: SPHERE_KILLSWITCH
 *  - Allow loopback
 *  - Allow traffic through VPN interface (sphere0)
 *  - Allow DHCP (UDP 67-68) for initial connectivity
 *  - Allow DNS to VPN server for tunnel re-establishment
 *  - DROP everything else
 */
@Singleton
class KillSwitchManager @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    @Volatile
    var isEnabled = false
        private set

    private companion object {
        const val CHAIN_NAME = "SPHERE_KILLSWITCH"
        const val VPN_INTERFACE = "sphere0"
    }

    /**
     * Enable kill switch — blocks all non-VPN traffic.
     * @param vpnServerEndpoint WireGuard server endpoint (host:port) to allow through.
     */
    suspend fun enable(vpnServerEndpoint: String) = withContext(Dispatchers.IO) {
        try {
            val serverHost = vpnServerEndpoint.substringBefore(":")

            // Create chain
            iptables("-N $CHAIN_NAME 2>/dev/null || true")
            iptables("-F $CHAIN_NAME")

            // Allow loopback
            iptables("-A $CHAIN_NAME -o lo -j ACCEPT")
            iptables("-A $CHAIN_NAME -i lo -j ACCEPT")

            // Allow established connections on VPN interface
            iptables("-A $CHAIN_NAME -o $VPN_INTERFACE -j ACCEPT")
            iptables("-A $CHAIN_NAME -i $VPN_INTERFACE -j ACCEPT")

            // Allow traffic to VPN server (for tunnel establishment/maintenance)
            iptables("-A $CHAIN_NAME -d $serverHost -j ACCEPT")

            // Allow DHCP
            iptables("-A $CHAIN_NAME -p udp --dport 67:68 -j ACCEPT")

            // Drop everything else
            iptables("-A $CHAIN_NAME -j DROP")

            // Insert chain into OUTPUT and FORWARD
            iptables("-I OUTPUT 1 -j $CHAIN_NAME")
            iptables("-I FORWARD 1 -j $CHAIN_NAME")

            isEnabled = true
            Timber.i("Kill switch enabled, allowing only $serverHost + $VPN_INTERFACE")
        } catch (e: Exception) {
            Timber.e(e, "Failed to enable kill switch")
            // Attempt cleanup on failure
            disable()
            throw e
        }
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

    private fun iptables(args: String) {
        val process = Runtime.getRuntime().exec(arrayOf("su", "-c", "iptables $args"))
        val exitCode = process.waitFor()
        if (exitCode != 0) {
            val stderr = process.errorStream.bufferedReader().readText()
            Timber.w("iptables $args → exit=$exitCode: $stderr")
        }
    }
}
