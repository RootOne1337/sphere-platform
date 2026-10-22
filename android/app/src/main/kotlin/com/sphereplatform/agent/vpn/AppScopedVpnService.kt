package com.sphereplatform.agent.vpn

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Binder
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.Parcel
import android.os.Process
import androidx.core.app.NotificationCompat
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.R
import java.io.File
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.serialization.encodeToString

/** One APK, separate native process. No enrollment, WebSocket or root health polling. */
class AppScopedVpnService : VpnService() {
    internal companion object {
        const val CONTROL = "com.sphereplatform.agent.vpn.CONTROL_V1"
        const val DESCRIPTOR = "com.sphereplatform.agent.vpn.IControlV1"
        const val OPERATE = IBinder.FIRST_CALL_TRANSACTION
        private const val CHANNEL = "sphere_app_vpn"
        private const val NOTIFICATION = 3205
    }
    private val work = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val admission = Mutex()
    private val snapshot = AtomicReference(AppVpnSnapshot())
    private val listeners = linkedMapOf<IBinder, Messenger>()
    private val completed = LinkedHashMap<UUID, Pair<String, AppVpnSnapshot>>()
    private val mutationGeneration = AtomicLong()
    private lateinit var journal: UidGuardJournal
    private lateinit var guard: SelectedUidGuard
    @Volatile private var runtime: AppScopedVpnSession? = null
    private var prepared: PreparedAppScopedConfig? = null
    @Volatile private var activeId: UUID? = null

    override fun onCreate() {
        super.onCreate()
        check(VpnProcessIdentity.isVpnProcess(this)) { "vpn_process_isolation_required" }
        val directory = File(filesDir, "app-vpn-v1")
        journal = UidGuardJournal(File(directory, "guard.json"))
        guard = SelectedUidGuard(journal, BoundedGuardRootExecutor(File(directory, "scripts")))
        try {
            journal.read()?.takeIf { it.phase != "RELEASED" }?.let {
                snapshot.set(AppVpnSnapshot(sessionId = it.operationId, phase = "RECONCILIATION_REQUIRED", reason = "vpn_previous_process_ended_guard_retained",
                    trafficMode = if (it.planVersion == 5) "all_apps_except_control" else "selected_apps"))
            }
        } catch (_: Exception) { snapshot.set(AppVpnSnapshot(phase = "RECONCILIATION_REQUIRED", reason = "vpn_guard_journal_unreadable")) }
        work.launch {
            while (true) {
                delay(2000)
                val generation = mutationGeneration.get()
                if (generation % 2L != 0L) continue
                val current = runtime ?: continue
                val currentId = activeId ?: continue
                try {
                    val state = current.observe()
                    if (runtime !== current || activeId != currentId || mutationGeneration.get() != generation) continue
                    publish(snapshot.get().copy(phase = state.phase, reason = state.reason, nativeVersion = state.nativeVersion,
                        handshakeEpochSeconds = state.stats?.handshakeEpochSeconds,
                        rxBytes = state.stats?.rxBytes, txBytes = state.stats?.txBytes, sampledAtEpochMs = System.currentTimeMillis()))
                } catch (_: Exception) {
                    if (runtime !== current || activeId != currentId || mutationGeneration.get() != generation) continue
                    publish(snapshot.get().copy(phase = "STATUS_UNKNOWN", reason = "vpn_native_status_unavailable", sampledAtEpochMs = System.currentTimeMillis()))
                }
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!BuildConfig.APP_SCOPED_VPN_CANARY) { stopSelf(); return START_NOT_STICKY }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "VPN выбранных приложений", NotificationManager.IMPORTANCE_LOW))
        val notification = NotificationCompat.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_sphere)
            .setContentTitle("Sphere · VPN приложений").setContentText("Управление Sphere работает вне туннеля")
            .setOngoing(true).setOnlyAlertOnce(true).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(NOTIFICATION, notification)
        return START_NOT_STICKY // No blind restart/reapply after an uncertain native outcome.
    }

    private val control = object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
            if (code == INTERFACE_TRANSACTION) { reply?.writeString(DESCRIPTOR); return true }
            if (code != OPERATE) return super.onTransact(code, data, reply, flags)
            if (Binder.getCallingUid() != Process.myUid() || !BuildConfig.APP_SCOPED_VPN_CANARY) throw SecurityException("vpn_private_ipc_only")
            data.enforceInterface(DESCRIPTOR)
            if (data.dataAvail() > 131072) throw SecurityException("vpn_ipc_bounds")
            val bytes = data.createByteArray() ?: throw SecurityException("vpn_ipc_empty")
            if (bytes.size !in 1..98304) throw SecurityException("vpn_ipc_bounds")
            val command = AppVpnCommand.parse(bytes.toString(Charsets.UTF_8))
            val fingerprint = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
            bytes.fill(0)
            val callback = Messenger(data.readStrongBinder() ?: throw SecurityException("vpn_ipc_callback_missing"))
            synchronized(listeners) {
                if (listeners.size >= 4 && callback.binder !in listeners) throw SecurityException("vpn_ipc_listener_capacity")
                listeners[callback.binder] = callback
            }
            if (command.action == "status") {
                send(callback, snapshot.get().copy(requestId = command.requestId.toString()), 2)
            } else if (!admission.tryLock()) {
                send(callback, AppVpnSnapshot(requestId = command.requestId.toString(), sessionId = command.sessionId.toString(), phase = "OPERATION_REJECTED", reason = "vpn_operation_busy"), 2)
            } else work.launch {
                try {
                    val existing = completed[command.requestId]
                    if (existing != null) {
                        send(callback, if (existing.first == fingerprint) existing.second else AppVpnSnapshot(requestId = command.requestId.toString(), sessionId = command.sessionId.toString(), phase = "OPERATION_REJECTED", reason = "vpn_request_id_conflict"), 2)
                        return@launch
                    }
                    val result = operate(command)
                    completed[command.requestId] = fingerprint to result
                    while (completed.size > 32) completed.remove(completed.keys.first())
                    send(callback, result, 2)
                } finally { admission.unlock() }
            }
            reply?.writeInt(1)
            return true
        }
    }

    override fun onBind(intent: Intent?): IBinder? = when (intent?.action) {
        CONTROL -> if (BuildConfig.APP_SCOPED_VPN_CANARY) control else null
        SERVICE_INTERFACE -> super.onBind(intent)
        else -> null
    }

    private suspend fun operate(command: AppVpnCommand): AppVpnSnapshot {
        val initial = AppVpnSnapshot(command.requestId.toString(), command.sessionId.toString(),
            command.profileRevisionId?.toString() ?: snapshot.get().profileRevisionId, phase = "APPLYING",
            trafficMode = prepared?.apps?.mode ?: snapshot.get().trafficMode)
        var mutating = false
        fun beginMutation() { mutating = true; mutationGeneration.incrementAndGet(); publish(initial) }
        return try {
            val receipt = when (command.action) {
                "apply" -> {
                    if (activeId != null || journal.read()?.phase?.let { it != "RELEASED" } == true) throw VpnPreparationException("vpn_session_reconciliation_required")
                    val config = command.prepare(packageName, Process.myUid(), AndroidAppIdentitySource(packageManager))
                    // Consent and other VPN/lockdown checks happen before any guard mutation.
                    AndroidScopedTunPlatform(this).assertReady(config)
                    val session = AppScopedVpnSession(AndroidScopedTunPlatform(this), JniScopedAwgEngine(), guard)
                    beginMutation()
                    runtime = session; prepared = config; activeId = command.sessionId
                    session.connect(command.sessionId, config)
                }
                "pause" -> owned(command.sessionId).let { beginMutation(); it.pause(command.sessionId) }
                "resume" -> owned(command.sessionId).let {
                    val config = prepared ?: throw VpnPreparationException("vpn_profile_memory_unavailable")
                    beginMutation(); it.resume(command.sessionId, config)
                }
                "rotate" -> owned(command.sessionId).let {
                    val config = command.prepare(packageName, Process.myUid(), AndroidAppIdentitySource(packageManager))
                    val previous = prepared ?: throw VpnPreparationException("vpn_profile_memory_unavailable")
                    if (previous.apps.uids != config.apps.uids || previous.apps.packages.toSet() != config.apps.packages.toSet()
                        || previous.apps.ipv6 != config.apps.ipv6 || previous.apps.mode != config.apps.mode
                        || previous.apps.excludedPackage != config.apps.excludedPackage) throw VpnPreparationException("vpn_rotation_policy_change_requires_disconnect")
                    beginMutation()
                    it.rotate(command.sessionId, config).also { prepared = config }
                }
                "disconnect" -> {
                    val session = runtime
                    val state = if (session != null) owned(command.sessionId).let { beginMutation(); it.disconnect(command.sessionId) } else {
                        // Explicit recovery after process death: kernel proof must
                        // confirm that the previous TUN is closed before release.
                        val record = journal.read() ?: throw VpnPreparationException("vpn_session_not_found")
                        if (record.operationId != command.sessionId.toString()) throw VpnPreparationException("vpn_session_reconciliation_required")
                        beginMutation()
                        guard.release(command.sessionId)
                        AppTunnelReceipt(command.sessionId.toString(), "DISCONNECTED_CONFIRMED", null)
                    }
                    runtime = null; prepared = null; activeId = null
                    stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
                    state
                }
                else -> throw VpnPreparationException("vpn_action_unsupported")
            }
            initial.copy(phase = receipt.phase, reason = receipt.reason, nativeVersion = receipt.nativeVersion,
                trafficMode = if (receipt.phase == "DISCONNECTED_CONFIRMED") null else prepared?.apps?.mode ?: initial.trafficMode,
                sampledAtEpochMs = System.currentTimeMillis()).also(::publish)
        } catch (failure: Exception) {
            val reason = (failure as? VpnPreparationException)?.reason ?: "vpn_provider_operation_unconfirmed"
            // Loading a missing ABI or resolving an endpoint can fail before
            // connect has created its durable guard intent. Do not leave an
            // unowned in-memory session that cannot be explicitly disconnected.
            if (mutating && command.action == "apply") {
                val untouched = runCatching { journal.read()?.let { it.phase == "RELEASED" } ?: true }.getOrDefault(false)
                if (untouched) {
                    runtime = null; prepared = null; activeId = null
                    return initial.copy(phase = "OPERATION_REJECTED", reason = reason, sampledAtEpochMs = System.currentTimeMillis()).also(::publish)
                }
            }
            initial.copy(phase = if (mutating) "OUTCOME_UNKNOWN" else "OPERATION_REJECTED", reason = reason, sampledAtEpochMs = System.currentTimeMillis()).also { if (mutating) publish(it) }
        } finally {
            if (mutating) mutationGeneration.incrementAndGet()
        }
    }

    private fun owned(id: UUID) = runtime?.takeIf { activeId == id } ?: throw VpnPreparationException("vpn_session_reconciliation_required")
    private fun publish(state: AppVpnSnapshot) {
        snapshot.set(state)
        val callbacks = synchronized(listeners) { listeners.values.toList() }
        callbacks.forEach { if (!send(it, state)) synchronized(listeners) { listeners.remove(it.binder) } }
    }
    private fun send(callback: Messenger, state: AppVpnSnapshot, kind: Int = 1): Boolean = try {
        callback.send(Message.obtain(null, kind).apply { data = Bundle().apply { putString("snapshot", AppVpnWire.json.encodeToString(state)) } }); true
    } catch (_: Exception) { false }

    override fun onRevoke() {
        publish(snapshot.get().copy(phase = "REVOKED_GUARD_HELD", reason = "vpn_android_consent_revoked"))
        // Process death closes every native FD while the UID blackhole survives.
        // It must never terminate the management/control process.
        if (VpnProcessIdentity.isVpnProcess(this)) Process.killProcess(Process.myPid())
    }
    override fun onDestroy() {
        work.cancel()
        super.onDestroy()
        if (runtime != null && VpnProcessIdentity.isVpnProcess(this)) Process.killProcess(Process.myPid())
    }
}
