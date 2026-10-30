package com.sphereplatform.agent.streaming

import android.graphics.SurfaceTexture
import android.graphics.Matrix
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.os.Handler
import android.os.HandlerThread
import android.view.Surface
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.nio.ByteBuffer
import kotlin.math.abs
import org.webrtc.EglBase
import org.webrtc.RendererCommon
import org.webrtc.TextureBufferImpl
import org.webrtc.VideoFrame
import org.webrtc.YuvConverter
import timber.log.Timber

internal object NativePlanarGpuSource {
    fun create(request: PlanarGpuRequest): PlanarGpuSource? = WebRtcGpuPlanarSource(request)
}

/** OES -> maintained WebRTC YUV shader/readback -> existing planar encoder.
 * One GL owner, one pending draw, synchronous borrowed planes; no frame FIFO.
 */
private class WebRtcGpuPlanarSource(private val request: PlanarGpuRequest) : PlanarGpuSource {
    private lateinit var thread: HandlerThread
    private lateinit var handler: Handler
    private val closed = AtomicBoolean(false)
    private val queued = AtomicBoolean(false)
    private val failed = AtomicBoolean(false)
    private val pump = GpuFramePump(request.throttle, request.quality)
    private var egl: EglBase? = null
    private var converter: YuvConverter? = null
    private var textureId = 0
    private var producer: SurfaceTexture? = null
    private var input: Surface? = null
    private val matrix = FloatArray(16)
    private var windowNs = 0L
    private var samples = 0L
    private var convertNs = 0L
    private var submitNs = 0L
    private val idle = object : Runnable {
        override fun run() {
            if (closed.get() || failed.get()) return
            try { if (request.valid()) request.refresh() }
            catch (error: Exception) { fail(error); return }
            if (!closed.get()) handler.postDelayed(this, request.refreshIntervalMs)
        }
    }

    override fun start(): Surface {
        check(!closed.get() && !::handler.isInitialized)
        require(request.width in 2..4096 && request.height in 2..4096)
        require(request.width % 2 == 0 && request.height % 2 == 0 && request.refreshIntervalMs >= 1)
        thread = HandlerThread("sphere-capture-yuv").also { it.start() }
        handler = Handler(thread.looper)
        val ready = CountDownLatch(1)
        var failure: Throwable? = null
        check(handler.post {
            try { if (!closed.get()) initialize() }
            catch (error: Exception) { failure = error; releaseNative() }
            catch (error: LinkageError) { failure = error; releaseNative() }
            finally { ready.countDown() }
        })
        if (!ready.await(5, TimeUnit.SECONDS)) throw PlanarGpuSource.InitializationTimedOut()
        failure?.let { throw PlanarGpuSource.InitializationFailed(it) }
        check(!closed.get())
        return checkNotNull(input)
    }

    private fun initialize() {
        NativeWebRtcRuntime.ensure(request.context)
        val base = EglBase.create(null, EglBase.CONFIG_PIXEL_BUFFER)
        egl = base
        base.createDummyPbufferSurface(); base.makeCurrent()
        check(GLES20.glGetString(GLES20.GL_EXTENSIONS)?.split(' ')
            ?.contains("GL_OES_EGL_image_external") == true)
        val names = IntArray(1)
        GLES20.glGenTextures(1, names, 0)
        textureId = names[0]; check(textureId != 0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        check(GLES20.glGetError() == GLES20.GL_NO_ERROR)
        converter = YuvConverter()
        verifyColors()
        val texture = SurfaceTexture(textureId)
        producer = texture
        texture.setDefaultBufferSize(request.width, request.height)
        input = Surface(texture)
        texture.setOnFrameAvailableListener({
            if (!closed.get() && !failed.get() && queued.compareAndSet(false, true)) {
                handler.post {
                    queued.set(false)
                    if (!closed.get() && !failed.get()) draw()
                }
            }
        }, handler)
        handler.postDelayed(idle, request.refreshIntervalMs)
    }

    private fun verifyColors() {
        val names = IntArray(1)
        GLES20.glGenTextures(1,names,0); check(names[0] != 0)
        try {
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,names[0])
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MIN_FILTER,GLES20.GL_LINEAR)
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MAG_FILTER,GLES20.GL_LINEAR)
            val colors = listOf(intArrayOf(0,0,0,16,128,128),intArrayOf(255,255,255,235,128,128),
                intArrayOf(255,0,0,82,90,240),intArrayOf(0,255,0,144,54,34),intArrayOf(0,0,255,41,240,110))
            for (color in colors) {
                val pixels=ByteBuffer.allocateDirect(16)
                repeat(4) { pixels.put(color[0].toByte()); pixels.put(color[1].toByte()); pixels.put(color[2].toByte()); pixels.put(255.toByte()) }
                pixels.clear()
                GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,names[0])
                GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D,0,GLES20.GL_RGBA,2,2,0,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,pixels)
                val texture=TextureBufferImpl(2,2,VideoFrame.TextureBuffer.Type.RGB,names[0],Matrix(),handler,checkNotNull(converter),{})
                try {
                    val yuv=checkNotNull(converter?.convert(texture))
                    try {
                        for (y in 0..1) for (x in 0..1) check(abs((yuv.dataY.get(y*yuv.strideY+x).toInt() and 255)-color[3]) <= 2)
                        check(abs((yuv.dataU.get(0).toInt() and 255)-color[4]) <= 2)
                        check(abs((yuv.dataV.get(0).toInt() and 255)-color[5]) <= 2)
                    } finally { yuv.release() }
                } finally { texture.release() }
                check(GLES20.glGetError() == GLES20.GL_NO_ERROR)
            }
            Timber.i("GPU planar color_self_test=passed")
        } finally { GLES20.glDeleteTextures(1,names,0) }
    }

    private fun draw() {
        try {
            val producer = checkNotNull(producer)
            try { producer.updateTexImage() }
            catch (error: Exception) {
                if (!closed.get()) request.quality.recordCaptureReadFailure()
                throw error
            }
            producer.getTransformMatrix(matrix)
            val timestamp = producer.timestamp
            if (!request.valid()) return
            pump.frameAccepted(timestamp) {
                val started = System.nanoTime()
                val texture = TextureBufferImpl(request.width, request.height,
                    VideoFrame.TextureBuffer.Type.OES, textureId,
                    RendererCommon.convertMatrixToAndroidGraphicsMatrix(matrix), handler,
                    checkNotNull(converter), {})
                try {
                    val yuv = checkNotNull(converter?.convert(texture))
                    try {
                        check(yuv.width == request.width && yuv.height == request.height)
                        val converted = System.nanoTime()
                        val accepted = request.valid() && request.submit(I420Planes(yuv.width, yuv.height,
                            yuv.dataY, yuv.strideY, yuv.dataU, yuv.strideU, yuv.dataV, yuv.strideV), timestamp / 1000L)
                        val submitted = System.nanoTime()
                        if (windowNs == 0L) windowNs = started
                        samples++; convertNs += converted - started; submitNs += submitted - converted
                        if (submitted - windowNs >= 5_000_000_000L) flushTiming(submitted)
                        accepted
                    } finally { yuv.release() }
                } finally { texture.release() }
            }
        } catch (error: Exception) { fail(error) }
        catch (error: LinkageError) { fail(IllegalStateException("GPU planar native conversion unavailable", error)) }
    }

    private fun fail(error: Exception) {
        pump.close()
        if (!closed.get() && failed.compareAndSet(false, true)) request.failed(error)
    }

    private fun flushTiming(now: Long) {
        if (samples > 0) Timber.i("GPU planar samples=%d convert_mean_ms=%.3f submit_mean_ms=%.3f",
            samples, convertNs / samples / 1_000_000.0, submitNs / samples / 1_000_000.0)
        windowNs = now; samples = 0; convertNs = 0; submitNs = 0
    }

    override fun close(afterRelease: () -> Unit) {
        if (!closed.compareAndSet(false, true)) return
        pump.close()
        if (!::handler.isInitialized) { afterRelease(); return }
        check(handler.post {
            try { handler.removeCallbacks(idle); releaseNative() }
            finally {
                try { afterRelease() }
                finally { thread.quitSafely() }
            }
        }) { "GPU planar owner unavailable for cleanup" }
    }

    private fun releaseNative() {
        fun release(action: () -> Unit) { runCatching(action).onFailure { Timber.w("GPU planar cleanup failure (%s)", it.javaClass.simpleName) } }
        flushTiming(System.nanoTime())
        release { producer?.setOnFrameAvailableListener(null) }
        release { input?.release() }; input = null
        release { producer?.release() }; producer = null
        release { converter?.release() }; converter = null
        release { if (textureId != 0) GLES20.glDeleteTextures(1, intArrayOf(textureId), 0) }; textureId = 0
        release { egl?.release() }; egl = null
    }
}
