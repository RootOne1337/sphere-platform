package com.sphereplatform.agent.direct

import com.sphereplatform.agent.streaming.CaptureInputSession
import com.sphereplatform.agent.streaming.EncodedCaptureFrame
import org.webrtc.*
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * An explicit experimental VideoEncoder adapter for the already-running MediaCodec.
 * Coded access units retain their identity through WebRTC's generic native Buffer.
 * No second MediaProjection, raw pixel conversion, Surface or encoder is allocated.
 */
internal class DirectEncodedVideoSource(
    private val capture: CaptureInputSession,
    private val valid: () -> Boolean,
    private val requestKey: () -> Unit,
    private val failed: () -> Unit,
    private val profileLevelId: String = "42e01f",
    private val onRate: (Int, Int) -> Unit = { _, _ -> },
) {
    companion object {
        // MediaCodec has already encoded these reference-dependent pictures.
        // The raw-frame dropper cannot safely discard one before this adapter.
        const val FIELD_TRIALS = "WebRTC-FrameDropper/Disabled/"
    }
    private val budget = EncodedVideoBudget()
    private val outputBudget = EncodedVideoBudget()
    private val received = AtomicLong()
    private val forwarded = AtomicLong()
    private val rejected = AtomicLong()
    private val invalid = AtomicLong()
    private val encodeCalls = AtomicLong()
    private val encoderRequests = AtomicLong()
    private val encoderRefusals = AtomicLong()
    private val encoderInitializations = AtomicLong()
    private val requestedLevel = AtomicLong()
    private val waitingKey = AtomicLong()
    private val pausedFrames = AtomicLong()
    private val keyHints = AtomicLong()
    private val syncRequests = AtomicLong()
    private val forwardedBytes = AtomicLong()
    private val targetBitrate = AtomicLong()
    private val targetFramerate = AtomicLong()
    private val order = EncodedVideoOrder()
    private val sourceLock = Any()
    private var source: VideoSource? = null
    private var track: VideoTrack? = null
    @Volatile private var closed = false
    private var lastKeyRequestNs = 0L
    private val broken = AtomicBoolean(false)

    private fun requestSync() {
        val now = System.nanoTime()
        synchronized(this) {
            if (now - lastKeyRequestNs < 500_000_000L) return
            lastKeyRequestNs = now
        }
        syncRequests.incrementAndGet()
        requestKey()
    }
    private fun fail() { if (broken.compareAndSet(false, true)) failed() }

    val encoderFactory = object : VideoEncoderFactory {
        override fun getSupportedCodecs() = arrayOf(VideoCodecInfo("H264", mapOf(
            "profile-level-id" to profileLevelId, "level-asymmetry-allowed" to "1", "packetization-mode" to "1"), emptyList()))
        override fun createEncoder(info: VideoCodecInfo): VideoEncoder? {
            encoderRequests.incrementAndGet()
            requestedLevel.set(info.params["profile-level-id"]?.takeIf {
                Regex("[0-9a-fA-F]{6}").matches(it)
            }?.takeLast(2)?.toLong(16) ?: 0L)
            // The negotiated receiver level may be higher than this already-coded
            // source. WebRTC also carries independent fmtp parameters into the
            // factory. Equality of the complete map incorrectly rejects a valid
            // encoder: check the coded profile, level and packetization instead.
            if (info.name.equals("H264", true) && AvcReceiveCapabilities.acceptsParameters(info.params, profileLevelId))
                return ForwardEncoder()
            encoderRefusals.incrementAndGet()
            return null
        }
    }

    fun start(factory: PeerConnectionFactory): VideoTrack = synchronized(sourceLock) {
        check(!closed && source == null)
        val created = factory.createVideoSource(true)
        source = created
        // Encoded pictures cannot be cropped, rescaled or selectively dropped as raw
        // pixels. Keep source dimensions and coded order; use WebRTC's aligned
        // clock independently of its raw-picture crop/drop suggestions.
        created.setVideoProcessor(object : VideoProcessor {
            private var sink: VideoSink? = null
            override fun setSink(sink: VideoSink?) { this.sink = sink }
            override fun onCapturerStarted(success: Boolean) = Unit
            override fun onCapturerStopped() = Unit
            override fun onFrameCaptured(frame: VideoFrame) { sink?.onFrame(frame) }
            override fun onFrameCaptured(frame: VideoFrame, parameters: VideoProcessor.FrameAdaptationParameters) {
                // adaptFrame also translates the capture clock into WebRTC's
                // monotonic clock. Bypassing that timestamp with the raw crop/drop
                // policy can let the receive buffer drift on a host-local path.
                // Retain the same coded buffer: no pixel conversion, scaling,
                // reference-frame drop or additional encoded payload allocation.
                val target = sink ?: return
                frame.buffer.retain()
                val aligned = VideoFrame(frame.buffer, frame.rotation, parameters.timestampNs)
                try { target.onFrame(aligned) } finally { aligned.release() }
            }
        })
        created.capturerObserver.onCapturerStarted(true)
        factory.createVideoTrack("sphere-screen", created).also { track = it }
    }

    fun submit(frame: EncodedCaptureFrame) {
        if (!valid() || broken.get() || frame.capture != capture) return
        received.incrementAndGet()
        val size = frame.data.size.toLong() + if (frame.keyFrame) (frame.sps?.size ?: 0) + (frame.pps?.size ?: 0) else 0
        val release = if (size <= Int.MAX_VALUE) budget.reserve(size.toInt()) else null
        if (release == null) { rejected.incrementAndGet(); order.invalidate(); requestSync(); return }
        val bytes = EncodedVideoAccessUnit.prepare(frame, profileLevelId)
        if (bytes == null) { invalid.incrementAndGet(); release(); order.invalidate(); requestSync(); return }
        val buffer = CodedBuffer(frame, bytes, release)
        val videoFrame = VideoFrame(buffer, 0, frame.timestampNs)
        try {
            synchronized(sourceLock) {
                if (!closed && valid()) source?.capturerObserver?.onFrameCaptured(videoFrame)
            }
        } catch (_: Exception) { fail() }
        finally { videoFrame.release() }
    }

    fun close() {
        val owned = synchronized(sourceLock) {
            if (closed) return
            closed = true; budget.close(); outputBudget.close(); order.invalidate()
            (track to source).also { track = null; source = null }
        }
        runCatching { owned.second?.capturerObserver?.onCapturerStopped() }
        runCatching { owned.first?.dispose() }
        runCatching { owned.second?.dispose() }
    }

    /** One aggregate at retirement; no SDP, addresses, image bytes or per-frame logs. */
    fun receipt(): Map<String, Long> = mapOf(
        "received" to received.get(), "forwarded" to forwarded.get(),
        "budgetRejected" to rejected.get(), "invalidAccessUnits" to invalid.get(),
        "encodeCalls" to encodeCalls.get(), "keyframeWaitDrops" to waitingKey.get(),
        "encoderRequests" to encoderRequests.get(), "encoderRefusals" to encoderRefusals.get(),
        "encoderInitializations" to encoderInitializations.get(), "requestedLevel" to requestedLevel.get(),
        "pausedFrames" to pausedFrames.get(), "keyframeHints" to keyHints.get(),
        "syncRequests" to syncRequests.get(), "forwardedBytes" to forwardedBytes.get(),
        "targetBitrateBps" to targetBitrate.get(), "targetFramerate" to targetFramerate.get(),
        "failed" to if (broken.get()) 1L else 0L,
        "retainedInputFrames" to budget.retained().first.toLong(),
        "retainedInputBytes" to budget.retained().second.toLong(),
        "retainedOutputFrames" to outputBudget.retained().first.toLong(),
        "retainedOutputBytes" to outputBudget.retained().second.toLong(),
    )

    private inner class CodedBuffer(
        encoded: EncodedCaptureFrame, private var bytes: ByteArray?, private val freed: () -> Unit,
    ) : VideoFrame.Buffer {
        val sequence = encoded.sequence
        val timestampNs = encoded.timestampNs
        val keyFrame = encoded.keyFrame
        private val refs = AtomicInteger(1)
        override fun getWidth() = capture.frameWidth
        override fun getHeight() = capture.frameHeight
        override fun retain() { check(refs.incrementAndGet() > 1) }
        override fun release() { if (refs.decrementAndGet() == 0) { bytes = null; freed() } }
        override fun toI420(): VideoFrame.I420Buffer? { fail(); return null }
        override fun cropAndScale(x: Int, y: Int, width: Int, height: Int, scaleWidth: Int, scaleHeight: Int): VideoFrame.Buffer {
            if (x != 0 || y != 0 || width != this.width || height != this.height || scaleWidth != width || scaleHeight != height) fail()
            retain(); return this
        }
        fun data(): ByteArray? = bytes
    }

    private inner class ForwardEncoder : VideoEncoder {
        private var callback: VideoEncoder.Callback? = null
        private var paused = false
        override fun initEncode(settings: VideoEncoder.Settings, callback: VideoEncoder.Callback): VideoCodecStatus {
            encoderInitializations.incrementAndGet()
            if (settings.width != capture.frameWidth || settings.height != capture.frameHeight || settings.numberOfSimulcastStreams > 1) {
                fail(); return VideoCodecStatus.ERR_SIZE
            }
            this.callback = callback; order.invalidate(); requestSync()
            return VideoCodecStatus.OK
        }
        override fun release(): VideoCodecStatus { callback = null; order.invalidate(); return VideoCodecStatus.OK }
        override fun encode(frame: VideoFrame, info: VideoEncoder.EncodeInfo): VideoCodecStatus {
            encodeCalls.incrementAndGet()
            val sink = callback ?: return VideoCodecStatus.UNINITIALIZED
            val coded = frame.buffer as? CodedBuffer ?: run { fail(); return VideoCodecStatus.ERR_PARAMETER }
            val bytes = coded.data() ?: return VideoCodecStatus.NO_OUTPUT
            if (!valid() || broken.get()) { order.invalidate(); return VideoCodecStatus.NO_OUTPUT }
            if (paused) { pausedFrames.incrementAndGet(); order.invalidate(); return VideoCodecStatus.NO_OUTPUT }
            if (info.frameTypes.contains(EncodedImage.FrameType.VideoFrameKey) && !coded.keyFrame) {
                // Request a real MediaCodec IDR without discarding a valid
                // reference chain while that asynchronous request completes.
                // An actual missing reference is still rejected by order below.
                keyHints.incrementAndGet(); requestSync()
            }
            if (!order.admit(coded.sequence, coded.timestampNs, coded.keyFrame)) {
                waitingKey.incrementAndGet()
                requestSync(); return VideoCodecStatus.NO_OUTPUT
            }
            // RTP may retain the EncodedImage after this callback. Bound those
            // direct buffers separately until the native owner releases them.
            val release = outputBudget.reserve(bytes.size) ?: run {
                rejected.incrementAndGet(); order.invalidate(); requestSync(); return VideoCodecStatus.NO_OUTPUT
            }
            var owned: EncodedImage? = null
            return try {
                val payload = ByteBuffer.allocateDirect(bytes.size).apply { put(bytes); flip() }
                val image = EncodedImage.builder().setBuffer(payload, release)
                    .setEncodedWidth(capture.frameWidth).setEncodedHeight(capture.frameHeight)
                    .setCaptureTimeNs(frame.timestampNs).setRotation(0)
                    .setFrameType(if (coded.keyFrame) EncodedImage.FrameType.VideoFrameKey else EncodedImage.FrameType.VideoFrameDelta)
                    .createEncodedImage()
                owned = image
                sink.onEncodedFrame(image, VideoEncoder.CodecSpecificInfoH264())
                forwarded.incrementAndGet()
                forwardedBytes.addAndGet(bytes.size.toLong())
                VideoCodecStatus.OK
            }
            catch (_: Exception) { fail(); VideoCodecStatus.ERROR }
            finally { owned?.release() ?: release() }
        }
        override fun setRateAllocation(allocation: VideoEncoder.BitrateAllocation, framerate: Int): VideoCodecStatus {
            targetBitrate.set(allocation.sum.coerceAtLeast(0).toLong())
            targetFramerate.set(framerate.coerceAtLeast(0).toLong())
            val wasPaused = paused
            paused = allocation.sum <= 0
            if (paused || wasPaused != paused) order.invalidate()
            if (wasPaused && !paused) requestSync()
            // Handoff is a single coalesced source estimate. The source adapts raw
            // cadence/MediaCodec bitrate; the encoded reference chain remains intact.
            if (valid() && !closed) onRate(allocation.sum.coerceAtLeast(0), framerate.coerceAtLeast(0))
            return VideoCodecStatus.OK
        }
        override fun getScalingSettings(): VideoEncoder.ScalingSettings = VideoEncoder.ScalingSettings.OFF
        override fun getImplementationName() = "SphereSharedH264"
        override fun isHardwareEncoder() = false
    }
}
