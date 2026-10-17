package com.sphereplatform.agent.direct

import android.content.Context
import android.net.ConnectivityManager
import android.os.Build
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
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicBoolean

/** Ten independently owned peers, bounded callbacks and exact monotonic/generation fences. */
class DirectProbeTransport(
    private val context: Context, private val scope: CoroutineScope,
    private val generation: () -> Long?, private val send: (Long, JsonObject) -> Boolean,
    private val streaming: com.sphereplatform.agent.streaming.StreamingManager,
    private val input: DirectInputHandler? = null,
) {
    private companion object { val initialized = AtomicBoolean(false) }
    private val fence = AtomicLong(0)
    private val queue = Channel<() -> Unit>(128)
    private val peers = java.util.concurrent.ConcurrentHashMap<String, Probe>()

    private class Probe(val session: String, val generation: Long, val token: Long, startedAt: Long, ttlMs: Int, val live: Boolean) {
        val lease = DirectVideoLease(startedAt, ttlMs, live)
        val expires get() = lease.expiresAt
        val progress = DirectProbeProgress(SystemClock.elapsedRealtime())
        val telemetry = DirectProbeTelemetry(startedAt)
        var factory: PeerConnectionFactory? = null
        var connection: PeerConnection? = null
        var channel: DataChannel? = null
        @Volatile var inputChannel: DataChannel? = null
        var answered = false
        var sequence = 1
        var lastEcho = 0L
        var iceProfile = "host"
        var videoRequested = false
        var sharedControl = false
        var keyboard = false
        var trickle = false
        var candidatesReceived = 0
        var candidatesSent = 0
        val localCandidates = ArrayList<DirectIceCandidate.Fields>()
        val remoteCandidates = ArrayList<DirectIceCandidate.Fields>()
        var remoteSet = false
        var capture: com.sphereplatform.agent.streaming.CaptureInputSession? = null
        var video: DirectEncodedVideoSource? = null
        @Volatile var videoReady = false
        val statsBudget = ProbeStatsBudget(live)
        var hostHints: List<String> = emptyList() // Peer-local routes; never serialized.
    }

    init {
        scope.launch {
            try {
                while (true) {
                    for (p in peers.values.toList()) {
                        if (!valid(p)) close(p, if (SystemClock.elapsedRealtime() >= p.expires) ProbeStage.EXPIRED else ProbeStage.CLOSED)
                        else if (p.videoRequested && p.capture != streaming.getInputSession()) close(p)
                        else collectNetwork(p)
                    }
                    val action = if (peers.isEmpty()) queue.receive() else withTimeoutOrNull(100) { queue.receive() }
                    try { action?.invoke() } catch (e: kotlinx.coroutines.CancellationException) {
                        throw e
                    } catch (_: Exception) { invalidate(); closeAll() }
                }
            } finally {
                closeAll()
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
    fun inputChannel(session: String): DirectInputChannel? {
        val p = peers[session] ?: return null
        val channel = p.inputChannel ?: return null
        val capture = p.capture ?: return null
        if (!BuildConfig.CONTINUOUS_INPUT_CANARY || !p.live || p.session != session || !valid(p) ||
            channel.state() != DataChannel.State.OPEN) return null
        return object : DirectInputChannel {
            override val keyboardSupported = p.keyboard
            override val session = p.session
            override val capture = capture
            override fun isCurrent() = valid(p) && p.inputChannel === channel && channel.state() == DataChannel.State.OPEN
            override fun send(message: JsonObject): Boolean {
                val bytes = message.toString().toByteArray(Charsets.UTF_8)
                return isCurrent() && bytes.size <= 1024 && channel.bufferedAmount() <= 1024 &&
                    channel.send(DataChannel.Buffer(ByteBuffer.wrap(bytes), false))
            }
        }
    }
    private fun valid(p: Probe) = peers[p.session] === p && p.token == fence.get() &&
        generation() == p.generation && p.lease.valid(SystemClock.elapsedRealtime()) &&
        (!p.videoRequested || p.capture?.let { streaming.isEncodedViewerCurrent(p, it) } == true)

    fun handle(message: JsonObject): Boolean {
        val kind = (message["type"] as? JsonPrimitive)?.contentOrNull
        if (kind !in setOf("direct_probe_offer", "direct_probe_close", "direct_probe_renew", "direct_probe_candidate")) return false
        val wsGeneration = generation() ?: return true
        val token = fence.get()
        val receivedAt = SystemClock.elapsedRealtime()
        enqueue {
            if (token != fence.get() || generation() != wsGeneration) return@enqueue
            val sid = message["session_id"]?.jsonPrimitive?.contentOrNull ?: return@enqueue
            if (!DirectProbeProtocol.validSession(sid)) return@enqueue
            if (kind == "direct_probe_close") {
                if (message.keys == setOf("type", "session_id")) peers[sid]?.let { close(it) }
            } else if (kind == "direct_probe_candidate") {
                val current = peers[sid] ?: return@enqueue
                if (!current.trickle || !valid(current) || current.candidatesReceived >= DirectIceCandidate.MAX
                    || message.keys != setOf("type", "session_id", "ice")) return@enqueue
                val candidate = DirectIceCandidate.parse(message["ice"]) ?: return@enqueue
                current.candidatesReceived++
                if (current.remoteSet) addCandidate(current, candidate) else current.remoteCandidates.add(candidate)
            } else if (kind == "direct_probe_renew") {
                val current = peers[sid] ?: return@enqueue
                if (current.session != sid || !current.live || message.keys !in setOf(LegacyVideoRenewal.BASE_KEYS, LegacyVideoRenewal.EXTENDED_KEYS)) return@enqueue
                val delivery = if (message.keys == LegacyVideoRenewal.EXTENDED_KEYS)
                    LegacyVideoRenewal.parse(message) ?: return@enqueue else null
                val sequence = message["sequence"]?.jsonPrimitive?.intOrNull ?: return@enqueue
                val ttl = message["ttl_ms"]?.jsonPrimitive?.intOrNull ?: return@enqueue
                val now = SystemClock.elapsedRealtime()
                if (!valid(current) || !current.lease.renew(sequence, ttl, receivedAt, now)) close(current)
                else if (delivery != null && current.videoReady) {
                    val remaining = delivery.ttlMs - (now - receivedAt)
                    current.capture?.let { capture ->
                        if (remaining > 0 && remaining <= 10000)
                            streaming.renewLegacyVideoDelivery(current, capture, delivery.enabled, remaining.toInt())
                    }
                }
            } else {
                val sdp = message["sdp"]?.jsonPrimitive?.contentOrNull ?: return@enqueue
                val ttl = message["ttl_ms"]?.jsonPrimitive?.intOrNull ?: return@enqueue
                val mode = message["media"]?.jsonPrimitive?.contentOrNull
                val live = mode == DirectVideoProtocol.LIVE_MODE
                val video = live || mode == DirectVideoProtocol.MODE
                val expected = setOf("type", "session_id", "sdp", "ttl_ms") +
                    (if (video) setOf("media") else emptySet()) + (if ("ice" in message) setOf("ice") else emptySet()) +
                    (if ("shared_control" in message) setOf("shared_control") else emptySet()) +
                    (if ("keyboard" in message) setOf("keyboard") else emptySet()) +
                    (if ("trickle_ice" in message) setOf("trickle_ice") else emptySet())
                if (peers.size >= 10 || peers.containsKey(sid) || message.keys != expected || ttl !in 1..DirectProbeProtocol.MAX_TTL_MS ||
                    !(if (video) DirectVideoProtocol.validSdp(sdp, true) else DirectProbeProtocol.validSdp(sdp))) return@enqueue
                val grant = if ("ice" in message) DirectProbeTurnGrant.parse(message["ice"], sid) ?: return@enqueue else null
                if (SystemClock.elapsedRealtime() >= receivedAt + ttl) return@enqueue
                if (live && grant != null) return@enqueue // Relay renewal has a separate credential lifetime.
                val sharedControl = message["shared_control"] == JsonPrimitive(true)
                if ("shared_control" in message && (!sharedControl || !live)) return@enqueue
                val keyboard = message["keyboard"] == JsonPrimitive(true)
                if ("keyboard" in message && (!keyboard || !sharedControl)) return@enqueue
                val trickle = message["trickle_ice"] == JsonPrimitive(true)
                if ("trickle_ice" in message && (!trickle || !live || grant != null)) return@enqueue
                open(Probe(sid, wsGeneration, token, receivedAt, ttl, live).apply {
                    videoRequested = video; this.sharedControl = sharedControl; this.trickle = trickle; this.keyboard = keyboard
                }, sdp, grant)
            }
        }
        return true
    }

    private fun open(p: Probe, sdp: String, grant: DirectProbeTurnGrant?) {
        check(peers.putIfAbsent(p.session, p) == null)
        try {
            val localAddresses = runCatching {
                NetworkInterface.getNetworkInterfaces()?.asSequence()?.take(32)?.flatMap {
                    it.inetAddresses.asSequence().take(8)
                }?.filterIsInstance<Inet4Address>()?.mapNotNull { it.hostAddress }?.toList().orEmpty()
            }.getOrDefault(emptyList())
            // LDPlayer may spoof Build.HARDWARE as qcom and use a nonstandard
            // NAT subnet. The ABI and app's actual link routes avoid guessing
            // 10.0.2.2 on such guests. Reading these routes sends no network traffic.
            val x86Guest = Build.SUPPORTED_ABIS.any { it == "x86" || it == "x86_64" }
            val gateways = runCatching {
                val manager = context.getSystemService(ConnectivityManager::class.java)
                val network = manager.activeNetwork
                network?.let { manager.getLinkProperties(it) }?.routes.orEmpty()
                    .filter { it.isDefaultRoute }.take(8).mapNotNull { (it.gateway as? Inet4Address)?.hostAddress }
            }.getOrDefault(emptyList())
            p.hostHints = EmulatorHostCandidates.hints(localAddresses, gateways, x86Guest)
            val hostHints = EmulatorHostCandidates.augment(sdp, p.hostHints)
            Log.i("SphereDirectProbe", buildJsonObject {
                put("event", "native_emulator_host_candidates")
                put("added", hostHints.added)
                put("x86Guest", x86Guest)
                put("defaultGatewayCount", gateways.size)
                put("connected", false) // These hints are never reported as an established path.
            }.toString())
            if (p.videoRequested) {
                check(AvcReceiveCapabilities.accepts(sdp, streaming.encodedProfileLevelId())) { "receiver_level_insufficient" }
                p.capture = streaming.attachEncodedViewer(p) { frame ->
                    if (p.videoReady) p.video?.submit(frame)
                } ?: error("active_capture_required")
                p.video = DirectEncodedVideoSource(checkNotNull(p.capture), { valid(p) },
                    { if (valid(p)) streaming.requestDirectKeyFrame() }, { enqueue { if (peers[p.session] === p) close(p) } },
                    streaming.encodedProfileLevelId(), { bitrate, fps ->
                        p.capture?.let { streaming.onDirectRateEstimate(p, it, bitrate, fps) }
                    }, streaming.encodedRateLimits().first, streaming.encodedInitialBitrate())
            }
            // Validate before creating native threads. Ordinary builds keep an empty host-only profile.
            val iceProfile = DirectProbeIceProfile.fromUrl(BuildConfig.DIRECT_PROBE_STUN_URL)
            p.iceProfile = if (grant == null) iceProfile.name else "turn"
            progress(p, ProbeStage.OFFER_RECEIVED)
            publishTelemetry(p, p.telemetry.report(ProbeStage.OFFER_RECEIVED, p.iceProfile, false, SystemClock.elapsedRealtime()))
            if (p.factory == null) {
                if (initialized.compareAndSet(false, true)) {
                    try {
                        PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(context)
                            .setFieldTrials(DirectEncodedVideoSource.FIELD_TRIALS)
                            .setEnableInternalTracer(false).createInitializationOptions())
                    } catch (error: Exception) { initialized.set(false); throw error }
                }
                // Modern WebRTC factories own their Environment/field trials.
                // Apply the coded-reference policy to every rebuilt factory,
                // rather than relying only on deprecated process initialization.
                val builder = PeerConnectionFactory.builder()
                    .setFieldTrials(DirectEncodedVideoSource.FIELD_TRIALS)
                p.video?.let { builder.setVideoEncoderFactory(it.encoderFactory) }
                p.factory = builder.createPeerConnectionFactory()
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
            p.connection = p.factory?.createPeerConnection(config, object : PeerConnection.Observer {
                override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
                override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
                override fun onIceCandidate(candidate: IceCandidate) {
                    enqueue {
                        if (!valid(p) || !p.trickle || p.candidatesSent + p.localCandidates.size >= DirectIceCandidate.MAX) return@enqueue
                        val fields = DirectIceCandidate.parse(buildJsonObject {
                            put("candidate", candidate.sdp); put("sdpMid", candidate.sdpMid)
                            put("sdpMLineIndex", candidate.sdpMLineIndex)
                        }) ?: return@enqueue
                        if (p.answered) sendCandidate(p, fields) else p.localCandidates.add(fields)
                    }
                }
                override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
                override fun onAddStream(stream: MediaStream) = Unit
                override fun onRemoveStream(stream: MediaStream) = Unit
                override fun onRenegotiationNeeded() { enqueue { if (valid(p) && p.answered && !p.videoRequested) close(p) } }
                override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                    if (state in setOf(PeerConnection.IceConnectionState.FAILED, PeerConnection.IceConnectionState.CLOSED))
                        enqueue { if (peers[p.session] === p) close(p, ProbeStage.CONNECTION_FAILED) }
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
                        if (valid(p) && p.live && BuildConfig.CONTINUOUS_INPUT_CANARY && input != null &&
                            channel.label() == (if (p.sharedControl) "sphere-control-v2" else "sphere-control-v1") && p.inputChannel == null) {
                            p.inputChannel = channel
                            channel.registerObserver(object : DataChannel.Observer {
                                override fun onBufferedAmountChange(previous: Long) = Unit
                                override fun onStateChange() {
                                    enqueue {
                                        if (p.sharedControl && valid(p) && channel.state() == DataChannel.State.OPEN) {
                                            inputChannel(p.session)?.let { if (!input.sharedGranted(it)) close(p) }
                                        }
                                        if (peers[p.session] === p && p.inputChannel === channel && channel.state() in
                                            setOf(DataChannel.State.CLOSING, DataChannel.State.CLOSED)) input.directClosed(p.session)
                                    }
                                }
                                override fun onMessage(buffer: DataChannel.Buffer) {
                                    val text = if (!buffer.binary && buffer.data.remaining() in 1..(if (p.keyboard) 8192 else 1024))
                                        Charsets.UTF_8.decode(buffer.data).toString() else ""
                                    // V2 has its own bounded per-participant actor. MOVE does not
                                    // allocate a closure in the shared signaling/stats mailbox.
                                    val dispatch = letDispatch@{
                                        if (valid(p) && p.inputChannel === channel) {
                                            // SCTP onMessage may precede the queued OPEN-state
                                            // callback. Establish the authenticated shared grant
                                            // synchronously before the first participant OPEN;
                                            // otherwise a fast localhost client loses that OPEN.
                                            if (p.sharedControl) {
                                                val current = inputChannel(p.session)
                                                if (current == null || !input.sharedGranted(current)) {
                                                    enqueue { if (peers[p.session] === p) close(p) }
                                                    return@letDispatch
                                                }
                                            }
                                            val message = runCatching { Json.parseToJsonElement(text) as? JsonObject }.getOrNull()
                                            if (message == null || !input.directMessage(p.session, message)) input.directClosed(p.session)
                                        }
                                    }
                                    if (p.sharedControl) dispatch() else enqueue(dispatch)
                                }
                            })
                            if (p.sharedControl && channel.state() == DataChannel.State.OPEN) {
                                inputChannel(p.session)?.let { if (!input.sharedGranted(it)) close(p) }
                            }
                            return@enqueue
                        }
                        if (!valid(p) || p.channel != null || channel.label() !=
                            (if (p.live) DirectVideoProtocol.LIVE_LABEL else if (p.videoRequested) DirectVideoProtocol.LABEL else DirectProbeProtocol.LABEL)) {
                            channel.close(); channel.dispose()
                            if (peers[p.session] === p) close(p)
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
            if (p.videoRequested) {
                val maximum = streaming.encodedRateLimits().first.coerceIn(100_000, 32_000_000)
                p.connection?.setBitrate(null, streaming.encodedInitialBitrate().coerceIn(100_000, maximum), maximum)
            }
            progress(p, ProbeStage.PEER_READY)
            p.connection?.setRemoteDescription(observer(p, ProbeStage.REMOTE_FAILED, set = {
                p.remoteSet = true
                val candidates = p.remoteCandidates.toList(); p.remoteCandidates.clear()
                candidates.forEach { if (valid(p)) addCandidate(p, it) }
                if (!valid(p)) return@observer
                progress(p, ProbeStage.REMOTE_SET)
                p.video?.let { video ->
                    p.connection?.addTrack(video.start(checkNotNull(p.factory)), listOf("sphere-screen"))?.let { sender ->
                        val limits = streaming.encodedRateLimits()
                        val parameters = sender.parameters
                        parameters.encodings.forEach { encoding ->
                            encoding.maxBitrateBps = limits.first
                            encoding.maxFramerate = limits.second
                        }
                        parameters.degradationPreference = RtpParameters.DegradationPreference.MAINTAIN_RESOLUTION
                        check(sender.setParameters(parameters)) { "rtp_source_limits_refused" }
                    }
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
            }), SessionDescription(SessionDescription.Type.OFFER, hostHints.sdp))
        } catch (failure: Exception) {
            // Finite adapter discriminators, never platform exception text, SDP
            // or peer addresses. Reconnect failures used to hide the actual cause.
            val detail = when (failure.message) {
                "receiver_level_insufficient", "active_capture_required", "peer_unavailable" -> failure.message
                else -> "native_peer_adapter"
            }
            Log.w("SphereDirectProbe", "native_peer_setup_failure:" + detail)
            close(p, ProbeStage.OPEN_FAILED)
        }
    }

    private fun observer(p: Probe, failed: ProbeStage, set: () -> Unit = {}, create: (SessionDescription) -> Unit = {}) = object : SdpObserver {
        override fun onSetSuccess() { enqueue { if (valid(p)) try { set() } catch (_: Exception) { close(p, failed) } } }
        override fun onCreateSuccess(description: SessionDescription) { enqueue { if (valid(p)) try { create(description) } catch (_: Exception) { close(p, failed) } } }
        override fun onSetFailure(error: String) { enqueue { if (peers[p.session] === p) close(p, failed) } }
        override fun onCreateFailure(error: String) { enqueue { if (peers[p.session] === p) close(p, failed) } }
    }

    private fun answer(p: Probe) {
        val connection = p.connection ?: return
        if (!valid(p) || p.answered || !p.trickle && connection.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) return
        val sdp = connection.localDescription?.description ?: return
        if (!(if (p.videoRequested) DirectVideoProtocol.validSdp(sdp, false) else DirectProbeProtocol.validSdp(sdp)) || !send(p.generation, buildJsonObject {
            put("type", "direct_probe_answer"); put("session_id", p.session); put("sdp", sdp)
        })) { close(p, ProbeStage.ANSWER_FAILED); return }
        p.answered = true
        progress(p, ProbeStage.ANSWER_SENT)
        val candidates = p.localCandidates.toList(); p.localCandidates.clear()
        candidates.forEach { if (valid(p)) sendCandidate(p, it) }
    }

    private fun sendCandidate(p: Probe, fields: DirectIceCandidate.Fields) {
        if (!valid(p) || !p.trickle || !p.answered || p.candidatesSent >= DirectIceCandidate.MAX) return
        p.candidatesSent++
        if (!send(p.generation, buildJsonObject {
            put("type", "direct_probe_candidate"); put("session_id", p.session)
            put("ice", DirectIceCandidate.wire(fields))
        })) close(p, ProbeStage.ANSWER_FAILED)
    }

    private fun addCandidate(p: Probe, fields: DirectIceCandidate.Fields) {
        if (p.connection?.addIceCandidate(IceCandidate(fields.mid, fields.index, fields.candidate)) != true)
            close(p, ProbeStage.REMOTE_FAILED)
    }

    private fun echo(p: Probe, text: String) {
        if (!valid(p)) { if (peers[p.session] === p) close(p); return }
        val now = SystemClock.elapsedRealtime()
        val echoed = if (p.live && p.sequence in 1..1000000) "SL1 ${p.session} ${p.sequence}".takeIf { it == text }
            else if (p.live) null else DirectProbeProtocol.echo(text, p.session, p.sequence)
        val channel = p.channel
        if (echoed == null || (p.lastEcho != 0L && now - p.lastEcho < 100) || channel == null ||
            channel.bufferedAmount() > 1024 || !channel.send(DataChannel.Buffer(ByteBuffer.wrap(echoed.toByteArray()), false))) {
            close(p); return
        }
        p.sequence++; p.lastEcho = now
    }

    private fun channelOpened(p: Probe, channel: DataChannel) {
        if (!valid(p) || channel.state() != DataChannel.State.OPEN) return
        progress(p, ProbeStage.CHANNEL_OPEN)
        if (p.videoRequested && !p.videoReady) {
            val capture = checkNotNull(p.capture)
            val binding = "SV1 ${p.session} ${capture.epoch} ${capture.frameWidth} ${capture.frameHeight}"
            if (!channel.send(DataChannel.Buffer(ByteBuffer.wrap(binding.toByteArray()), false))) close(p)
            else { p.videoReady = true; streaming.requestDirectKeyFrame() }
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
                val projected = if (rows.size <= DirectProbeNetwork.MAX_ROWS)
                    rows.map { ProbeStatsRow(it.type, it.members, it.id) } else emptyList()
                val summary = if (rows.size <= DirectProbeNetwork.MAX_ROWS) DirectProbeNetwork.summary(projected) else null
                val hostSelected = DirectProbeNetwork.emulatorHostSelected(projected, p.hostHints)
                enqueue {
                    if (p.statsBudget.complete() && valid(p) && summary != null) {
                        val age = (SystemClock.elapsedRealtime() - sampledAt).coerceAtLeast(0)
                        val snapshot = buildJsonObject {
                            put("event", "native_ice_summary")
                            put("iceProfile", p.iceProfile)
                            put("answerSent", p.answered)
                            put("sampleAgeMs", age)
                            put("network", summary)
                            put("emulatorHostSelected", hostSelected?.let(::JsonPrimitive) ?: JsonNull)
                        }
                        p.telemetry.observe(summary, sampledAt)
                        val report = p.telemetry.report(p.progress.latest?.stage ?: ProbeStage.OFFER_RECEIVED,
                            p.iceProfile, p.answered, SystemClock.elapsedRealtime())
                        // Keep detailed local logging finite even on an eight-hour viewer.
                        if (report?.get("sequence")?.jsonPrimitive?.intOrNull?.let { it <= 32 } == true)
                            Log.i("SphereDirectProbe", snapshot.toString())
                        publishTelemetry(p, report)
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

    private fun publishTelemetry(p: Probe, sample: JsonObject?) {
        if (sample == null || p.token != fence.get() || generation() != p.generation) return
        // A full/stale signaling queue drops optional diagnostics, never the peer.
        runCatching { send(p.generation, buildJsonObject {
            put("type", "direct_probe_telemetry"); put("session_id", p.session); put("sample", sample)
        }) }
    }

    private fun closeAll() { peers.values.toList().forEach { close(it) } }

    private fun close(old: Probe, stage: ProbeStage = ProbeStage.CLOSED) {
        if (!peers.remove(old.session, old)) return
        old?.videoReady = false
        old?.let { input?.directClosed(it.session) }
        old?.let { streaming.detachEncodedViewer(it) }
        old?.let { progress(it, stage) }
        old?.let { publishTelemetry(it, it.telemetry.report(stage, it.iceProfile, it.answered, SystemClock.elapsedRealtime())) }
        old?.statsBudget?.retire()
        // One already-closed JNI wrapper must not prevent retiring other threads.
        old?.channel?.let {
            runCatching { it.unregisterObserver() }
            runCatching { it.close() }
            runCatching { it.dispose() }
        }
        old?.inputChannel?.let {
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
        val ownedFactory = old.factory
        old.factory = null
        runCatching { ownedFactory?.dispose() }
    }
}
