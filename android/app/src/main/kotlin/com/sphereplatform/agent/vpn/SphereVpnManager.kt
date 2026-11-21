package com.sphereplatform.agent.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import timber.log.Timber
import java.io.File
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Legacy root tunnel lifecycle. New connections are quarantined: wg-quick
 * provides neither app-scoped routing nor control-plane isolation. There is
 * currently no VpnService fallback. Retain disconnect for legacy recovery.
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

    /** No config is saved or executed without an accepted app-scoped provider. */
    @Suppress("UNUSED_PARAMETER")
    suspend fun connect(config: String): Unit = mutex.withLock {
        VpnExecutionPolicy.requireAppScopedProvider()
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

    /** Reconnect must pass the same gate as initial activation. */
    suspend fun reconnect(): Unit = mutex.withLock {
        VpnExecutionPolicy.requireAppScopedProvider()
    }

    /**
     * Check if VPN tunnel interface is active.
     * Uses network capabilities check + interface file existence.
     */
    fun isActive(): Boolean {
        if (!tunnelActive) return false
        return checkTunnelInterface()
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
