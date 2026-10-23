package com.sphereplatform.agent.vpn

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.net.VpnService
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Messenger
import android.os.Parcel
import androidx.core.content.ContextCompat
import com.sphereplatform.agent.BuildConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.UUID

/** Management process facade. A timeout is unknown; it never retries a mutation.
 * CommandDispatcher's durable journal must claim mutation IDs before this facade.
 */
@Singleton
class AppScopedVpnClient @Inject constructor(@ApplicationContext private val context: Context) {
    private val lock = Mutex()
    private val generation = AtomicLong()
    private val pending = ConcurrentHashMap<String, CompletableDeferred<AppVpnSnapshot>>()
    private val current = MutableStateFlow<AppVpnSnapshot?>(null)
    internal val snapshots = current.asStateFlow()
    @Volatile private var remote: IBinder? = null
    private var readiness: CompletableDeferred<IBinder>? = null
    private var connection: ServiceConnection? = null
    private val callback by lazy { Messenger(Handler(Looper.getMainLooper()) { message ->
        if (message.sendingUid != android.os.Process.myUid()) return@Handler true
        try {
            val text = message.data.getString("snapshot") ?: return@Handler true
            if (text.toByteArray(Charsets.UTF_8).size > 8192) return@Handler true
            val state = Json.decodeFromString<AppVpnSnapshot>(text)
            if (state.providerPid <= 0 || state.providerPid == android.os.Process.myPid()) return@Handler true
            when (message.what) {
                1 -> current.value = state
                2 -> state.requestId?.let { pending[it]?.complete(state) }
            }
        } catch (_: Exception) { /* Never log IPC contents or parser context. */ }
        true
    }) }
    // Register the management process for restored native snapshots. This is a
    // read-only subscription, never a retry of apply/resume/rotate.
    private val startupObserver = if (AppVpnAutoStart.hasState(context)) CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
        runCatching { request(JsonObject(mapOf("schema_version" to JsonPrimitive(1),
            "request_id" to JsonPrimitive(UUID.randomUUID().toString()), "session_id" to JsonPrimitive(UUID.randomUUID().toString()),
            "action" to JsonPrimitive("status")))) }
    } else null

    internal suspend fun request(payload: JsonObject): AppVpnSnapshot = withContext(Dispatchers.IO) {
        if (!BuildConfig.APP_SCOPED_VPN_CANARY || VpnProcessIdentity.isVpnProcess(context)) throw VpnPreparationException("vpn_provider_not_enabled")
        val text = payload.toString()
        val command = AppVpnCommand.parse(text)
        if (command.action in setOf("apply", "resume", "rotate") && VpnService.prepare(context) != null) {
            return@withContext AppVpnSnapshot(requestId = command.requestId.toString(), sessionId = command.sessionId.toString(), phase = "CONSENT_REQUIRED", reason = "vpn_android_consent_required")
        }
        val result = CompletableDeferred<AppVpnSnapshot>()
        if (pending.putIfAbsent(command.requestId.toString(), result) != null) throw VpnPreparationException("vpn_duplicate_client_request")
        try {
            withTimeout(45000) {
                if (command.action in setOf("apply", "resume", "rotate")) {
                    try { ContextCompat.startForegroundService(context, Intent(context, AppScopedVpnService::class.java)) }
                    catch (_: Exception) { throw VpnPreparationException("vpn_service_start_not_permitted") }
                }
                val binder = bind()
                val bytes = text.toByteArray(Charsets.UTF_8)
                val data = Parcel.obtain(); val reply = Parcel.obtain()
                try {
                    data.writeInterfaceToken(AppScopedVpnService.DESCRIPTOR)
                    data.writeByteArray(bytes); data.writeStrongBinder(callback.binder)
                    if (!binder.transact(AppScopedVpnService.OPERATE, data, reply, 0) || reply.readInt() != 1) throw VpnPreparationException("vpn_ipc_not_accepted")
                } catch (_: Exception) {
                    throw VpnPreparationException("vpn_command_outcome_unknown")
                } finally { bytes.fill(0); data.recycle(); reply.recycle() }
                result.await().also { if (command.action == "status") current.value = it }
            }
        } catch (_: TimeoutCancellationException) {
            throw VpnPreparationException("vpn_command_outcome_unknown")
        } finally { pending.remove(command.requestId.toString(), result) }
    }

    private suspend fun bind(): IBinder {
        val future = lock.withLock {
            remote?.takeIf { it.isBinderAlive }?.let { return it }
            readiness?.takeIf { !it.isCompleted }?.let { return@withLock it }
            val epoch = generation.incrementAndGet()
            val ready = CompletableDeferred<IBinder>(); readiness = ready
            val bound = object : ServiceConnection {
                override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
                    if (generation.get() != epoch) return
                    if (service == null) ready.completeExceptionally(VpnPreparationException("vpn_binding_unavailable"))
                    else { remote = service; ready.complete(service) }
                }
                override fun onServiceDisconnected(name: ComponentName?) { if (generation.get() == epoch) lost() }
                override fun onBindingDied(name: ComponentName?) { if (generation.get() == epoch) lost() }
                override fun onNullBinding(name: ComponentName?) { ready.completeExceptionally(VpnPreparationException("vpn_binding_unavailable")) }
            }
            connection?.let { runCatching { context.unbindService(it) } }
            connection = bound
            val accepted = try { context.bindService(Intent(context, AppScopedVpnService::class.java).setAction(AppScopedVpnService.CONTROL), bound, Context.BIND_AUTO_CREATE) } catch (_: Exception) { false }
            if (!accepted) ready.completeExceptionally(VpnPreparationException("vpn_binding_unavailable"))
            ready
        }
        return withTimeout(10000) { future.await() }
    }

    private fun lost() {
        remote = null
        readiness?.takeIf { !it.isCompleted }?.completeExceptionally(VpnPreparationException("vpn_process_ended_outcome_unknown"))
        pending.values.forEach { it.completeExceptionally(VpnPreparationException("vpn_process_ended_outcome_unknown")) }
        current.value = current.value?.copy(phase = "RECONCILIATION_REQUIRED", reason = "vpn_process_ended_guard_retained")
    }

    internal suspend fun close() = lock.withLock {
        startupObserver?.cancel()
        generation.incrementAndGet()
        connection?.let { runCatching { context.unbindService(it) } }
        connection = null; remote = null; readiness = null
        pending.values.forEach { it.completeExceptionally(VpnPreparationException("vpn_client_closed_outcome_unknown")) }
    }
}
