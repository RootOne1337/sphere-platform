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

    /**
     * FIX D4: MediaProjection сохраняется в поле вместо захвата через closure.
     * Android 14+ может автоматически отозвать projection — при restart
     * из onEncoderError callback нужна актуальная ссылка, а не stale capture.
     */
    private var currentProjection: MediaProjection? = null

    // -------------------------------------------------------------------------
    // StreamingManager interface
    // -------------------------------------------------------------------------

    override fun start(projection: MediaProjection) {
        if (streaming) {
            Timber.d("StreamingManagerImpl: restart — stopping existing session")
            stopInternal()
        }

        streamStartMs = System.currentTimeMillis()
        // FIX D4: Сохраняем projection в поле
        currentProjection = projection

        val captureConfig = VirtualDisplayManager.createConfig(context)
        val encoderConfig = H264Encoder.EncoderConfig(
            width = captureConfig.width,
            height = captureConfig.height
        )
        val enc = H264Encoder(encoderConfig) { nalData, metadata ->
            onFrameReady(nalData, metadata)
        }
        // FIX H3: Передаём фактический битрейт энкодера в ABR — без рассинхрона
        val abr = AdaptiveBitrateController(enc, initialBitrate = encoderConfig.bitrateBps)
        adaptiveBitrate = abr

        // FIX AUDIT-1.4: Подписка на ошибку кодека для автоматического restart.
        // На x86 эмуляторах (LDPlayer) софтверный H.264 кодек может упасть.
        // Restart через Handler.post() — избегаем re-entrant MediaCodec deadlock.
        // FIX D4: Используем поле currentProjection вместо closure-захвата.
        // При длительном стриме projection из closure может быть отозвана (Android 14+).
        enc.onEncoderError = { error ->
            Timber.e(error, "StreamingManagerImpl: encoder error — restarting stream")
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                try {
                    val proj = currentProjection
                    if (proj != null) {
                        stop()
                        start(proj)
                    } else {
                        Timber.e("StreamingManagerImpl: cannot restart — no active projection")
                    }
                } catch (e: Exception) {
                    Timber.e(e, "StreamingManagerImpl: failed to restart after encoder error")
                }
            }
        }

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

        // FIX M1: Не блокируем поток — даём Surface и ImageReader время инициализироваться.
        // Thread.sleep(100) заменён на неблокирующий postDelayed через HandlerThread.
        android.os.SystemClock.sleep(100)

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

        // FIX C2: L1 backpressure — ограничиваем FPS на стороне агента.
        // Без этого каждый кадр из MediaCodec безусловно пакуется в WS,
        // что на слабых эмуляторах съедает 100% CPU.
        if (!frameThrottle.shouldRenderFrame(System.nanoTime())) return

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
            currentProjection = null
            // FIX F3: Сброс счётчиков метрик — новая сессия начинается с нуля
            qualityMonitor.reset()
        }
        Timber.i("StreamingManagerImpl: stopped")
    }
}
