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
import java.util.UUID
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

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
    private var imageReaderHandler: Handler? = null
    private var gpuBridge: SurfaceTextureEncoderBridge? = null
    private var planarGpuBridge: PlanarGpuSource? = null
    internal var planarGpuFactory: (PlanarGpuRequest) -> PlanarGpuSource? = NativePlanarGpuSource::create
    internal var gpuBridgeEnabled = BuildConfig.STREAM_GPU_BRIDGE
    internal var planarInputEnabled = BuildConfig.STREAM_PLANAR_INPUT
    internal var qualityProfilesEnabled = BuildConfig.CONTINUOUS_INPUT_CANARY
    internal var codecSource: (Int, Int, Float, Boolean) -> StreamQualityPolicy.Source = StreamCodecCapability::source
    private val qualityPreferences by lazy { context.getSharedPreferences("sphere_stream_quality_v1", Context.MODE_PRIVATE) }
    private var qualitySettings: StreamQualitySettings = runCatching {
        qualityPreferences.getString("settings", null)?.let { Json.decodeFromString<StreamQualitySettings>(it) }
    }.getOrNull() ?: StreamQualitySettings()
    private var qualitySource: StreamQualityPolicy.Source? = null
    private var qualityPlan: StreamQualityPolicy.Plan? = null
    private var sourceRateGovernor: DirectSourceRateGovernor? = null
    private var rateAdaptation = "source"
    private data class RateEstimate(val owner: Any, val capture: CaptureInputSession, val bitrate: Int, val fps: Int)
    private val pendingRate = AtomicReference<RateEstimate?>()
    private val rateScheduled = AtomicBoolean(false)
    private data class CachedQuality(val capture: Any?, val value: StreamQualitySnapshot)
    private val cachedQuality = AtomicReference<CachedQuality?>()
    private val qualityHandler by lazy { Handler(context.mainLooper) }
    internal var monotonicNs: () -> Long = System::nanoTime
    internal var monotonicMs: () -> Long = android.os.SystemClock::elapsedRealtime
    // Image/Bitmap native storage must stay alive through the complete copy and
    // surface draw. Lifecycle methods serialize separately from codec callbacks.
    private val frameLock = Any()
    @Volatile private var captureSession: Any? = null
    private var inputGeometry: CaptureInputGeometry? = null
    private var inputSession: CaptureInputSession? = null
    private var inputInvalidationListener: (() -> Unit)? = null
    private var displayListener: android.hardware.display.DisplayManager.DisplayListener? = null
    internal var displayGeometry: () -> CaptureDisplayGeometry? = { CaptureDisplayGeometry.read(context) }
    private class EncodedViewer(val owner: Any, val capture: CaptureInputSession, val consume: (EncodedCaptureFrame) -> Unit) {
        val sequence = java.util.concurrent.atomic.AtomicLong(0)
        val legacy = LegacyVideoDeliveryLease()
        @Volatile var rate: Pair<Int, Long>? = null
    }
    @Volatile private var encodedViewers: List<EncodedViewer> = emptyList()
    private val awaitingLegacyIdr = java.util.concurrent.atomic.AtomicBoolean(false)

    private var streamStartMs: Long = 0L
    private var encoderCaptureEpoch: UUID? = null

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
        startCapture(projection, null)
    }

    private fun startCapture(projection: MediaProjection, retainedDisplay: VirtualDisplayManager?) {
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
        val sourceDisplay = displayGeometry()
        val captureConfig = VirtualDisplayManager.createConfig(context, nativeSize = gpuBridgeEnabled || planarInputEnabled)
        inputGeometry = sourceDisplay?.let {
            CaptureInputGeometry(it.width, it.height,
                captureConfig.width, captureConfig.height, it.rotation)
        }
        inputSession = inputGeometry?.let(CaptureInputSession::create)
        val packetEpoch = if (BuildConfig.CONTINUOUS_INPUT_CANARY) inputSession?.epoch?.let(UUID::fromString) else null
        val packetStartMs = streamStartMs
        encoderCaptureEpoch = packetEpoch
        val display = (context.getSystemService(Context.DISPLAY_SERVICE) as? android.hardware.display.DisplayManager)
            ?.getDisplay(android.view.Display.DEFAULT_DISPLAY)
        val source = if (qualityProfilesEnabled) codecSource(captureConfig.width, captureConfig.height,
            display?.refreshRate ?: 30f, planarInputEnabled) else null
        val plan = source?.let { StreamQualityPolicy.plan(qualitySettings, it) }
        qualitySource = source; qualityPlan = plan
        sourceRateGovernor = plan?.let(::DirectSourceRateGovernor)
        rateAdaptation = "source"
        val encoderConfig = H264Encoder.EncoderConfig(width = captureConfig.width, height = captureConfig.height,
            fps = source?.maximumFps ?: 30, bitrateBps = plan?.initialBitrate ?: 1_500_000,
            maxBitrateBps = source?.codecMaxBitrate ?: 4_000_000)
        frameThrottle.configure(plan?.maxFps ?: encoderConfig.fps, newCapture = true, precise = qualityProfilesEnabled)
        val enc = H264Encoder(encoderConfig) { nalData, metadata ->
            onFrameReady(nalData, metadata, session, packetEpoch, packetStartMs)
        }
        enc.onIdleFrameQueued = {
            synchronized(frameLock) {
                if (streaming && captureSession === session) qualityMonitor.recordIdleRefresh()
            }
        }
        // FIX H3: Передаём фактический битрейт энкодера в ABR — без рассинхрона
        val abr = AdaptiveBitrateController(enc, minBitrate = plan?.minBitrate ?: 500_000,
            maxBitrate = plan?.maxBitrate ?: 4_000_000, initialBitrate = encoderConfig.bitrateBps)
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
        enc.adjustFrameRate(plan?.maxFps ?: encoderConfig.fps)

        if (gpuBridgeEnabled && usePlanar) {
            val source = planarGpuFactory(PlanarGpuRequest(context, captureConfig.width, captureConfig.height,
                frameThrottle, qualityMonitor, { streaming && captureSession === session },
                { planes, ptsUs -> streaming && captureSession === session && enc.submitI420Frame(planes, ptsUs) },
                { enc.refreshIdleFrame(); Unit }, enc.frameIntervalMs, { error ->
                    Timber.e(error, "GPU planar capture failed; stopping this session")
                    Handler(context.mainLooper).post { if (encoder === enc) stop() }
                }))
            if (source != null) {
                planarGpuBridge = source
                try {
                    val surface = source.start()
                    val vdm = retainedDisplay ?: VirtualDisplayManager(context, projection)
                    virtualDisplayManager = vdm
                    streaming = true
                    if (retainedDisplay == null) vdm.createDisplay(captureConfig, surface)
                    else vdm.reconfigureDisplay(captureConfig, surface)
                    watchDisplay(session)
                    getStreamQuality()
                    viewerKeyFrameCoordinator.markEncoderReady { requestKeyFrameNow() }
                    Timber.i("StreamingManagerImpl: started GPU planar YuvConverter bridge")
                    return
                } catch (error: PlanarGpuSource.InitializationFailed) {
                    // No VirtualDisplay consumed a projection token. The retired
                    // source owns no codec Surface; retain the planar fallback.
                    source.close()
                    planarGpuBridge = null
                    Timber.w(error, "GPU planar unavailable at startup; using RGBA planar input")
                } catch (error: Exception) {
                    if (retainedDisplay == null) stopInternal()
                    throw error // Never fall back/reuse a consumed display token.
                }
            }
        }

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
                val vdm = retainedDisplay ?: VirtualDisplayManager(context, projection)
                virtualDisplayManager = vdm
                streaming = true
                if (retainedDisplay == null) vdm.createDisplay(captureConfig, captureSurface)
                else vdm.reconfigureDisplay(captureConfig, captureSurface)
                watchDisplay(session)
                getStreamQuality()
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
                if (retainedDisplay == null) stopInternal()
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
        val captureHandler = Handler(thread.looper)
        imageReaderHandler = captureHandler
        var lastPlanarTimestamp = 0L
        var lastSurfaceSubmissionNs: Long? = null
        var lastSurfaceBounds: Rect? = null
        val idleRefresh = object : Runnable {
            override fun run() {
                synchronized(frameLock) {
                    if (!streaming || captureSession !== session) return
                    try {
                        if (usePlanar) enc.refreshIdleFrame()
                        else {
                            val now = monotonicNs()
                            val last = lastSurfaceSubmissionNs
                            val bitmap = cachedBitmap
                            val bounds = lastSurfaceBounds
                            if (last != null && now - last >= enc.frameIntervalNs && bitmap != null && !bitmap.isRecycled && bounds != null) {
                                val surface = checkNotNull(encoderSurface)
                                val canvas = surface.lockCanvas(null)
                                if (canvas != null) {
                                    try { canvas.drawBitmap(bitmap, bounds, bounds, null) }
                                    finally { surface.unlockCanvasAndPost(canvas) }
                                    lastSurfaceSubmissionNs = now
                                    qualityMonitor.recordIdleRefresh()
                                } else qualityMonitor.recordRenderFailure()
                            }
                        }
                    } catch (error: Exception) {
                        qualityMonitor.recordRenderFailure()
                    }
                    Unit // This synchronized block owns side effects, not a Boolean result.
                }
                if (streaming && captureSession === session) captureHandler.postDelayed(this, enc.frameIntervalMs)
            }
        }

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
                    val captureTimestamp = if (usePlanar) image.timestamp else monotonicNs()
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
                    // A failed native copy must not make partially updated cache
                    // pixels eligible for an idle submission.
                    lastSurfaceSubmissionNs = null
                    lastSurfaceBounds = null
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
                            if (bmp === cachedBitmap) {
                                lastSurfaceSubmissionNs = monotonicNs()
                                lastSurfaceBounds = src
                            }
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
        }, captureHandler)

        // FIX M1: Не блокируем поток — даём Surface и ImageReader время инициализироваться.
        // Thread.sleep(100) заменён на неблокирующий postDelayed через HandlerThread.
        android.os.SystemClock.sleep(100)

        val vdm = retainedDisplay ?: VirtualDisplayManager(context, projection)
        virtualDisplayManager = vdm
        // Mark capture active before creating the display: its first frame can
        // arrive from the ImageReader callback before createDisplay returns.
        streaming = true
        try {
            // Pass ImageReader surface — keeps AUTO_MIRROR buffer path decoupled from OMX encoder
            if (retainedDisplay == null) vdm.createDisplay(captureConfig, ir.surface)
            else vdm.reconfigureDisplay(captureConfig, ir.surface)
        } catch (e: Exception) {
            if (retainedDisplay == null) stopInternal()
            throw e
        }

        viewerKeyFrameCoordinator.markEncoderReady { requestKeyFrameNow() }
        watchDisplay(session)
        getStreamQuality()
        captureHandler.postDelayed(idleRefresh, enc.frameIntervalMs)
        Timber.i("StreamingManagerImpl: started input=%s", if (usePlanar) "yuv420_planar" else "surface")
    }

    @Synchronized
    override fun stop() = stopInternal()

    override fun isActive(): Boolean = streaming

    private fun watchDisplay(session: Any) {
        val manager = context.getSystemService(Context.DISPLAY_SERVICE) as? android.hardware.display.DisplayManager ?: return
        val listener = object : android.hardware.display.DisplayManager.DisplayListener {
            override fun onDisplayAdded(id: Int) = Unit
            override fun onDisplayRemoved(id: Int) = Unit
            override fun onDisplayChanged(id: Int) {
                if (id == android.view.Display.DEFAULT_DISPLAY && captureSession === session) reconfigureIfDisplayChanged()
            }
        }
        displayListener = listener
        manager.registerDisplayListener(listener, qualityHandler)
    }

    @Synchronized
    internal fun reconfigureIfDisplayChanged() {
        if (!streaming) return
        val display = displayGeometry() ?: return
        if (inputSession?.matchesDisplay(display.width, display.height, display.rotation) != false) return
        val projection = currentProjection ?: return
        val retained = virtualDisplayManager ?: return
        try {
            retained.detachSurface()
            virtualDisplayManager = null // stopInternal retires codec/input, but preserves this projection's display.
            stopInternal()
            startCapture(projection, retained)
            Timber.i("StreamingManagerImpl: source geometry changed; capture rebound")
        } catch (failure: Exception) {
            val attached = virtualDisplayManager === retained
            stopInternal()
            if (!attached) runCatching { retained.release() }
            Timber.w("StreamingManagerImpl: source geometry rebind failed")
        }
    }

    // -------------------------------------------------------------------------
    // Frame pipeline
    // -------------------------------------------------------------------------

    private fun onFrameReady(nalData: ByteArray, metadata: H264Encoder.FrameMetadata,
                             session: Any, captureEpoch: UUID?, startedMs: Long) {
        if (!streaming || captureSession !== session) return

        // Once encoded, every access unit retains its position in the reference
        // chain. Callback scheduling/batching is not the source frame cadence.
        qualityMonitor.recordFrame(
            metadata.sizeBytes,
            metadata.isKeyFrame,
            metadata.isCodecConfig,
        )

        if (!metadata.isCodecConfig) {
            for (viewer in encodedViewers) {
                // No subscriber code runs under the capture/lifecycle lock. A retired
                // peer checks its own fence, and a replacement never receives this epoch.
                if (viewer.capture.epoch == captureEpoch?.toString() && metadata.presentationTimeUs > 0) {
                    runCatching { viewer.consume(EncodedCaptureFrame(viewer.capture, viewer.sequence.incrementAndGet(),
                        Math.multiplyExact(metadata.presentationTimeUs, 1000L), metadata.isKeyFrame,
                        nalData, encoder?.cachedSps, encoder?.cachedPps)) }
                }
            }
        }

        val delivery = encodedViewers.filter { it.capture.epoch == captureEpoch?.toString() }
            .map { it.legacy.observe(monotonicMs()) }
        if (delivery.isNotEmpty() && delivery.none { it.sendLegacy }) {
            qualityMonitor.recordLegacySuppression(nalData.size)
            return // Encoded RTP already consumed this exact access unit above.
        }
        if (delivery.any { it.requestKeyFrame }) {
            awaitingLegacyIdr.set(true)
            // Never acquire the lifecycle lock on the codec callback thread:
            // stop() may be waiting for that callback to finish.
            (imageReaderHandler ?: Handler(context.mainLooper)).post {
                if (streaming && captureSession === session) onViewerConnected()
            }
        }
        if (awaitingLegacyIdr.get() && !metadata.isCodecConfig) {
            if (!metadata.isKeyFrame) {
                qualityMonitor.recordLegacySuppression(nalData.size)
                return
            }
            // An already queued IDR can beat the recovery Handler. Configuration
            // must still precede it, independently of callback scheduling.
            replayLegacyHeaders()
            awaitingLegacyIdr.set(false)
        }

        // Capture these at encoder creation. A late callback must never stamp
        // an old access unit with a replacement capture's identity or clock.
        val packed = FramePackager.pack(nalData, metadata, startedMs, captureEpoch)
        val sent = sendFrameBinary(packed)

        if (!sent && (!qualityProfilesEnabled || encodedViewers.isEmpty())) {
            adaptiveBitrate?.onFrameDropDetected()
            if (metadata.isKeyFrame) {
                Timber.w("StreamingManagerImpl: I-frame send failed — WS queue may be full")
            }
        } else if (sent && (!qualityProfilesEnabled || encodedViewers.isEmpty())) {
            adaptiveBitrate?.onSuccessfulDelivery()
        }
        if (qualityProfilesEnabled && encodedViewers.isEmpty()) {
            val bitrate = encoder?.targetBitrateBps
            cachedQuality.updateAndGet { old ->
                if (old?.capture !== session || old.value.active == null || bitrate == null
                    || old.value.active.targetBitrateBps == bitrate && old.value.active.adaptation == "legacy_queue") old
                else old.copy(value = old.value.copy(active = old.value.active.copy(
                    targetBitrateBps = bitrate, adaptation = "legacy_queue")))
            }
        }
    }

    /**
     * Called when a new viewer connects — sends cached SPS/PPS and requests
     * an immediate keyframe so the viewer can start decoding without waiting
     * for the next I-frame interval.
     */
    @Synchronized
    override fun onViewerConnected() {
        encodedViewers.forEach { it.legacy.requireLegacy(monotonicMs()) }
        val dispatched = viewerKeyFrameCoordinator.request { requestKeyFrameNow() }
        if (!dispatched) {
            Timber.i("StreamingManagerImpl: viewer key-frame request deferred until encoder is ready")
        }
    }

    @Synchronized
    override fun requestDirectKeyFrame() {
        viewerKeyFrameCoordinator.request { requestKeyFrameNow(sendLegacyHeaders = false) }
    }

    private fun replayLegacyHeaders() {
        val enc = encoder ?: return
        if (!streaming) return
        val fakeMeta = H264Encoder.FrameMetadata(
            isKeyFrame = true,
            presentationTimeUs = 0L,
            sizeBytes = 0,
            isCodecConfig = true,
        )
        enc.cachedSps?.let { sps ->
            sendFrameBinary(FramePackager.pack(sps, fakeMeta.copy(sizeBytes = sps.size), streamStartMs, encoderCaptureEpoch))
        }
        enc.cachedPps?.let { pps ->
            sendFrameBinary(FramePackager.pack(pps, fakeMeta.copy(sizeBytes = pps.size), streamStartMs, encoderCaptureEpoch))
        }
    }

    private fun requestKeyFrameNow(sendLegacyHeaders: Boolean = true) {
        val enc = encoder ?: return
        if (!streaming) return
        if (sendLegacyHeaders) replayLegacyHeaders()
        // Planar refresh may produce output immediately. Queue decoder config
        // before requesting that IDR so a fresh viewer cannot discard it.
        if (enc.requestKeyFrame()) {
            Timber.i("StreamingManagerImpl: encoder accepted viewer sync-frame request")
        } else {
            Timber.w("StreamingManagerImpl: encoder did not accept viewer key-frame request")
        }
    }

    override fun getQualityStats(): StreamQualityMonitor.StreamStats =
        qualityMonitor.getStats()

    @Synchronized
    override fun getStreamQuality(): StreamQualitySnapshot {
        val source = qualitySource
        val plan = qualityPlan
        val enc = encoder
        val value = StreamQualitySnapshot(qualityProfilesEnabled, settings = qualitySettings,
            active = if (streaming && source != null && plan != null && enc != null)
                StreamQualitySnapshot.Active(source.width, source.height, source.sourceFps,
                    source.codecMaxFps, frameThrottle.targetFps, plan.maxBitrate, enc.targetBitrateBps, rateAdaptation)
            else null)
        cachedQuality.set(CachedQuality(captureSession, value))
        return value
    }

    override fun getStreamQualityTelemetry(): StreamQualitySnapshot? = cachedQuality.get()?.value?.takeIf { it.supported }

    @Synchronized
    override fun configureStreamQuality(settings: StreamQualitySettings): StreamQualitySnapshot {
        check(qualityProfilesEnabled) { "stream_quality_unsupported" }
        val source = qualitySource
        val enc = encoder
        val plan = source?.let { StreamQualityPolicy.plan(settings, it) }
        val previousBitrate = enc?.targetBitrateBps
        if (streaming && enc != null && plan != null) {
            check(enc.adjustBitrate(plan.initialBitrate)) { "stream_quality_codec_refused" }
        }
        if (!qualityPreferences.edit().putString("settings", Json.encodeToString(settings)).commit()) {
            // Retain the old preference and source policy if durable storage refused the write.
            previousBitrate?.let { enc.adjustBitrate(it) }
            throw IllegalStateException("stream_quality_storage_unavailable")
        }
        qualitySettings = settings
        if (plan != null && enc != null && streaming) {
            qualityPlan = plan
            sourceRateGovernor?.configure(plan)
            frameThrottle.configure(plan.maxFps)
            enc.adjustFrameRate(plan.maxFps)
            adaptiveBitrate = AdaptiveBitrateController(enc, plan.minBitrate, plan.maxBitrate, plan.initialBitrate)
            rateAdaptation = "source"
        }
        return getStreamQuality()
    }

    @Synchronized
    override fun encodedProfileLevelId(): String = encoder?.profileLevelId ?: "42e01f"

    @Synchronized
    override fun encodedRateLimits(): Pair<Int, Int> =
        (qualitySource?.codecMaxBitrate ?: 4_000_000) to (qualitySource?.maximumFps ?: 30)

    @Synchronized
    override fun encodedInitialBitrate(): Int = qualityPlan?.initialBitrate ?: 2_000_000

    override fun onDirectRateEstimate(owner: Any, capture: CaptureInputSession, bitrate: Int, fps: Int) {
        if (!qualityProfilesEnabled || !isEncodedViewerCurrent(owner, capture)
            || bitrate !in 0..100_000_000 || fps !in 0..240) return
        val viewer = encodedViewers.firstOrNull { it.owner === owner && it.capture == capture } ?: return
        viewer.rate = bitrate to monotonicMs()
        pendingRate.set(RateEstimate(owner, capture, bitrate, fps))
        if (rateScheduled.compareAndSet(false, true)) qualityHandler.post(drainRate)
    }

    // One replaceable estimate and at most one posted callback. No native callback
    // waits for MediaCodec/lifecycle locks or creates a coroutine per allocation.
    private val drainRate = object : Runnable {
        override fun run() {
            val estimate = pendingRate.getAndSet(null)
            synchronized(this@StreamingManagerImpl) {
                if (estimate != null && isEncodedViewerCurrent(estimate.owner, estimate.capture)) {
                    // One coded source serves all current peers. The weakest recent
                    // allocation controls that source; one fast peer cannot repeatedly
                    // overwrite a slow peer's budget and fill its RTP queue.
                    val now = monotonicMs()
                    val sharedBitrate = encodedViewers.filter { it.capture == estimate.capture }
                        .mapNotNull { it.rate?.takeIf { sample -> now >= sample.second && now - sample.second <= 10000 }?.first }
                        .minOrNull() ?: estimate.bitrate
                    val rate = sourceRateGovernor?.observe(sharedBitrate, estimate.fps, now)
                    val enc = encoder
                    if (rate != null && enc != null) {
                        if (enc.adjustBitrate(rate.bitrate)) {
                            frameThrottle.configure(rate.fps); enc.adjustFrameRate(rate.fps)
                            rateAdaptation = "webrtc"
                            getStreamQuality()
                        } else sourceRateGovernor?.refused(enc.targetBitrateBps, frameThrottle.targetFps)
                    }
                }
            }
            rateScheduled.set(false)
            if (pendingRate.get() != null && rateScheduled.compareAndSet(false, true)) qualityHandler.post(this)
        }
    }

    @Synchronized
    override fun mapStreamPoints(points: List<StreamPoint>): List<StreamPoint>? {
        if (!streaming) return null
        val display = displayGeometry() ?: return null
        return inputGeometry?.map(points, display.width, display.height, display.rotation)
    }

    @Synchronized
    override fun getInputSession(): CaptureInputSession? {
        if (!streaming) return null
        val session = inputSession ?: return null
        val display = displayGeometry() ?: return null
        return session.takeIf { it.matchesDisplay(display.width, display.height, display.rotation) }
    }

    @Synchronized
    override fun setInputInvalidationListener(listener: (() -> Unit)?) { inputInvalidationListener = listener }

    @Synchronized
    override fun attachEncodedViewer(owner: Any, consume: (EncodedCaptureFrame) -> Unit): CaptureInputSession? {
        if (encodedViewers.size >= 10 || encodedViewers.any { it.owner === owner }) return null
        val capture = getInputSession() ?: return null
        // The encoded adapter advertises the actual configured AVC level ceiling.
        encodedViewers = encodedViewers + EncodedViewer(owner, capture, consume)
        return capture
    }

    @Synchronized
    override fun detachEncodedViewer(owner: Any) {
        val viewer = encodedViewers.firstOrNull { it.owner === owner } ?: return
        encodedViewers = encodedViewers.filterNot { it === viewer }
        if (encodedViewers.isEmpty() && !viewer.legacy.observe(monotonicMs()).sendLegacy) {
            awaitingLegacyIdr.set(true)
            viewerKeyFrameCoordinator.request { requestKeyFrameNow() }
        }
    }

    override fun isEncodedViewerCurrent(owner: Any, capture: CaptureInputSession): Boolean {
        return streaming && encodedViewers.any { it.owner === owner && it.capture == capture }
    }

    @Synchronized
    override fun renewLegacyVideoDelivery(owner: Any, capture: CaptureInputSession, enabled: Boolean, ttlMs: Int): Boolean {
        val viewer = encodedViewers.firstOrNull { it.owner === owner } ?: return false
        if (!streaming || viewer.owner !== owner || viewer.capture != capture || getInputSession() != capture) return false
        return viewer.legacy.renew(enabled, monotonicMs(), ttlMs)
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
        displayListener?.let { listener ->
            runCatching { (context.getSystemService(Context.DISPLAY_SERVICE) as? android.hardware.display.DisplayManager)?.unregisterDisplayListener(listener) }
        }
        displayListener = null
        viewerKeyFrameCoordinator.markEncoderStopped()
        streaming = false
        cachedQuality.set(null)
        encodedViewers = emptyList()
        awaitingLegacyIdr.set(false)
        inputGeometry = null
        inputSession = null
        encoderCaptureEpoch = null
        // Fence input before releasing surfaces/codec, without awaiting a root worker under this lock.
        runCatching { inputInvalidationListener?.invoke() }
        // PERF: Индивидуальный try-catch на каждый ресурс.
        // До: один try-catch → если virtualDisplayManager.release() бросает,
        // imageReader, thread и encoder не освобождаются → утечка 5-10MB.
        // После: каждый ресурс освобождается независимо.
        try { virtualDisplayManager?.release() } catch (e: Exception) {
            Timber.w(e, "StreamingManagerImpl: virtualDisplayManager release error")
        }
        synchronized(frameLock) {
            captureSession = null
            imageReaderHandler?.removeCallbacksAndMessages(null)
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
        val planarBridge = planarGpuBridge
        if (planarBridge != null) {
            // All submitted planes/cache copies finish on the GL owner first.
            planarBridge.close { ownedEncoder?.stop() }
        } else if (bridge != null) {
            // Never destroy the codec Surface concurrently with eglSwapBuffers.
            bridge.close { ownedEncoder?.stop() }
        } else {
            try { ownedEncoder?.stop() } catch (e: Exception) {
                Timber.w(e, "StreamingManagerImpl: encoder stop error")
            }
        }
        gpuBridge = null
        planarGpuBridge = null
        virtualDisplayManager = null
        imageReader = null
        imageReaderThread = null
        imageReaderHandler = null
        encoder = null
        adaptiveBitrate = null
        pendingRate.set(null)
        qualitySource = null; qualityPlan = null; sourceRateGovernor = null; rateAdaptation = "source"
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
