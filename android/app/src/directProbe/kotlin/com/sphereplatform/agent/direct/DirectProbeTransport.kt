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
    private val streaming: com.sphereplatform.agent.streaming.StreamingManager,
) {
    private companion object { val initialized = AtomicBoolean(false) }
    private val fence = AtomicLong(0)
    private val queue = Channel<() -> Unit>(32)
    @Volatile private var peer: Probe? = null
    private var factory: PeerConnectionFactory? = null

    private class Probe(val session: String, val generation: Long, val token: Long, val expires: Long) {
        val progress = DirectProbeProgress(SystemClock.elapsedRealtime())
        var connection: PeerConnection? = null
        var channel: DataChannel? = null
        var answered = false
        var sequence = 1
        var lastEcho = 0L
        var iceProfile = "host"
        var videoRequested = false
        var capture: com.sphereplatform.agent.streaming.CaptureInputSession? = null
        var video: DirectEncodedVideoSource? = null
        @Volatile var videoReady = false
        val statsBudget = ProbeStatsBudget()
    }

    init {
        scope.launch {
            try {
                while (true) {
                    peer?.let { if (!valid(it)) close(if (SystemClock.elapsedRealtime() >= it.expires) ProbeStage.EXPIRED else ProbeStage.CLOSED) }
                    peer?.let { if (it.videoRequested && it.capture != streaming.getInputSession()) close() }
                    // Setup failures previously emitted no stats because sampling began only after the answer.
                    peer?.let { if (valid(it)) collectNetwork(it) }
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
        generation() == p.generation && SystemClock.elapsedRealtime() < p.expires &&
        (!p.videoRequested || p.capture?.let { streaming.isEncodedViewerCurrent(p, it) } == true)

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
                val video = message["media"]?.jsonPrimitive?.contentOrNull == DirectVideoProtocol.MODE
                val expected = setOf("type", "session_id", "sdp", "ttl_ms") +
                    (if (video) setOf("media") else emptySet()) + (if ("ice" in message) setOf("ice") else emptySet())
                if (peer != null || message.keys != expected || ttl !in 1..DirectProbeProtocol.MAX_TTL_MS ||
                    !(if (video) DirectVideoProtocol.validSdp(sdp, true) else DirectProbeProtocol.validSdp(sdp))) return@enqueue
                val grant = if ("ice" in message) DirectProbeTurnGrant.parse(message["ice"], sid) ?: return@enqueue else null
                if (SystemClock.elapsedRealtime() >= receivedAt + ttl) return@enqueue
                open(Probe(sid, wsGeneration, token, receivedAt + ttl).apply { videoRequested = video }, sdp, grant)
            }
        }
        return true
    }

    private fun open(p: Probe, sdp: String, grant: DirectProbeTurnGrant?) {
        peer = p
        try {
            if (p.videoRequested) {
                p.capture = streaming.attachEncodedViewer(p) { frame ->
                    if (p.videoReady) p.video?.submit(frame)
                } ?: error("active_capture_required")
                p.video = DirectEncodedVideoSource(checkNotNull(p.capture), { valid(p) },
                    { if (valid(p)) streaming.onViewerConnected() }, { enqueue { if (peer === p) close() } })
            }
            // Validate before creating native threads. Ordinary builds keep an empty host-only profile.
            val iceProfile = DirectProbeIceProfile.fromUrl(BuildConfig.DIRECT_PROBE_STUN_URL)
            p.iceProfile = if (grant == null) iceProfile.name else "turn"
            progress(p, ProbeStage.OFFER_RECEIVED)
            if (factory == null) {
                if (initialized.compareAndSet(false, true)) {
                    try {
                        PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(context)
                            .setEnableInternalTracer(false).createInitializationOptions())
                    } catch (error: Exception) { initialized.set(false); throw error }
                }
                val builder = PeerConnectionFactory.builder()
                p.video?.let { builder.setVideoEncoderFactory(it.encoderFactory) }
                factory = builder.createPeerConnectionFactory()
            }
            progress(p, ProbeStage.FACTORY_READY)
            val servers = grant?.urls?.map { PeerConnection.IceServer.builder(it)
                .setUsername(grant.username).setPassword(grant.credential).createIceServer() }
                ?: iceProfile.serverUrl?.let { listOf(PeerConnection.IceServer.builder(it).createIceServer()) }
                ?: emptyList()
            val config = PeerConnection.RTCConfiguration(servers)
            if (p.videoRequested) config.enableCpuOveruseDetection = false
            if (grant != null) config.iceTransportsType = if (grant.relayOnly)
                PeerConnection.IceTransportsType.RELAY else PeerConnection.IceTransportsType.ALL
            config.sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            p.connection = factory?.createPeerConnection(config, object : PeerConnection.Observer {
                override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
                override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
                override fun onIceCandidate(candidate: IceCandidate) = Unit
                override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
                override fun onAddStream(stream: MediaStream) = Unit
                override fun onRemoveStream(stream: MediaStream) = Unit
                override fun onRenegotiationNeeded() { enqueue { if (valid(p) && p.answered && !p.videoRequested) close() } }
                override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                    if (state in setOf(PeerConnection.IceConnectionState.FAILED, PeerConnection.IceConnectionState.CLOSED))
                        enqueue { if (peer === p) close(ProbeStage.CONNECTION_FAILED) }
                }
                override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
                    enqueue {
                        if (!valid(p)) return@enqueue
                        if (state == PeerConnection.IceGatheringState.GATHERING) progress(p, ProbeStage.GATHERING)
                        if (state == PeerConnection.IceGatheringState.COMPLETE) {
                            progress(p, ProbeStage.GATHERED)
                            answer(p)
                        }
                    }
                }
                override fun onDataChannel(channel: DataChannel) {
                    val admitted = enqueue {
                        if (!valid(p) || p.channel != null || channel.label() !=
                            (if (p.videoRequested) DirectVideoProtocol.LABEL else DirectProbeProtocol.LABEL)) {
                            channel.close(); channel.dispose()
                            if (peer === p) close()
                        } else {
                            p.channel = channel
                            progress(p, ProbeStage.CHANNEL_RECEIVED)
                            channel.registerObserver(object : DataChannel.Observer {
                                override fun onBufferedAmountChange(previous: Long) = Unit
                                override fun onStateChange() {
                                    enqueue { channelOpened(p, channel) }
                                }
                                override fun onMessage(buffer: DataChannel.Buffer) {
                                    val text = if (!buffer.binary && buffer.data.remaining() <= 80)
                                        Charsets.UTF_8.decode(buffer.data).toString() else ""
                                    enqueue { echo(p, text) }
                                }
                            })
                            // OPEN may precede observer registration on a fast local peer.
                            channelOpened(p, channel)
                        }
                    }
                    // A JNI wrapper must not be orphaned when the bounded mailbox rejects it.
                    if (!admitted) { channel.close(); channel.dispose() }
                }
            }) ?: error("peer_unavailable")
            progress(p, ProbeStage.PEER_READY)
            p.connection?.setRemoteDescription(observer(p, ProbeStage.REMOTE_FAILED, set = {
                progress(p, ProbeStage.REMOTE_SET)
                p.video?.let { video ->
                    p.connection?.addTrack(video.start(checkNotNull(factory)), listOf("sphere-screen"))
                    p.connection?.transceivers?.filter { it.mediaType == MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO }
                        ?.forEach { it.direction = RtpTransceiver.RtpTransceiverDirection.SEND_ONLY }
                }
                p.connection?.createAnswer(observer(p, ProbeStage.CREATE_FAILED, create = { desc ->
                    progress(p, ProbeStage.ANSWER_CREATED)
                    p.connection?.setLocalDescription(observer(p, ProbeStage.LOCAL_FAILED, set = {
                        progress(p, ProbeStage.LOCAL_SET)
                        answer(p)
                    }), desc)
                }), MediaConstraints())
            }), SessionDescription(SessionDescription.Type.OFFER, sdp))
        } catch (_: Exception) { close(ProbeStage.OPEN_FAILED) }
    }

    private fun observer(p: Probe, failed: ProbeStage, set: () -> Unit = {}, create: (SessionDescription) -> Unit = {}) = object : SdpObserver {
        override fun onSetSuccess() { enqueue { if (valid(p)) set() } }
        override fun onCreateSuccess(description: SessionDescription) { enqueue { if (valid(p)) create(description) } }
        override fun onSetFailure(error: String) { enqueue { if (peer === p) close(failed) } }
        override fun onCreateFailure(error: String) { enqueue { if (peer === p) close(failed) } }
    }

    private fun answer(p: Probe) {
        val connection = p.connection ?: return
        if (!valid(p) || p.answered || connection.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) return
        val sdp = connection.localDescription?.description ?: return
        if (!(if (p.videoRequested) DirectVideoProtocol.validSdp(sdp, false) else DirectProbeProtocol.validSdp(sdp)) || !send(p.generation, buildJsonObject {
            put("type", "direct_probe_answer"); put("session_id", p.session); put("sdp", sdp)
        })) { close(ProbeStage.ANSWER_FAILED); return }
        p.answered = true
        progress(p, ProbeStage.ANSWER_SENT)
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

    private fun channelOpened(p: Probe, channel: DataChannel) {
        if (!valid(p) || channel.state() != DataChannel.State.OPEN) return
        progress(p, ProbeStage.CHANNEL_OPEN)
        if (p.videoRequested && !p.videoReady) {
            val capture = checkNotNull(p.capture)
            val binding = "SV1 ${p.session} ${capture.epoch} ${capture.frameWidth} ${capture.frameHeight}"
            if (!channel.send(DataChannel.Buffer(ByteBuffer.wrap(binding.toByteArray()), false))) close()
            else { p.videoReady = true; streaming.onViewerConnected() }
        }
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
                            put("answerSent", p.answered)
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

    private fun progress(p: Probe, stage: ProbeStage) {
        val snapshot = p.progress.record(stage, SystemClock.elapsedRealtime()) ?: return
        Log.i("SphereDirectProbe", buildJsonObject {
            put("event", "native_probe_progress")
            put("iceProfile", p.iceProfile)
            put("stage", snapshot.stage.wireName)
            put("elapsedMs", snapshot.elapsedMs)
        }.toString())
    }

    private fun close(stage: ProbeStage = ProbeStage.CLOSED) {
        val old = peer
        peer = null
        old?.videoReady = false
        old?.let { streaming.detachEncodedViewer(it) }
        old?.let { progress(it, stage) }
        old?.statsBudget?.retire()
        // One already-closed JNI wrapper must not prevent retiring other threads.
        old?.channel?.let {
            runCatching { it.unregisterObserver() }
            runCatching { it.close() }
            runCatching { it.dispose() }
        }
        old?.connection?.let {
            runCatching { it.close() }
            runCatching { it.dispose() }
        }
        old?.video?.let { video ->
            video.close()
            Log.i("SphereDirectProbe", buildJsonObject {
                put("event", "native_video_retired")
                video.receipt().forEach { (key, value) -> put(key, value) }
            }.toString())
        }
        // Factory threads are also retired after every finite probe.
        val ownedFactory = factory
        factory = null
        runCatching { ownedFactory?.dispose() }
    }
}
