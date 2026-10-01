package com.sphereplatform.agent.streaming

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.view.Surface
import timber.log.Timber
import java.nio.ByteBuffer
import java.util.concurrent.ArrayBlockingQueue

/**
 * Asynchronous H.264 encoder using [MediaCodec] surface input mode.
 *
 * - Baseline Profile Level 3.1 → maximum WebCodecs compatibility
 * - [MediaFormat.KEY_LOW_LATENCY] = 1 (API 30+) for real-time streaming
 * - CBR for predictable bitrate over the network
 * - SPS/PPS cached and replayed when a new viewer connects
 *
 * Usage:
 * ```
 * val surface = encoder.start()       // returns InputSurface for VirtualDisplay
 * encoder.requestKeyFrame()           // on viewer reconnect
 * encoder.adjustBitrate(newBitrate)   // from AdaptiveBitrateController
 * encoder.stop()
 * ```
 */
class H264Encoder(
    private val config: EncoderConfig,
    private val onFrameReady: (ByteArray, FrameMetadata) -> Unit,
) {

    /**
     * FIX AUDIT-1.4: Callback при фатальной ошибке кодека.
     * Вызывается из MediaCodec callback thread — подписчик (StreamingManagerImpl)
     * должен выполнять restart АСИНХРОННО, не из этого callback'а.
     */
    var onEncoderError: ((Exception) -> Unit)? = null

    data class EncoderConfig(
        val width: Int = 720,
        val height: Int = 1280,
        val fps: Int = 30,
        val bitrateBps: Int = 1_500_000,
        val iFrameIntervalSec: Int = 1,
    ) {
        // LOW-3: validate at construction time, not silently at encode time
        init {
            require(width > 0) { "width must be positive" }
            require(height > 0) { "height must be positive" }
            require(bitrateBps > 0) { "bitrateBps must be positive" }
        }
    }

    data class FrameMetadata(
        val isKeyFrame: Boolean,
        val presentationTimeUs: Long,
        val sizeBytes: Int,
        val isCodecConfig: Boolean = false,
    )

    // -------------------------------------------------------------------------
    // SPS/PPS cache — sent to every newly-connected viewer before P-frames
    // -------------------------------------------------------------------------

    @Volatile var cachedSps: ByteArray? = null
        private set
    @Volatile var cachedPps: ByteArray? = null
        private set

    @Volatile private var codec: MediaCodec? = null
    private var inputSurface: Surface? = null
    private val inputLock = Any()
    @Volatile private var planarInputs: ArrayBlockingQueue<Int>? = null
    private var planarConverter: RgbaToI420? = null
    private var planarWindowNs = 0L
    private var planarSamples = 0
    private var planarConvertNs = 0L
    private var planarQueueNs = 0L
    private var callbackErrorReported = false

    // -------------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------------

    /**
     * Configure and start the encoder.
     * @return The [Surface] to be passed to [VirtualDisplayManager.createDisplay].
     */
    fun start(): Surface = checkNotNull(startCodec(false))

    /** Debug canary only: avoids the measured slow Google OMX graphics input. */
    internal fun startPlanar() { startCodec(true) }

    private fun startCodec(planar: Boolean): Surface? = synchronized(inputLock) {
        check(codec == null) { "Encoder already started" }
        val mime = MediaFormat.MIMETYPE_VIDEO_AVC
        val format = MediaFormat.createVideoFormat(mime, config.width, config.height).apply {
            setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                if (planar) MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Planar
                else MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface,
            )
            setInteger(MediaFormat.KEY_BIT_RATE, config.bitrateBps)
            setInteger(MediaFormat.KEY_FRAME_RATE, config.fps)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, config.iFrameIntervalSec)

            // Baseline Profile Level 3.1 — compatible with WebCodecs "avc1.42E01F"
            setInteger(
                MediaFormat.KEY_PROFILE,
                MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline,
            )
            setInteger(
                MediaFormat.KEY_LEVEL,
                MediaCodecInfo.CodecProfileLevel.AVCLevel31,
            )

            // Critical for real-time streaming (API 30+)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
            }

            // 0 = real-time priority (quality secondary)
            setInteger(MediaFormat.KEY_PRIORITY, 0)

            // CBR — predictable bitrate for stable WS throughput
            setInteger(
                MediaFormat.KEY_BITRATE_MODE,
                MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR,
            )
            if (planar) {
                setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT601_NTSC)
                setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED)
                setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_SDR_VIDEO)
            }
        }

        val c = if (planar) MediaCodec.createByCodecName("OMX.google.h264.encoder")
            else MediaCodec.createEncoderByType(mime)
        try {
            if (planar) {
                require(c.codecInfo.getCapabilitiesForType(mime).colorFormats.contains(
                    MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Planar))
                planarConverter = RgbaToI420(config.width, config.height)
                planarInputs = ArrayBlockingQueue(64)
            }
            // Name is platform-selected, not an assumption about hardware. A
            // bounded startup record makes slow emulator encoders diagnosable.
            Timber.i("H264Encoder selected codec=%s width=%d height=%d target_fps=%d bitrate_bps=%d input=%s",
                c.name, config.width, config.height, config.fps, config.bitrateBps,
                if (planar) "yuv420_planar" else "surface")
            c.setCallback(encoderCallback)
            c.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            val surface = if (planar) null else c.createInputSurface()
            inputSurface = surface
            callbackErrorReported = false
            cachedSps = null; cachedPps = null
            codec = c
            c.start()
            surface
        } catch (error: Exception) {
            codec = null; planarInputs = null; planarConverter = null
            runCatching { inputSurface?.release() }; inputSurface = null
            runCatching { c.release() }
            throw error
        }
    }

    fun stop() = synchronized(inputLock) {
        val owned = codec
        codec = null
        cachedSps = null; cachedPps = null
        planarInputs = null; planarConverter = null
        planarWindowNs = 0L; planarSamples = 0; planarConvertNs = 0L; planarQueueNs = 0L
        runCatching { owned?.stop() }.onFailure { Timber.w(it, "H264Encoder stop error") }
        runCatching { owned?.release() }.onFailure { Timber.w(it, "H264Encoder release error") }
        runCatching { inputSurface?.release() }.onFailure { Timber.w(it, "H264Encoder input Surface release error") }
        inputSurface = null
    }

    /** Nonblocking admission: skip a RAW image if the codec has no free input. */
    internal fun submitPlanarFrame(rgba: ByteBuffer, rowStride: Int, pixelStride: Int, ptsUs: Long): Boolean =
        synchronized(inputLock) {
            val owned = codec ?: return@synchronized false
            val available = planarInputs ?: return@synchronized false
            val converter = planarConverter ?: return@synchronized false
            require(ptsUs > 0)
            val index = available.poll() ?: return@synchronized false
            var queueAttempted = false
            try {
                val buffer = checkNotNull(owned.getInputBuffer(index))
                val started = System.nanoTime()
                converter.convert(rgba, rowStride, pixelStride, buffer)
                val converted = System.nanoTime()
                queueAttempted = true
                owned.queueInputBuffer(index, 0, converter.outputSize, ptsUs, 0)
                val queued = System.nanoTime()
                if (planarWindowNs == 0L) planarWindowNs = started
                planarSamples++; planarConvertNs += converted - started; planarQueueNs += queued - converted
                if (queued - planarWindowNs >= 5_000_000_000L) {
                    Timber.i("H264Encoder planar_input samples=%d convert_mean_ms=%.3f queue_mean_ms=%.3f",
                        planarSamples, planarConvertNs / planarSamples / 1_000_000.0,
                        planarQueueNs / planarSamples / 1_000_000.0)
                    planarWindowNs = queued; planarSamples = 0; planarConvertNs = 0L; planarQueueNs = 0L
                }
                true
            } catch (error: Exception) {
                if (!queueAttempted) available.offer(index)
                else onEncoderError?.invoke(error) // Do not retry an uncertain queue operation.
                throw error
            }
        }

    fun requestKeyFrame(): Boolean {
        val activeCodec = codec ?: return false
        return try {
            activeCodec.setParameters(Bundle().apply {
                putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0)
            })
            true
        } catch (error: IllegalStateException) {
            Timber.w(error, "H264Encoder: sync-frame request rejected by codec state")
            false
        } catch (error: IllegalArgumentException) {
            Timber.w(error, "H264Encoder: sync-frame request rejected by codec")
            false
        }
    }

    fun adjustBitrate(newBitrateBps: Int) {
        codec?.setParameters(Bundle().apply {
            putInt(MediaCodec.PARAMETER_KEY_VIDEO_BITRATE, newBitrateBps)
        })
    }

    // -------------------------------------------------------------------------
    // MediaCodec async callback
    // -------------------------------------------------------------------------

    private val encoderCallback = object : MediaCodec.Callback() {
        override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {
            val available = planarInputs
            // A stopped codec's callback cannot lend an index to a new session.
            if (this@H264Encoder.codec === codec && available != null && !available.offer(index)) {
                onEncoderError?.invoke(IllegalStateException("Planar input callback capacity exceeded"))
            }
        }

        override fun onOutputBufferAvailable(
            codec: MediaCodec,
            index: Int,
            info: MediaCodec.BufferInfo,
        ) {
            val packets = try {
                synchronized(inputLock) {
                    // stop() owns release; queued callbacks from that codec do
                    // not own any native buffer in the replacement session.
                    if (this@H264Encoder.codec !== codec) return
                    var failure: Exception? = null
                    var copied = emptyList<Pair<ByteArray, FrameMetadata>>()
                    try {
                        if (info.size > 0) {
                            codec.getOutputBuffer(index)?.let { buffer ->
                                val data = ByteArray(info.size)
                                buffer.position(info.offset)
                                buffer.get(data)
                                val isConfig = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                                copied = if (isConfig) splitNalUnits(data).map { nal ->
                                    nal to FrameMetadata(true, info.presentationTimeUs, nal.size, true)
                                } else listOf(data to FrameMetadata(
                                    info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0,
                                    info.presentationTimeUs, info.size))
                            }
                        }
                    } catch (error: Exception) {
                        failure = error
                    } finally {
                        // Return the buffer BEFORE calling a consumer, which
                        // may synchronously stop the encoder or throw. Native
                        // read/release is serialized against stop(), while the
                        // external callback never runs under this lock.
                        try { codec.releaseOutputBuffer(index, false) }
                        catch (error: Exception) {
                            if (failure == null) failure = error else failure.addSuppressed(error)
                        }
                    }
                    failure?.let { throw it }
                    for ((nal, metadata) in copied) {
                        if (metadata.isCodecConfig) when (findFirstNalType(nal)) {
                            7 -> cachedSps = nal
                            8 -> cachedPps = nal
                        }
                    }
                    copied
                }
            } catch (error: Exception) {
                reportCallbackError(codec, error)
                return
            }
            for ((data, metadata) in packets) {
                if (this@H264Encoder.codec !== codec) return
                try { onFrameReady(data, metadata) }
                catch (error: Exception) { reportCallbackError(codec, error); return }
            }
        }

        override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
            reportCallbackError(codec, e)
        }

        override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {
            if (this@H264Encoder.codec === codec) Timber.i("Encoder output format changed: $format")
        }
    }

    private fun splitNalUnits(data: ByteArray): List<ByteArray> {
        val nals = mutableListOf<ByteArray>()
        var start = -1
        var i = 0
        while (i < data.size - 2) {
            if (data[i] == 0.toByte() && data[i + 1] == 0.toByte() && data[i + 2] == 1.toByte()) {
                val isFourByte = (i > 0 && data[i - 1] == 0.toByte())
                val actualStart = if (isFourByte) i - 1 else i
                if (start != -1) {
                    nals.add(data.copyOfRange(start, actualStart))
                }
                start = actualStart
                i += 3
            } else {
                i++
            }
        }
        if (start != -1) {
            nals.add(data.copyOfRange(start, data.size))
        } else if (data.isNotEmpty()) {
            nals.add(data)
        }
        return nals
    }

    private fun findFirstNalType(data: ByteArray): Int {
        for (i in 0..data.size - 3) {
            if (data[i] == 0.toByte() && data[i + 1] == 0.toByte() && data[i + 2] == 1.toByte()) {
                if (i + 3 < data.size) {
                    return data[i + 3].toInt() and 0x1F
                }
            }
        }
        return -1
    }

    private fun reportCallbackError(owned: MediaCodec, error: Exception) {
        val consumer = synchronized(inputLock) {
            if (codec !== owned || callbackErrorReported) return
            callbackErrorReported = true
            onEncoderError
        }
        Timber.e(error, "H264Encoder: active codec callback failed")
        // The manager schedules recovery asynchronously. A faulty subscriber
        // cannot turn a contained codec failure into an uncaught Looper error.
        try { consumer?.invoke(error) }
        catch (subscriberError: Exception) { Timber.e(subscriberError, "H264Encoder: error subscriber failed") }
    }
}
