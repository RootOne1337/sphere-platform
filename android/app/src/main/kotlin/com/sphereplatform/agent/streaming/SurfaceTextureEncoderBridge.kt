package com.sphereplatform.agent.streaming

import android.graphics.SurfaceTexture
import android.opengl.EGL14
import android.opengl.EGLConfig
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLExt
import android.opengl.EGLSurface
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.os.Handler
import android.os.HandlerThread
import android.view.Surface
import timber.log.Timber
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * MediaProjection -> SurfaceTexture/OES -> recordable EGL -> MediaCodec.
 * No RGBA readback, Bitmap allocation/copy or CPU Canvas on the frame path.
 * All GL calls and destruction belong to one thread, including partial init.
 * The encoder's input Surface is borrowed; its owner releases it after close.
 */
internal class SurfaceTextureEncoderBridge(
    private val output: Surface,
    private val width: Int,
    private val height: Int,
    throttle: FrameThrottle,
    private val quality: StreamQualityMonitor,
    private val onFailure: (Exception) -> Unit,
) {
    private lateinit var thread: HandlerThread
    private lateinit var handler: Handler
    private val closed = AtomicBoolean(false)
    private val drawQueued = AtomicBoolean(false)
    private val failed = AtomicBoolean(false)
    private val pump = GpuFramePump(throttle, quality)
    private var display: EGLDisplay? = null
    private var context: EGLContext? = null
    private var window: EGLSurface? = null
    private var textureId = 0
    private var program = 0
    private var producer: SurfaceTexture? = null
    private var input: Surface? = null
    private val matrix = FloatArray(16)
    private val positions = floats(floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f))
    private val coordinates = floats(floatArrayOf(0f, 0f, 1f, 0f, 0f, 1f, 1f, 1f))
    private var positionLocation = -1
    private var coordinateLocation = -1
    private var matrixLocation = -1
    private var samplerLocation = -1

    class InitializationFailed(cause: Exception) : IllegalStateException("GPU capture initialization failed", cause)
    class InitializationTimedOut : IllegalStateException("GPU capture initialization deadline exceeded")

    fun start(): Surface {
        check(!closed.get() && !::handler.isInitialized) { "GPU capture already started or closed" }
        thread = HandlerThread("sphere-capture-gl").also { it.start() }
        handler = Handler(thread.looper)
        val ready = CountDownLatch(1)
        var failure: Exception? = null
        check(handler.post {
            try {
                if (!closed.get()) initialize()
            } catch (error: Exception) {
                failure = error
                releaseNative() // Disconnect window producer before a CPU fallback.
            } finally { ready.countDown() }
        })
        if (!ready.await(5, TimeUnit.SECONDS)) throw InitializationTimedOut()
        failure?.let { throw InitializationFailed(it) }
        check(!closed.get()) { "GPU capture closed during initialization" }
        return checkNotNull(input)
    }

    /** Nonblocking stop. Encoder destruction is queued AFTER the last GL draw. */
    fun close(afterRelease: () -> Unit = {}) {
        if (!closed.compareAndSet(false, true)) return
        pump.close() // Fence counters before the manager resets the session.
        if (!::handler.isInitialized) { afterRelease(); return }
        check(handler.post {
            try { pump.close(); releaseNative() }
            finally {
                try { afterRelease() }
                finally { thread.quitSafely() }
            }
        }) { "GPU owner thread unavailable for cleanup" }
    }

    private fun initialize() {
        display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
        check(display != null && display != EGL14.EGL_NO_DISPLAY)
        val versions = IntArray(2)
        check(EGL14.eglInitialize(display, versions, 0, versions, 1))
        check(EGL14.eglQueryString(display, EGL14.EGL_EXTENSIONS)
            ?.split(' ')?.contains("EGL_ANDROID_presentation_time") == true)
        val configs = arrayOfNulls<EGLConfig>(1)
        val count = IntArray(1)
        val attributes = intArrayOf(
            EGL14.EGL_RED_SIZE, 8, EGL14.EGL_GREEN_SIZE, 8, EGL14.EGL_BLUE_SIZE, 8,
            EGL14.EGL_ALPHA_SIZE, 8, EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT,
            EGL14.EGL_SURFACE_TYPE, EGL14.EGL_WINDOW_BIT,
            0x3142, 1, // EGL_RECORDABLE_ANDROID
            EGL14.EGL_NONE,
        )
        check(EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0) && count[0] > 0)
        context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
            intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE), 0)
        check(context != null && context != EGL14.EGL_NO_CONTEXT)
        window = EGL14.eglCreateWindowSurface(display, configs[0], output, intArrayOf(EGL14.EGL_NONE), 0)
        check(window != null && window != EGL14.EGL_NO_SURFACE)
        check(EGL14.eglMakeCurrent(display, window, window, context))
        check(GLES20.glGetString(GLES20.GL_EXTENSIONS)?.split(' ')
            ?.contains("GL_OES_EGL_image_external") == true)
        program = createProgram()
        positionLocation = GLES20.glGetAttribLocation(program, "position")
        coordinateLocation = GLES20.glGetAttribLocation(program, "coordinate")
        matrixLocation = GLES20.glGetUniformLocation(program, "textureMatrix")
        samplerLocation = GLES20.glGetUniformLocation(program, "image")
        check(listOf(positionLocation, coordinateLocation, matrixLocation, samplerLocation).all { it >= 0 })
        val names = IntArray(1)
        GLES20.glGenTextures(1, names, 0)
        textureId = names[0]
        check(textureId != 0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        checkGl()
        val texture = SurfaceTexture(textureId)
        producer = texture
        texture.setDefaultBufferSize(width, height)
        input = Surface(texture)
        texture.setOnFrameAvailableListener({
            if (!closed.get() && !failed.get() && drawQueued.compareAndSet(false, true)) {
                handler.post {
                    drawQueued.set(false)
                    if (!closed.get() && !failed.get()) drawFrame()
                }
            }
        }, handler)
    }

    private fun drawFrame() {
        try {
            val texture = checkNotNull(producer)
            try {
                texture.updateTexImage() // Drain producer buffer even if FPS gate skips it.
            } catch (error: Exception) {
                if (!closed.get()) quality.recordCaptureReadFailure()
                throw error
            }
            texture.getTransformMatrix(matrix) // Includes producer crop/orientation; no hardcoded flip.
            val timestamp = texture.timestamp
            pump.frame(timestamp) {
                GLES20.glViewport(0, 0, width, height)
                GLES20.glUseProgram(program)
                GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
                GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
                GLES20.glUniform1i(samplerLocation, 0)
                GLES20.glUniformMatrix4fv(matrixLocation, 1, false, matrix, 0)
                positions.position(0); coordinates.position(0)
                GLES20.glEnableVertexAttribArray(positionLocation)
                GLES20.glEnableVertexAttribArray(coordinateLocation)
                GLES20.glVertexAttribPointer(positionLocation, 2, GLES20.GL_FLOAT, false, 0, positions)
                GLES20.glVertexAttribPointer(coordinateLocation, 2, GLES20.GL_FLOAT, false, 0, coordinates)
                GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
                GLES20.glDisableVertexAttribArray(positionLocation)
                GLES20.glDisableVertexAttribArray(coordinateLocation)
                checkGl()
                check(EGLExt.eglPresentationTimeANDROID(display, window, timestamp))
                check(EGL14.eglSwapBuffers(display, window))
            }
        } catch (error: Exception) {
            // Stop native draws immediately. Manager schedules cleanup/codec
            // stop on the owner thread; no silent CPU switch mid-GOP/session.
            pump.close()
            if (!closed.get() && failed.compareAndSet(false, true)) onFailure(error)
        }
    }

    private fun releaseNative() {
        fun release(action: () -> Unit) { runCatching(action).onFailure { Timber.w(it, "GPU capture cleanup failure") } }
        release { producer?.setOnFrameAvailableListener(null) }
        release { input?.release() }; input = null
        release { producer?.release() }; producer = null
        if (display != null && display != EGL14.EGL_NO_DISPLAY) {
            release { if (program != 0) GLES20.glDeleteProgram(program) }; program = 0
            release { if (textureId != 0) GLES20.glDeleteTextures(1, intArrayOf(textureId), 0) }; textureId = 0
            release { EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT) }
            release { if (window != null && window != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, window) }
            release { if (context != null && context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context) }
            release { EGL14.eglReleaseThread() }
            release { EGL14.eglTerminate(display) }
        }
        display = null; context = null; window = null
    }

    private fun createProgram(): Int {
        val vertex = shader(GLES20.GL_VERTEX_SHADER, """
            attribute vec4 position;
            attribute vec4 coordinate;
            uniform mat4 textureMatrix;
            varying vec2 uv;
            void main() { gl_Position = position; uv = (textureMatrix * coordinate).xy; }
        """.trimIndent())
        var fragment = 0
        var linked = 0
        try {
            fragment = shader(GLES20.GL_FRAGMENT_SHADER, """
                #extension GL_OES_EGL_image_external : require
                precision mediump float;
                varying vec2 uv;
                uniform samplerExternalOES image;
                void main() { gl_FragColor = texture2D(image, uv); }
            """.trimIndent())
            linked = GLES20.glCreateProgram()
            check(linked != 0)
            GLES20.glAttachShader(linked, vertex); GLES20.glAttachShader(linked, fragment)
            GLES20.glLinkProgram(linked)
            val status = IntArray(1)
            GLES20.glGetProgramiv(linked, GLES20.GL_LINK_STATUS, status, 0)
            check(status[0] == GLES20.GL_TRUE) { "GPU capture shader link failed" }
            return linked
        } catch (error: Exception) {
            if (linked != 0) GLES20.glDeleteProgram(linked)
            throw error
        } finally {
            GLES20.glDeleteShader(vertex)
            if (fragment != 0) GLES20.glDeleteShader(fragment)
        }
    }

    private fun shader(type: Int, text: String): Int {
        val shader = GLES20.glCreateShader(type)
        check(shader != 0)
        GLES20.glShaderSource(shader, text); GLES20.glCompileShader(shader)
        val status = IntArray(1)
        GLES20.glGetShaderiv(shader, GLES20.GL_COMPILE_STATUS, status, 0)
        if (status[0] != GLES20.GL_TRUE) {
            GLES20.glDeleteShader(shader)
            error("GPU capture shader compile failed")
        }
        return shader
    }

    private fun checkGl() { check(GLES20.glGetError() == GLES20.GL_NO_ERROR) { "GPU capture GL error" } }
    private fun floats(values: FloatArray) = ByteBuffer.allocateDirect(values.size * 4)
        .order(ByteOrder.nativeOrder()).asFloatBuffer().apply { put(values); position(0) }
}
