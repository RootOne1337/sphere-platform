package com.sphereplatform.agent.vpn

import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.os.Process
import android.provider.Settings
import java.io.File
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.amnezia.awg.GoBackend

internal interface HeldAppTun {
    val name: String
    val index: Int
    fun duplicateForNative(): Int
    fun close()
}

internal interface ScopedTunPlatform {
    val ownerUid: Int
    fun assertReady(config: PreparedAppScopedConfig)
    fun establish(config: PreparedAppScopedConfig): HeldAppTun
    fun protect(fd: Int): Boolean
}

internal class AndroidScopedTunPlatform(private val service: VpnService) : ScopedTunPlatform {
    override val ownerUid: Int get() = Process.myUid()
    override fun assertReady(config: PreparedAppScopedConfig) {
        if (VpnService.prepare(service) != null) throw VpnPreparationException("vpn_consent_required")
        val lockdown = try {
            if (Build.VERSION.SDK_INT >= 29) service.isLockdownEnabled else Settings.Secure.getInt(service.contentResolver, "always_on_vpn_lockdown", 0) != 0
        } catch (_: Exception) { throw VpnPreparationException("vpn_lockdown_unverified") }
        if (lockdown) throw VpnPreparationException("vpn_lockdown_conflicts_with_control_bypass")
        val manager = service.getSystemService(ConnectivityManager::class.java)
        if (manager.allNetworks.any { manager.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true }) throw VpnPreparationException("vpn_other_network_active")
        val fresh = AppTrafficSelectionResolver.resolve(AppTrafficSelection(config.apps.packages, ipv6 = config.apps.ipv6), service.packageName, ownerUid, AndroidAppIdentitySource(service.packageManager))
        if (fresh.uids != config.apps.uids) throw VpnPreparationException("vpn_package_identity_changed")
        if (config.nativeConfig.`interface`.dnsServers.isEmpty()) throw VpnPreparationException("vpn_explicit_dns_required")
    }
    override fun establish(config: PreparedAppScopedConfig): HeldAppTun {
        assertReady(config)
        val builder = service.Builder().setSession("Sphere app-scoped VPN").setBlocking(true)
        config.apps.packages.forEach { builder.addAllowedApplication(it) }
        config.nativeConfig.`interface`.addresses.forEach { builder.addAddress(it.address, it.mask) }
        config.nativeConfig.`interface`.dnsServers.forEach { builder.addDnsServer(it) }
        config.nativeConfig.peers.single().allowedIps.forEach { builder.addRoute(it.address, it.mask) }
        builder.setMtu(config.nativeConfig.`interface`.mtu.orElse(1280))
        if (Build.VERSION.SDK_INT >= 29) builder.setMetered(false)
        val descriptor = builder.establish() ?: throw VpnPreparationException("vpn_tun_not_created")
        try { return HeldDescriptorTun(descriptor) } catch (failure: Exception) { descriptor.close(); throw failure }
    }
    override fun protect(fd: Int) = service.protect(fd)
}

internal class HeldDescriptorTun(private val descriptor: ParcelFileDescriptor) : HeldAppTun {
    override val name: String
    override val index: Int
    init {
        val info = File("/proc/self/fdinfo/${descriptor.fd}").readText()
        name = info.lineSequence().firstOrNull { it.startsWith("iff:") }?.substringAfter(':')?.trim().orEmpty()
        if (!Regex("tun[0-9]{1,4}").matches(name)) throw VpnPreparationException("vpn_tun_identity_unverified")
        index = File("/sys/class/net/$name/ifindex").readText().trim().toIntOrNull()
            ?.takeIf { it > 0 } ?: throw VpnPreparationException("vpn_tun_identity_unverified")
    }
    override fun duplicateForNative() = ParcelFileDescriptor.dup(descriptor.fileDescriptor).detachFd()
    override fun close() = descriptor.close()
}

internal data class AwgTransportStats(val handshakeEpochSeconds: Long, val rxBytes: Long, val txBytes: Long)

internal interface ScopedAwgEngine {
    fun load(): String
    /** Takes ownership of fd on entry, including a negative native result. */
    fun start(name: String, fd: Int, config: String): Int
    fun sockets(handle: Int): IntArray
    fun stats(handle: Int): AwgTransportStats
    fun stop(handle: Int)
}

internal class JniScopedAwgEngine : ScopedAwgEngine {
    override fun load(): String {
        try {
            System.loadLibrary("wg-go")
            return GoBackend.awgVersion()?.takeIf { it.length in 1..128 } ?: throw VpnPreparationException("vpn_native_version_unverified")
        } catch (_: LinkageError) { throw VpnPreparationException("vpn_native_library_unavailable") }
    }
    override fun start(name: String, fd: Int, config: String): Int = try {
        GoBackend.awgTurnOn(name, fd, config)
    } catch (_: UnsatisfiedLinkError) {
        // An unresolved JNI symbol never enters Go, so native ownership did not
        // begin. Retire the detached duplicate explicitly; the held TUN remains.
        runCatching { ParcelFileDescriptor.adoptFd(fd).close() }
        throw VpnPreparationException("vpn_native_entrypoint_unavailable")
    }
    override fun sockets(handle: Int) = intArrayOf(GoBackend.awgGetSocketV4(handle), GoBackend.awgGetSocketV6(handle)).filter { it >= 0 }.distinct().toIntArray()
    override fun stats(handle: Int): AwgTransportStats {
        // Upstream IPC contains private keys. Project only counters; never expose
        // the raw native result, include it in an exception or log it.
        val text = GoBackend.awgGetConfig(handle) ?: throw VpnPreparationException("vpn_native_status_unavailable")
        if (text.length > 65536) throw VpnPreparationException("vpn_native_status_invalid")
        fun number(key: String) = text.lineSequence().firstOrNull { it.startsWith("$key=") }?.substringAfter('=')?.toLongOrNull()?.takeIf { it >= 0 } ?: 0
        return AwgTransportStats(number("last_handshake_time_sec"), number("rx_bytes"), number("tx_bytes"))
    }
    override fun stop(handle: Int) = GoBackend.awgTurnOff(handle)
}

internal data class AppTunnelReceipt(val operationId: String, val phase: String, val nativeVersion: String?, val stats: AwgTransportStats? = null, val reason: String? = null)

/** Candidate runtime; callers MUST isolate it from Sphere's control/media process.
 * Native activation and a handshake are separate outcomes. A failed start keeps
 * the UID guard; only explicit confirmed teardown may release application traffic.
 */
internal class AppScopedVpnSession(private val platform: ScopedTunPlatform, private val engine: ScopedAwgEngine, private val guard: SelectedUidGuard) {
    private val lock = Mutex()
    private var operation: UUID? = null
    private var tun: HeldAppTun? = null
    private var handle = -1
    private var version: String? = null
    private var allowed = false
    private var uncertain = false
    private var guardConfirmed = false
    private var failureReason: String? = null

    suspend fun connect(id: UUID, config: PreparedAppScopedConfig): AppTunnelReceipt = lock.withLock {
        if (operation != null) throw VpnPreparationException("vpn_session_reconciliation_required")
        platform.assertReady(config)
        version = engine.load()
        val endpoint = config.nativeConfig.peers.single().endpoint.get()
        if (endpoint.resolved.isEmpty) throw VpnPreparationException("vpn_endpoint_resolution_failed")
        val userspace = config.nativeConfig.toAwgUserspaceString()
        operation = id
        try {
            guard.block(id, config.apps, platform.ownerUid)
            guardConfirmed = true
            tun = platform.establish(config)
            handle = engine.start(tun!!.name, tun!!.duplicateForNative(), userspace)
            if (handle < 0) throw VpnPreparationException("vpn_native_activation_rejected")
            val sockets = engine.sockets(handle)
            if (sockets.isEmpty() || sockets.any { !platform.protect(it) }) throw VpnPreparationException("vpn_transport_protection_failed")
            guard.allow(id, tun!!.name, tun!!.index)
            allowed = true
            AppTunnelReceipt(id.toString(), "TRANSPORT_READY", version)
        } catch (failure: Exception) {
            failureReason = (failure as? VpnPreparationException)?.reason ?: "vpn_native_or_platform_failure"
            withContext(NonCancellable + Dispatchers.IO) {
                if (handle >= 0) runCatching { engine.stop(handle) }.onFailure { uncertain = true }
                handle = -1
                runCatching { tun?.close() }.onFailure { uncertain = true }; tun = null
            }
            if (failure is CancellationException) throw failure
            throw VpnPreparationException(if (guardConfirmed) "vpn_start_failed_guard_held" else "vpn_start_failed_guard_unconfirmed")
        }
    }
    suspend fun observe(): AppTunnelReceipt = lock.withLock {
        val id = operation ?: throw VpnPreparationException("vpn_session_not_found")
        if (handle < 0 || !allowed) return@withLock AppTunnelReceipt(id.toString(), if (guardConfirmed) "FAILED_GUARD_HELD" else "GUARD_UNCONFIRMED", version, reason = failureReason)
        val stats = engine.stats(handle)
        AppTunnelReceipt(id.toString(), if (stats.handshakeEpochSeconds > 0) "HANDSHAKE_CONFIRMED" else "AWAITING_HANDSHAKE", version, stats)
    }
    suspend fun disconnect(id: UUID): AppTunnelReceipt = lock.withLock {
        if (operation != id) throw VpnPreparationException("vpn_session_reconciliation_required")
        withContext(NonCancellable + Dispatchers.IO) {
            if (allowed) runCatching { guard.pause(id) }.onSuccess { allowed = false }.onFailure { uncertain = true }
            if (handle >= 0) runCatching { engine.stop(handle) }.onFailure { uncertain = true }
            handle = -1
            runCatching { tun?.close() }.onFailure { uncertain = true }; tun = null
            if (uncertain) throw VpnPreparationException("vpn_stop_unknown_guard_held")
            guard.release(id)
            operation = null
            guardConfirmed = false
            AppTunnelReceipt(id.toString(), "DISCONNECTED_CONFIRMED", version)
        }
    }
}
