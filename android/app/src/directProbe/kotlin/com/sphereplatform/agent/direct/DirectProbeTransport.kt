package com.sphereplatform.agent.direct

import android.content.Context
import android.os.SystemClock
import android.util.Log
import com.sphereplatform.agent.BuildConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.*
import org.webrtc.*
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicBoolean

/** One peer, bounded callback mailbox, monotonic TTL and authenticated WS generation fence. */
class DirectProbeTransport(
    private val context: Context, private val scope: CoroutineScope,
    private val generation: () -> Long?, private val send: (Long, JsonObject) -> Boolean,
) {
    private companion object { val initialized = AtomicBoolean(false) }
    private val fence = AtomicLong(0)
    private val queue = Channel<() -> Unit>(32)
    private var peer: Probe? = null
    private var factory: PeerConnectionFactory? = null

    private class Probe(val session: String, val generation: Long, val token: Long, val expires: Long) {
        var connection: PeerConnection? = null
        var channel: DataChannel? = null
        var answered = false
        var sequence = 1
        var lastEcho = 0L
        var iceProfile = "host"
        val statsBudget = ProbeStatsBudget()
    }

    init {
        scope.launch {
            try {
                while (true) {
                    peer?.let { if (!valid(it)) close() }
                    peer?.let { if (it.answered && valid(it)) collectNetwork(it) }
                    val action = if (peer == null) queue.receive() else withTimeoutOrNull(100) { queue.receive() }
                    try { action?.invoke() } catch (e: kotlinx.coroutines.CancellationException) {
                        throw e
                    } catch (_: Exception) { invalidate(); close() }
                }
            } finally {
                close()
                factory?.dispose()
                factory = null
                queue.close()
            }
        }
    }

    private fun enqueue(action: () -> Unit): Boolean {
        if (queue.trySend(action).isSuccess) return true
        invalidate()
        return false
    }
    fun invalidate() { fence.incrementAndGet() }
    private fun valid(p: Probe) = peer === p && p.token == fence.get() &&
        generation() == p.generation && SystemClock.elapsedRealtime() < p.expires

    fun handle(message: JsonObject): Boolean {
        val kind = (message["type"] as? JsonPrimitive)?.contentOrNull
        if (kind !in setOf("direct_probe_offer", "direct_probe_close")) return false
        val wsGeneration = generation() ?: return true
        val token = fence.get()
        val receivedAt = SystemClock.elapsedRealtime()
        enqueue {
            if (token != fence.get() || generation() != wsGeneration) return@enqueue
            val sid = message["session_id"]?.jsonPrimitive?.contentOrNull ?: return@enqueue
            if (!DirectProbeProtocol.validSession(sid)) return@enqueue
            if (kind == "direct_probe_close") {
                if (message.keys == setOf("type", "session_id") && peer?.session == sid) close()
            } else {
                val sdp = message["sdp"]?.jsonPrimitive?.contentOrNull ?: return@enqueue
                val ttl = message["ttl_ms"]?.jsonPrimitive?.intOrNull ?: return@enqueue
                if (peer != null || message.keys != setOf("type", "session_id", "sdp", "ttl_ms") ||
                    ttl !in 1..DirectProbeProtocol.MAX_TTL_MS || !DirectProbeProtocol.validSdp(sdp)) return@enqueue
                if (SystemClock.elapsedRealtime() >= receivedAt + ttl) return@enqueue
                open(Probe(sid, wsGeneration, token, receivedAt + ttl), sdp)
            }
        }
        return true
    }

    private fun open(p: Probe, sdp: String) {
        peer = p
        try {
            // Validate before creating native threads. Ordinary builds keep an empty host-only profile.
            val iceProfile = DirectProbeIceProfile.fromUrl(BuildConfig.DIRECT_PROBE_STUN_URL)
            p.iceProfile = iceProfile.name
            if (factory == null) {
                if (initialized.compareAndSet(false, true)) {
                    try {
                        PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(context)
                            .setEnableInternalTracer(false).createInitializationOptions())
                    } catch (error: Exception) { initialized.set(false); throw error }
                }
                factory = PeerConnectionFactory.builder().createPeerConnectionFactory()
            }
            val servers = iceProfile.serverUrl?.let { listOf(PeerConnection.IceServer.builder(it).createIceServer()) }
                ?: emptyList()
            val config = PeerConnection.RTCConfiguration(servers)
            config.sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            p.connection = factory?.createPeerConnection(config, object : PeerConnection.Observer {
                override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
                override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
                override fun onIceCandidate(candidate: IceCandidate) = Unit
                override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
                override fun onAddStream(stream: MediaStream) = Unit
                override fun onRemoveStream(stream: MediaStream) = Unit
                override fun onRenegotiationNeeded() { enqueue { if (valid(p) && p.answered) close() } }
                override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                    if (state in setOf(PeerConnection.IceConnectionState.FAILED, PeerConnection.IceConnectionState.CLOSED))
                        enqueue { if (peer === p) close() }
                }
                override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
                    if (state == PeerConnection.IceGatheringState.COMPLETE) enqueue { answer(p) }
                }
                override fun onDataChannel(channel: DataChannel) {
                    val admitted = enqueue {
                        if (!valid(p) || p.channel != null || channel.label() != DirectProbeProtocol.LABEL) {
                            channel.close(); channel.dispose()
                            if (peer === p) close()
                        } else {
                            p.channel = channel
                            channel.registerObserver(object : DataChannel.Observer {
                                override fun onBufferedAmountChange(previous: Long) = Unit
                                override fun onStateChange() = Unit
                                override fun onMessage(buffer: DataChannel.Buffer) {
                                    val text = if (!buffer.binary && buffer.data.remaining() <= 80)
                                        Charsets.UTF_8.decode(buffer.data).toString() else ""
                                    enqueue { echo(p, text) }
                                }
                            })
                        }
                    }
                    // A JNI wrapper must not be orphaned when the bounded mailbox rejects it.
                    if (!admitted) { channel.close(); channel.dispose() }
                }
            }) ?: error("peer_unavailable")
            p.connection?.setRemoteDescription(observer(p, set = {
                p.connection?.createAnswer(observer(p, create = { desc ->
                    p.connection?.setLocalDescription(observer(p, set = { answer(p) }), desc)
                }), MediaConstraints())
            }), SessionDescription(SessionDescription.Type.OFFER, sdp))
        } catch (_: Exception) { close() }
    }

    private fun observer(p: Probe, set: () -> Unit = {}, create: (SessionDescription) -> Unit = {}) = object : SdpObserver {
        override fun onSetSuccess() { enqueue { if (valid(p)) set() } }
        override fun onCreateSuccess(description: SessionDescription) { enqueue { if (valid(p)) create(description) } }
        override fun onSetFailure(error: String) { enqueue { if (peer === p) close() } }
        override fun onCreateFailure(error: String) { enqueue { if (peer === p) close() } }
    }

    private fun answer(p: Probe) {
        val connection = p.connection ?: return
        if (!valid(p) || p.answered || connection.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) return
        val sdp = connection.localDescription?.description ?: return
        if (!DirectProbeProtocol.validSdp(sdp) || !send(p.generation, buildJsonObject {
            put("type", "direct_probe_answer"); put("session_id", p.session); put("sdp", sdp)
        })) { close(); return }
        p.answered = true
    }

    private fun echo(p: Probe, text: String) {
        if (!valid(p)) { if (peer === p) close(); return }
        val now = SystemClock.elapsedRealtime()
        val echoed = DirectProbeProtocol.echo(text, p.session, p.sequence)
        val channel = p.channel
        if (echoed == null || (p.lastEcho != 0L && now - p.lastEcho < 100) || channel == null ||
            channel.bufferedAmount() > 1024 || !channel.send(DataChannel.Buffer(ByteBuffer.wrap(echoed.toByteArray()), false))) {
            close(); return
        }
        p.sequence++; p.lastEcho = now
    }

    private fun collectNetwork(p: Probe) {
        val connection = p.connection ?: return
        val sampledAt = SystemClock.elapsedRealtime()
        if (!p.statsBudget.begin(sampledAt)) return
        try {
            connection.getStats { report ->
                // Never stringify the native report: it contains addresses, IDs and certificates.
                val rows = report.statsMap.values
                val summary = if (rows.size <= DirectProbeNetwork.MAX_ROWS) DirectProbeNetwork.summary(
                    rows.map { ProbeStatsRow(it.type, it.members) }) else null
                enqueue {
                    if (p.statsBudget.complete() && valid(p) && summary != null) {
                        val age = (SystemClock.elapsedRealtime() - sampledAt).coerceAtLeast(0)
                        val snapshot = buildJsonObject {
                            put("event", "native_ice_summary")
                            put("iceProfile", p.iceProfile)
                            put("sampleAgeMs", age)
                            put("network", summary)
                        }
                        // Canary-only local aggregate, <=32 records/peer; no per-sample socket publication.
                        Log.i("SphereDirectProbe", snapshot.toString())
                    }
                }
            }
        } catch (_: Exception) { p.statsBudget.complete() }
    }

    private fun close() {
        val old = peer
        peer = null
        old?.statsBudget?.retire()
        old?.channel?.unregisterObserver()
        old?.channel?.close()
        old?.channel?.dispose()
        old?.connection?.close()
        old?.connection?.dispose()
        // Factory threads are also retired after every finite probe.
        factory?.dispose(); factory = null
    }
}
