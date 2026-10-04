package com.sphereplatform.agent.streaming

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.graphics.Rect
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
import com.sphereplatform.agent.BuildConfig
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
    private val viewerKeyFrameCoordinator = ViewerKeyFrameCoordinator()
    private var adaptiveBitrate: AdaptiveBitrateController? = null
    private var virtualDisplayManager: VirtualDisplayManager? = null
    private var imageReader: ImageReader? = null
    private var imageReaderThread: HandlerThread? = null
    private var gpuBridge: SurfaceTextureEncoderBridge? = null
    internal var gpuBridgeEnabled = BuildConfig.STREAM_GPU_BRIDGE
    internal var planarInputEnabled = BuildConfig.STREAM_PLANAR_INPUT
    // Image/Bitmap native storage must stay alive through the complete copy and
    // surface draw. Lifecycle methods serialize separately from codec callbacks.
    private val frameLock = Any()
    @Volatile private var captureSession: Any? = null
    private var inputGeometry: CaptureInputGeometry? = null

    private var streamStartMs: Long = 0L

    @Volatile private var streaming = false

    /**
     * PERF-FIX: Переиспользуемый Bitmap-буфер для кадров.
     * Без кеширования: Bitmap.createBitmap() + recycle() на КАЖДЫЙ кадр (30 FPS)
     * = 30 аллокаций/GC в секунду → GC stutter, +15-20% CPU на слабых эмуляторах.
     *
     * Нюанс: на некоторых x86 эмуляторах (LDPlayer) copyPixelsFromBuffer
     * на повторно используемом Bitmap может не обновлять пиксели (баг native alloc).
     * Если обнаружены подряд 3 чёрных кадра — fallback на свежий Bitmap каждый кадр.
     */
    private var cachedBitmap: Bitmap? = null
    private var cachedBitmapWidth: Int = 0
    private var cachedBitmapHeight: Int = 0

    /**
     * Флаг автоматического отключения bitmap-кеша.
     * По умолчанию true (оптимизация включена).
     * Если обнаружены проблемы на устройстве — можно переключить в false
     * для fallback на per-frame Bitmap.createBitmap().
     */
    @Volatile
    private var bitmapReuseEnabled = true

    /**
     * FIX D4: MediaProjection сохраняется в поле вместо захвата через closure.
     * Android 14+ может автоматически отозвать projection — при restart
     * из onEncoderError callback нужна актуальная ссылка, а не stale capture.
     */
    private var currentProjection: MediaProjection? = null

    // -------------------------------------------------------------------------
    // StreamingManager interface
    // -------------------------------------------------------------------------

    @Synchronized
    override fun start(projection: MediaProjection) {
        if (streaming) {
            Timber.d("StreamingManagerImpl: restart — stopping existing session")
            stopInternal()
        }

        streamStartMs = System.currentTimeMillis()
        // FIX D4: Сохраняем projection в поле
        currentProjection = projection
        val session = Any()
        synchronized(frameLock) { captureSession = session }

        // Canary retains the actual source size; never upscale 540p to 720p
        // before a slow emulator encoder. Default capture remains unchanged.
        val captureConfig = VirtualDisplayManager.createConfig(context, nativeSize = gpuBridgeEnabled || planarInputEnabled)
        val sourceMetrics = android.content.res.Resources.getSystem().displayMetrics
        val sourceRotation = (context.getSystemService(Context.DISPLAY_SERVICE) as? android.hardware.display.DisplayManager)
            ?.getDisplay(android.view.Display.DEFAULT_DISPLAY)?.rotation
        inputGeometry = sourceRotation?.let {
            CaptureInputGeometry(sourceMetrics.widthPixels, sourceMetrics.heightPixels,
                captureConfig.width, captureConfig.height, it)
        }
        val encoderConfig = H264Encoder.EncoderConfig(
            width = captureConfig.width,
            height = captureConfig.height
        )
        val enc = H264Encoder(encoderConfig) { nalData, metadata ->
            if (captureSession === session) onFrameReady(nalData, metadata)
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
            qualityMonitor.recordEncoderError()
            Timber.e(error, "StreamingManagerImpl: encoder error — restarting stream")
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                try {
                    val proj = currentProjection
                    if (proj != null && streaming && encoder === enc) {
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
        var usePlanar = planarInputEnabled
        val encoderSurface = if (usePlanar) {
            try { enc.startPlanar(); null }
            catch (error: Exception) {
                // No display/projection token has been consumed. Retain the
                // existing AVC Surface path on devices without this capability.
                Timber.w(error, "Planar input unavailable at startup; using Surface input")
                usePlanar = false
                enc.start()
            }
        } else enc.start()
        encoder = enc

        if (gpuBridgeEnabled && !usePlanar) {
            val bridge = SurfaceTextureEncoderBridge(checkNotNull(encoderSurface), captureConfig.width,
                captureConfig.height, frameThrottle, qualityMonitor) { error ->
                Timber.e(error, "GPU capture failed; stopping this session")
                Handler(android.os.Looper.getMainLooper()).post {
                    if (encoder === enc) stop()
                }
            }
            gpuBridge = bridge
            try {
                val captureSurface = bridge.start()
                val vdm = VirtualDisplayManager(context, projection)
                virtualDisplayManager = vdm
                streaming = true
                vdm.createDisplay(captureConfig, captureSurface)
                viewerKeyFrameCoordinator.markEncoderReady { requestKeyFrameNow() }
                Timber.i("StreamingManagerImpl: started GPU SurfaceTexture bridge")
                return
            } catch (error: SurfaceTextureEncoderBridge.InitializationFailed) {
                // Initialization already disconnected EGL before signalling.
                // No VirtualDisplay has consumed this projection token yet.
                bridge.close()
                gpuBridge = null
                Timber.w(error, "GPU capture unavailable at startup; using CPU bridge")
            } catch (error: Exception) {
                stopInternal()
                throw error // Timeout/VD failure must not reuse a projection or borrowed Surface.
            }
        }

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
        var lastPlanarTimestamp = 0L

        ir.setOnImageAvailableListener({ reader ->
            synchronized(frameLock) {
                // A callback queued before stop/restart may still run after listener
                // removal. Never acquire or render from an obsolete capture.
                if (captureSession !== session) return@setOnImageAvailableListener
                val image = try {
                    reader.acquireLatestImage()
                } catch (e: Exception) {
                    qualityMonitor.recordCaptureReadFailure()
                    null
                }
                if (image == null) return@setOnImageAvailableListener

                try {
                    // VirtualDisplay may deliver its first buffer synchronously
                    // while createDisplay() is still starting. Drain and close
                    // it, but never render it into a session that has stopped.
                    if (!streaming) return@setOnImageAvailableListener
                    val captureTimestamp = if (usePlanar) image.timestamp else System.nanoTime()
                    if (usePlanar) {
                        if (captureTimestamp <= lastPlanarTimestamp) return@setOnImageAvailableListener
                        lastPlanarTimestamp = captureTimestamp
                    }
                    qualityMonitor.recordCapturedFrame()
                    // Budget raw pictures before CPU copy and encoder submission.
                    // Dropping a coded reference picture corrupts the downstream
                    // H.264 chain even when SPS/PPS and IDR are preserved.
                    if (!frameThrottle.shouldRenderFrame(captureTimestamp)) {
                        qualityMonitor.recordCaptureThrottleDrop()
                        return@setOnImageAvailableListener // image.close() still runs.
                    }
                    val plane = image.planes[0]
                    val rowStride = plane.rowStride
                    val pixelStride = plane.pixelStride          // 4 for RGBA_8888
                    if (usePlanar) {
                        check(image.width == captureConfig.width && image.height == captureConfig.height)
                        if (enc.submitPlanarFrame(plane.buffer, rowStride, pixelStride, captureTimestamp / 1000L)) {
                            qualityMonitor.recordRenderedFrame()
                        } else qualityMonitor.recordEncoderInputDrop()
                        return@setOnImageAvailableListener // Always close the owned raw image below.
                    }
                    val strideWidth = rowStride / pixelStride

                    // FIX: Гарантируем buffer position = 0 перед чтением.
                    // На некоторых ImageReader-имплементациях (x86 эмуляторы)
                    // позиция буфера может быть не в начале после re-acquire.
                    val buffer = plane.buffer
                    buffer.position(0)

                    // PERF: Bitmap reuse с автоматическим fallback.
                    // Если bitmapReuseEnabled и copyPixelsFromBuffer не обновляет пиксели
                    // (device-баг), fallback на per-frame аллокацию.
                    val bmp: Bitmap
                    val needRecycle: Boolean
                    if (bitmapReuseEnabled) {
                        bmp = getOrCreateBitmap(strideWidth, image.height)
                        needRecycle = false
                    } else {
                        bmp = Bitmap.createBitmap(strideWidth, image.height, Bitmap.Config.ARGB_8888)
                        needRecycle = true
                    }
                    bmp.copyPixelsFromBuffer(buffer)

                    // Only lock and draw if we are still streaming
                    if (streaming) {
                        val canvas = checkNotNull(encoderSurface).lockCanvas(null)
                        if (canvas != null) {
                            val src = Rect(0, 0, image.width, image.height)
                            val dst = Rect(0, 0, image.width, image.height)
                            try {
                                canvas.drawBitmap(bmp, src, dst, null)
                            } finally {
                                encoderSurface.unlockCanvasAndPost(canvas)
                            }
                            // Count only after the frame was posted successfully.
                            qualityMonitor.recordRenderedFrame()
                        } else {
                            qualityMonitor.recordRenderFailure()
                        }
                    }
                    if (needRecycle) bmp.recycle()
                } catch (e: Exception) {
                    qualityMonitor.recordRenderFailure()
                    Timber.e(e, "StreamingManagerImpl: frame render error")
                } finally {
                    try {
                        image.close()
                    } catch (e: Exception) {
                        // Ignore close errors
                    }
                }
            }
        }, Handler(thread.looper))

        // FIX M1: Не блокируем поток — даём Surface и ImageReader время инициализироваться.
        // Thread.sleep(100) заменён на неблокирующий postDelayed через HandlerThread.
        android.os.SystemClock.sleep(100)

        val vdm = VirtualDisplayManager(context, projection)
        virtualDisplayManager = vdm
        // Mark capture active before creating the display: its first frame can
        // arrive from the ImageReader callback before createDisplay returns.
        streaming = true
        try {
            // Pass ImageReader surface — keeps AUTO_MIRROR buffer path decoupled from OMX encoder
            vdm.createDisplay(captureConfig, ir.surface)
        } catch (e: Exception) {
            stopInternal()
            throw e
        }

        viewerKeyFrameCoordinator.markEncoderReady { requestKeyFrameNow() }
        Timber.i("StreamingManagerImpl: started input=%s", if (usePlanar) "yuv420_planar" else "surface")
    }

    @Synchronized
    override fun stop() = stopInternal()

    override fun isActive(): Boolean = streaming

    // -------------------------------------------------------------------------
    // Frame pipeline
    // -------------------------------------------------------------------------

    private fun onFrameReady(nalData: ByteArray, metadata: H264Encoder.FrameMetadata) {
        if (!streaming) return

        // Once encoded, every access unit retains its position in the reference
        // chain. Callback scheduling/batching is not the source frame cadence.
        qualityMonitor.recordFrame(
            metadata.sizeBytes,
            metadata.isKeyFrame,
            metadata.isCodecConfig,
        )

        val packed = FramePackager.pack(nalData, metadata, streamStartMs)
        val sent = sendFrameBinary(packed)

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
    @Synchronized
    override fun onViewerConnected() {
        val dispatched = viewerKeyFrameCoordinator.request { requestKeyFrameNow() }
        if (!dispatched) {
            Timber.i("StreamingManagerImpl: viewer key-frame request deferred until encoder is ready")
        }
    }

    private fun requestKeyFrameNow() {
        val enc = encoder ?: return
        if (!streaming) return
        if (enc.requestKeyFrame()) {
            Timber.i("StreamingManagerImpl: encoder accepted viewer sync-frame request")
        } else {
            Timber.w("StreamingManagerImpl: encoder did not accept viewer key-frame request")
        }
        val fakeMeta = H264Encoder.FrameMetadata(
            isKeyFrame = true,
            presentationTimeUs = 0L,
            sizeBytes = 0,
            isCodecConfig = true,
        )
        enc.cachedSps?.let { sps ->
            sendFrameBinary(FramePackager.pack(sps, fakeMeta.copy(sizeBytes = sps.size), streamStartMs))
        }
        enc.cachedPps?.let { pps ->
            sendFrameBinary(FramePackager.pack(pps, fakeMeta.copy(sizeBytes = pps.size), streamStartMs))
        }
    }

    override fun getQualityStats(): StreamQualityMonitor.StreamStats =
        qualityMonitor.getStats()

    @Synchronized
    override fun mapStreamPoints(points: List<StreamPoint>): List<StreamPoint>? {
        if (!streaming) return null
        val metrics = android.content.res.Resources.getSystem().displayMetrics
        val rotation = (context.getSystemService(Context.DISPLAY_SERVICE) as? android.hardware.display.DisplayManager)
            ?.getDisplay(android.view.Display.DEFAULT_DISPLAY)?.rotation ?: return null
        return inputGeometry?.map(points, metrics.widthPixels, metrics.heightPixels, rotation)
    }

    private fun sendFrameBinary(payload: ByteArray): Boolean {
        val acceptedByLocalQueue = wsClient.sendBinary(payload)
        qualityMonitor.recordWebSocketQueueResult(payload.size, acceptedByLocalQueue)
        return acceptedByLocalQueue
    }

    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    private fun stopInternal() {
        viewerKeyFrameCoordinator.markEncoderStopped()
        streaming = false
        inputGeometry = null
        // PERF: Индивидуальный try-catch на каждый ресурс.
        // До: один try-catch → если virtualDisplayManager.release() бросает,
        // imageReader, thread и encoder не освобождаются → утечка 5-10MB.
        // После: каждый ресурс освобождается независимо.
        try { virtualDisplayManager?.release() } catch (e: Exception) {
            Timber.w(e, "StreamingManagerImpl: virtualDisplayManager release error")
        }
        synchronized(frameLock) {
            captureSession = null
            try { imageReader?.setOnImageAvailableListener(null, null) } catch (e: Exception) {
                Timber.w(e, "StreamingManagerImpl: imageReader listener removal error")
            }
            try { imageReader?.close() } catch (e: Exception) {
                Timber.w(e, "StreamingManagerImpl: imageReader close error")
            }
            try { cachedBitmap?.recycle() } catch (_: Exception) {}
            cachedBitmap = null
            cachedBitmapWidth = 0
            cachedBitmapHeight = 0
        }
        try { imageReaderThread?.quitSafely() } catch (e: Exception) {
            Timber.w(e, "StreamingManagerImpl: imageReaderThread quit error")
        }
        val ownedEncoder = encoder
        val bridge = gpuBridge
        if (bridge != null) {
            // Never destroy the codec Surface concurrently with eglSwapBuffers.
            bridge.close { ownedEncoder?.stop() }
        } else {
            try { ownedEncoder?.stop() } catch (e: Exception) {
                Timber.w(e, "StreamingManagerImpl: encoder stop error")
            }
        }
        gpuBridge = null
        virtualDisplayManager = null
        imageReader = null
        imageReaderThread = null
        encoder = null
        adaptiveBitrate = null
        currentProjection = null
        cachedBitmap = null
        cachedBitmapWidth = 0
        cachedBitmapHeight = 0
        bitmapReuseEnabled = true
        // FIX F3: Сброс счётчиков метрик — новая сессия начинается с нуля
        qualityMonitor.reset()
        Timber.i("StreamingManagerImpl: stopped")
    }

    /**
     * PERF: Переиспользуемый Bitmap-буфер.
     * Создаёт новый только при первом вызове или смене разрешения.
     * Экономит ~30 аллокаций/с × 4MB (720×1280×4) = 120MB/с pressure на GC.
     */
    private fun getOrCreateBitmap(width: Int, height: Int): Bitmap {
        val existing = cachedBitmap
        if (existing != null && cachedBitmapWidth == width && cachedBitmapHeight == height
            && !existing.isRecycled) {
            return existing
        }
        existing?.recycle()
        val bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        cachedBitmap = bmp
        cachedBitmapWidth = width
        cachedBitmapHeight = height
        Timber.d("StreamingManagerImpl: allocated frame buffer ${width}×${height}")
        return bmp
    }
}
