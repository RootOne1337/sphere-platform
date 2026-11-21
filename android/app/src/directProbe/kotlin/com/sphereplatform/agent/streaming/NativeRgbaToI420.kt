package com.sphereplatform.agent.streaming

import java.nio.ByteBuffer
import kotlin.math.abs
import org.webrtc.YuvHelper
import timber.log.Timber

/** Uses the already packaged JNI/libyuv; no separate loader, download or root. */
internal object NativeRgbaToI420 : NativeRgbaConversion {
    @Volatile override var available = false
        private set
    private var attempted = false

    /** Called only after the existing PeerConnectionFactory initialization succeeds. */
    @Synchronized fun activate() {
        if (attempted) return
        attempted = true
        try {
            val colors = listOf(intArrayOf(0,0,0,16,128,128), intArrayOf(255,255,255,235,128,128),
                intArrayOf(255,0,0,82,90,240), intArrayOf(0,255,0,144,54,34), intArrayOf(0,0,255,41,240,110))
            for (color in colors) {
                // Padded first row; last row exposes only its actual two pixels.
                val source = ByteBuffer.allocateDirect(20)
                for (row in 0..1) for (column in 0..1) {
                    val at = row * 12 + column * 4
                    source.put(at,color[0].toByte()); source.put(at+1,color[1].toByte())
                    source.put(at+2,color[2].toByte()); source.put(at+3,255.toByte())
                }
                val output = ByteBuffer.allocateDirect(6)
                nativeConvert(source,12,2,2,output)
                for (i in 0..5) {
                    val expected = color[if (i < 4) 3 else i]
                    check(abs((output.get(i).toInt() and 255)-expected) <= 2) { "native_yuv_color_check" }
                }
            }
            available = true
            Timber.i("NativeRgbaToI420 libyuv color_and_stride_self_test=passed")
        } catch (error: LinkageError) {
            Timber.w("NativeRgbaToI420 unavailable; scalar fallback (%s)",error.javaClass.simpleName)
        } catch (error: RuntimeException) {
            Timber.w("NativeRgbaToI420 self-test refused; scalar fallback (%s)",error.javaClass.simpleName)
        }
    }

    override fun convert(source: ByteBuffer, rowStride: Int, width: Int, height: Int, output: ByteBuffer): Boolean {
        if (!available || !source.isDirect || !output.isDirect) return false
        return try {
            nativeConvert(source,rowStride,width,height,output)
            true
        } catch (error: LinkageError) {
            available = false
            Timber.w("NativeRgbaToI420 disabled; scalar fallback (%s)",error.javaClass.simpleName)
            false
        } catch (error: RuntimeException) {
            available = false
            Timber.w("NativeRgbaToI420 conversion refused; scalar fallback (%s)",error.javaClass.simpleName)
            false
        }
    }

    private fun nativeConvert(source: ByteBuffer, rowStride: Int, width: Int, height: Int, output: ByteBuffer) {
        val ySize = width * height
        val chromaSize = ySize / 4
        fun plane(at: Int, size: Int) = output.duplicate().apply { position(at); limit(at+size) }.slice()
        // libyuv's ABGR name describes register order; little-endian byte memory
        // is R,G,B,A. The runtime red/blue checks above guard this distinction.
        YuvHelper.ABGRToI420(source,rowStride,plane(0,ySize),width,
            plane(ySize,chromaSize),width/2,plane(ySize+chromaSize,chromaSize),width/2,width,height)
    }
}
