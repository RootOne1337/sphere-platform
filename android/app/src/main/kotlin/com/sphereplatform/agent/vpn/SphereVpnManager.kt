package com.sphereplatform.agent.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.io.File
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * SphereVpnManager — AmneziaWG VPN tunnel management (TZ-06).
 *
 * Manages WireGuard-compatible tunnels via `wg-quick` userspace tool
 * (requires root or VpnService fallback). Stores config in app-private dir,
 * monitors tunnel state via interface check, supports auto-reconnect.
 */
@Singleton
class SphereVpnManager @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val mutex = Mutex()
    private val configDir = File(context.filesDir, "vpn")

    @Volatile
    private var activeTunnelName: String? = null

    @Volatile
    private var tunnelActive = false

    init {
        configDir.mkdirs()
    }

    /**
     * Activates VPN tunnel with the given WireGuard config text.
     * Config is written to app-private storage, then wg-quick is invoked.
     */
    suspend fun connect(config: String) = mutex.withLock {
        withContext(Dispatchers.IO) {
            try {
                // Tear down existing tunnel if any
                bringDownTunnel()

                // Write config to disk
                val configFile = File(configDir, CONFIG_FILE)
                configFile.writeText(config)
                configFile.setReadable(false, false)
                configFile.setReadable(true, true)

                // Bring up tunnel
                bringUpTunnel(configFile)

                activeTunnelName = TUNNEL_NAME
                tunnelActive = true
                Timber.i("VPN tunnel $TUNNEL_NAME connected")
            } catch (e: Exception) {
                tunnelActive = false
                activeTunnelName = null
                Timber.e(e, "VPN connect failed")
                throw e
            }
        }
    }

    fun disconnect() {
        try {
            bringDownTunnel()
            tunnelActive = false
            activeTunnelName = null
            Timber.i("VPN tunnel disconnected")
        } catch (e: Exception) {
            Timber.e(e, "VPN disconnect failed")
        } finally {
            cleanupConfig()
        }
    }

    /**
     * Reconnect with exponential backoff. Used when stale handshake detected.
     */
    suspend fun reconnect() {
        val configFile = File(configDir, CONFIG_FILE)
        if (!configFile.exists()) {
            Timber.w("Cannot reconnect: no saved config")
            return
        }
        val config = configFile.readText()
        var attempt = 0
        while (attempt < MAX_RECONNECT_ATTEMPTS) {
            try {
                connect(config)
                return
            } catch (e: Exception) {
                attempt++
                val delayMs = RECONNECT_BASE_DELAY_MS * (1L shl attempt.coerceAtMost(4))
                Timber.w("VPN reconnect attempt $attempt failed, retrying in ${delayMs}ms")
                delay(delayMs)
            }
        }
        Timber.e("VPN reconnect failed after $MAX_RECONNECT_ATTEMPTS attempts")
    }

    /**
     * Check if VPN tunnel interface is active.
     * Uses network capabilities check + interface file existence.
     */
    fun isActive(): Boolean {
        if (!tunnelActive) return false
        return checkTunnelInterface()
    }

    private fun bringUpTunnel(configFile: File) {
        val result = executeRoot("wg-quick up ${configFile.absolutePath}")
        if (result.exitCode != 0) {
            throw VpnException("wg-quick up failed (exit=${result.exitCode}): ${result.stderr}")
        }
    }

    private fun bringDownTunnel() {
        val configFile = File(configDir, CONFIG_FILE)
        if (configFile.exists()) {
            try {
                executeRoot("wg-quick down ${configFile.absolutePath}")
            } catch (e: Exception) {
                Timber.w(e, "wg-quick down failed (may not be running)")
            }
        }
    }

    private fun checkTunnelInterface(): Boolean {
        return try {
            val cm = context.getSystemService(ConnectivityManager::class.java)
            val activeNetwork = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(activeNetwork) ?: return false
            caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
        } catch (e: Exception) {
            // Fallback: check /sys/class/net for wg interface
            File("/sys/class/net/$TUNNEL_NAME").exists()
        }
    }

    private fun cleanupConfig() {
        try {
            File(configDir, CONFIG_FILE).delete()
        } catch (_: Exception) {}
    }

    private companion object {
        const val TUNNEL_NAME = "sphere0"
        const val CONFIG_FILE = "sphere0.conf"
        const val MAX_RECONNECT_ATTEMPTS = 5
        const val RECONNECT_BASE_DELAY_MS = 2000L
        /** Таймаут на root-команду (wg-quick). На слабых эмуляторах может зависнуть. */
        const val ROOT_CMD_TIMEOUT_SECONDS = 60L
        /** Максимальный размер stdout/stderr для чтения (защита от OOM). */
        const val MAX_OUTPUT_CHARS = 8_192
    }

    private fun executeRoot(command: String): ShellResult {
        val process = Runtime.getRuntime().exec(arrayOf("su", "-c", command))
        // FIX C1+H5: Читаем stdout/stderr с лимитом, timeout на waitFor
        val stdout = process.inputStream.bufferedReader().use {
            it.readText().take(MAX_OUTPUT_CHARS)
        }
        val stderr = process.errorStream.bufferedReader().use {
            it.readText().take(MAX_OUTPUT_CHARS)
        }
        val finished = process.waitFor(ROOT_CMD_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        if (!finished) {
            process.destroyForcibly()
            Timber.e("Root command timed out after ${ROOT_CMD_TIMEOUT_SECONDS}s: $command")
            return ShellResult(-1, stdout, "TIMEOUT: process killed after ${ROOT_CMD_TIMEOUT_SECONDS}s")
        }
        val exitCode = process.exitValue()
        return ShellResult(exitCode, stdout, stderr)
    }

    private data class ShellResult(val exitCode: Int, val stdout: String, val stderr: String)
}

class VpnException(message: String) : Exception(message)
