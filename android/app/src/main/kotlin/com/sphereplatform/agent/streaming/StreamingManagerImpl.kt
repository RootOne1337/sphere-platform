package com.sphereplatform.agent.streaming

import android.content.Context
import android.media.projection.MediaProjection
import com.sphereplatform.agent.ws.SphereWebSocketClientContract
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Production [StreamingManager] — coordinates encoder, VirtualDisplay and
 * WebSocket transport.
 *
 * Pipeline:
 * MediaProjection → VirtualDisplay → Surface → H264Encoder → FramePackager
 *   → SphereWebSocketClient → backend → viewer browser
 */
@Singleton
class StreamingManagerImpl @Inject constructor(
    @ApplicationContext private val context: Context,
    private val wsClient: SphereWebSocketClientContract,
    private val frameThrottle: FrameThrottle,
    private val qualityMonitor: StreamQualityMonitor,
) : StreamingManager {

    private var encoder: H264Encoder? = null
    private var adaptiveBitrate: AdaptiveBitrateController? = null
    private var virtualDisplayManager: VirtualDisplayManager? = null

    private var streamStartMs: Long = 0L

    @Volatile private var streaming = false

    // -------------------------------------------------------------------------
    // StreamingManager interface
    // -------------------------------------------------------------------------

    override fun start(projection: MediaProjection) {
        if (streaming) {
            Timber.d("StreamingManagerImpl: restart — stopping existing session")
            stopInternal()
        }

        streamStartMs = System.currentTimeMillis()

        val enc = H264Encoder(H264Encoder.EncoderConfig()) { nalData, metadata ->
            onFrameReady(nalData, metadata)
        }
        val abr = AdaptiveBitrateController(enc)
        adaptiveBitrate = abr

        // start() returns the Surface that VirtualDisplay will render into
        val encoderSurface = enc.start()
        encoder = enc

        val vdm = VirtualDisplayManager(context, projection)
        vdm.createDisplay(VirtualDisplayManager.DisplayConfig(), encoderSurface)
        virtualDisplayManager = vdm

        streaming = true
        Timber.i("StreamingManagerImpl: started")
    }

    override fun stop() = stopInternal()

    override fun isActive(): Boolean = streaming

    // -------------------------------------------------------------------------
    // Frame pipeline
    // -------------------------------------------------------------------------

    private fun onFrameReady(nalData: ByteArray, metadata: H264Encoder.FrameMetadata) {
        if (!streaming) return

        qualityMonitor.recordFrame(metadata.sizeBytes, metadata.isKeyFrame)

        val packed = FramePackager.pack(nalData, metadata, streamStartMs)
        val sent = wsClient.sendBinary(packed)

        if (!sent) {
            adaptiveBitrate?.onFrameDropDetected()
            if (metadata.isKeyFrame) {
                Timber.w("StreamingManagerImpl: I-frame send failed — WS queue may be full")
            }
        } else {
            adaptiveBitrate?.onSuccessfulDelivery()
        }
    }

    /**
     * Called when a new viewer connects — sends cached SPS/PPS and requests
     * an immediate keyframe so the viewer can start decoding without waiting
     * for the next I-frame interval.
     */
    fun onViewerConnected() {
        encoder?.requestKeyFrame()

        val enc = encoder ?: return
        val fakeMeta = H264Encoder.FrameMetadata(
            isKeyFrame = true,
            presentationTimeUs = 0L,
            sizeBytes = 0,
        )
        enc.cachedSps?.let { sps ->
            wsClient.sendBinary(FramePackager.pack(sps, fakeMeta.copy(sizeBytes = sps.size), streamStartMs))
        }
        enc.cachedPps?.let { pps ->
            wsClient.sendBinary(FramePackager.pack(pps, fakeMeta.copy(sizeBytes = pps.size), streamStartMs))
        }
    }

    fun getQualityStats(): StreamQualityMonitor.StreamStats =
        qualityMonitor.getStats()

    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    private fun stopInternal() {
        streaming = false
        try {
            encoder?.stop()
            virtualDisplayManager?.release()
        } catch (e: Exception) {
            Timber.e(e, "StreamingManagerImpl.stop() error")
        } finally {
            encoder = null
            virtualDisplayManager = null
            adaptiveBitrate = null
        }
        Timber.i("StreamingManagerImpl: stopped")
    }
}
