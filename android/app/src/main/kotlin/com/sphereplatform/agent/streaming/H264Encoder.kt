package com.sphereplatform.agent.streaming

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.view.Surface
import timber.log.Timber
import java.nio.ByteBuffer

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
    )

    // -------------------------------------------------------------------------
    // SPS/PPS cache — sent to every newly-connected viewer before P-frames
    // -------------------------------------------------------------------------

    @Volatile var cachedSps: ByteArray? = null
        private set
    @Volatile var cachedPps: ByteArray? = null
        private set

    private var codec: MediaCodec? = null

    // -------------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------------

    /**
     * Configure and start the encoder.
     * @return The [Surface] to be passed to [VirtualDisplayManager.createDisplay].
     */
    fun start(): Surface {
        val mime = MediaFormat.MIMETYPE_VIDEO_AVC
        val format = MediaFormat.createVideoFormat(mime, config.width, config.height).apply {
            setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface,
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
        }

        val c = MediaCodec.createEncoderByType(mime)
        c.setCallback(encoderCallback)
        c.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        val inputSurface = c.createInputSurface()
        c.start()
        codec = c
        return inputSurface
    }

    fun stop() {
        try {
            codec?.stop()
            codec?.release()
        } catch (e: Exception) {
            Timber.e(e, "H264Encoder.stop() error")
        } finally {
            codec = null
        }
    }

    fun requestKeyFrame() {
        codec?.setParameters(Bundle().apply {
            putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0)
        })
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
            // Surface encoder: input buffers not used — frames arrive via Surface
        }

        override fun onOutputBufferAvailable(
            codec: MediaCodec,
            index: Int,
            info: MediaCodec.BufferInfo,
        ) {
            // Codec config (SPS/PPS) — cache and release, do not forward as a frame
            if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) {
                codec.getOutputBuffer(index)?.let { buf ->
                    handleCodecConfig(buf, info)
                }
                codec.releaseOutputBuffer(index, false)
                return
            }

            if (info.size == 0) {
                codec.releaseOutputBuffer(index, false)
                return
            }

            val buffer = codec.getOutputBuffer(index) ?: run {
                codec.releaseOutputBuffer(index, false)
                return
            }

            val isKeyFrame = info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
            val data = ByteArray(info.size)
            buffer.position(info.offset)
            buffer.get(data)

            onFrameReady(
                data,
                FrameMetadata(
                    isKeyFrame = isKeyFrame,
                    presentationTimeUs = info.presentationTimeUs,
                    sizeBytes = info.size,
                ),
            )
            codec.releaseOutputBuffer(index, false)
        }

        override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
            Timber.e(e, "H264Encoder MediaCodec error — attempting restart")
            restartEncoder()
        }

        override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {
            Timber.i("Encoder output format changed: $format")
        }
    }

    private fun handleCodecConfig(buffer: ByteBuffer, info: MediaCodec.BufferInfo) {
        val data = ByteArray(info.size)
        buffer.position(info.offset)
        buffer.get(data)
        
        // Split the buffer into individual NAL units
        val nals = splitNalUnits(data)
        for (nal in nals) {
            val nalType = findFirstNalType(nal)
            when (nalType) {
                7 -> cachedSps = nal
                8 -> cachedPps = nal
            }
            // Send SPS/PPS immediately so the frontend gets them even if onViewerConnected was called too early
            onFrameReady(
                nal,
                FrameMetadata(
                    isKeyFrame = true,
                    presentationTimeUs = info.presentationTimeUs,
                    sizeBytes = nal.size,
                )
            )
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

    private fun restartEncoder() {
        // StreamingManagerImpl observes errors via onFrameReady path.
        // Restart is triggered externally to avoid re-entrant MediaCodec calls.
        Timber.w("H264Encoder: restart requested from error callback")
    }
}
