package com.sphereplatform.agent.streaming

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.graphics.Rect
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
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
    private var imageReader: ImageReader? = null
    private var imageReaderThread: HandlerThread? = null

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

        val captureConfig = VirtualDisplayManager.createConfig(context)
        val enc = H264Encoder(H264Encoder.EncoderConfig(
            width = captureConfig.width,
            height = captureConfig.height
        )) { nalData, metadata ->
            onFrameReady(nalData, metadata)
        }
        val abr = AdaptiveBitrateController(enc)
        adaptiveBitrate = abr

        // start() returns the Surface that VirtualDisplay will render into
        val encoderSurface = enc.start()
        encoder = enc

        // ImageReader sits between VirtualDisplay (AUTO_MIRROR) and the H264 encoder surface.
        // This avoids the GraphicBufferSource acquireBuffer err=-38 crash on LDPlayer x86:
        // VirtualDisplay → ImageReader (CPU-accessible) → lockCanvas → encoderSurface
        val ir = ImageReader.newInstance(
            captureConfig.width, captureConfig.height,
            PixelFormat.RGBA_8888, 2,
        )
        imageReader = ir

        val thread = HandlerThread("sphere-imagereader").also { it.start() }
        imageReaderThread = thread

        ir.setOnImageAvailableListener({ reader ->
            val image = try {
                reader.acquireLatestImage()
            } catch (e: Exception) {
                null
            }
            if (image == null) return@setOnImageAvailableListener
            
            try {
                val plane = image.planes[0]
                val rowStride = plane.rowStride
                val pixelStride = plane.pixelStride          // 4 for RGBA_8888
                val strideWidth = rowStride / pixelStride
                val bmp = Bitmap.createBitmap(strideWidth, image.height, Bitmap.Config.ARGB_8888)
                bmp.copyPixelsFromBuffer(plane.buffer)
                
                // Only lock and draw if we are still streaming
                if (streaming) {
                    val canvas = encoderSurface.lockCanvas(null)
                    if (canvas != null) {
                        val src = Rect(0, 0, image.width, image.height)
                        val dst = Rect(0, 0, image.width, image.height)
                        canvas.drawBitmap(bmp, src, dst, null)
                        encoderSurface.unlockCanvasAndPost(canvas)
                    }
                }
                bmp.recycle()
            } catch (e: Exception) {
                Timber.e(e, "StreamingManagerImpl: frame render error")
            } finally {
                try {
                    image.close()
                } catch (e: Exception) {
                    // Ignore close errors
                }
            }
        }, Handler(thread.looper))

        // Give the Surface and ImageReader time to initialise before VirtualDisplay starts pushing
        Thread.sleep(100)

        val vdm = VirtualDisplayManager(context, projection)
        // Pass ImageReader surface — keeps AUTO_MIRROR buffer path decoupled from OMX encoder
        vdm.createDisplay(captureConfig, ir.surface)
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
            virtualDisplayManager?.release()
            imageReader?.close()
            imageReaderThread?.quitSafely()
            encoder?.stop()
        } catch (e: Exception) {
            Timber.e(e, "StreamingManagerImpl.stop() error")
        } finally {
            virtualDisplayManager = null
            imageReader = null
            imageReaderThread = null
            encoder = null
            adaptiveBitrate = null
        }
        Timber.i("StreamingManagerImpl: stopped")
    }
}
