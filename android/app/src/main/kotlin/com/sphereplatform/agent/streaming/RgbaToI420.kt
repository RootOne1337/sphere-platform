package com.sphereplatform.agent.streaming

import java.nio.ByteBuffer

internal interface NativeRgbaConversion {
    val available: Boolean
    fun convert(source: ByteBuffer, rowStride: Int, width: Int, height: Int, output: ByteBuffer): Boolean
}

/** Owned reusable RGBA -> planar YUV420, BT.601 limited range; no pixel-array allocation per frame. */
internal class RgbaToI420(private val width: Int, private val height: Int,
    private val native: NativeRgbaConversion = NativeRgbaToI420,
) {
    init {
        require(width in 2..4096 && height in 2..4096 && width % 2 == 0 && height % 2 == 0)
    }
    private val ySize = width * height
    private val cSize = ySize / 4
    val outputSize = ySize + 2 * cSize
    private var rgba = ByteArray(0)
    private val i420 = ByteArray(outputSize)
    private var nativeOutput: ByteBuffer? = null
    private var lastWasNative = false

    /** Caller owns capture lifetime and proves a prior successful submission. */
    fun copyLastConverted(destination: ByteBuffer) {
        require(!destination.isReadOnly && destination.capacity() >= outputSize)
        destination.clear()
        if (lastWasNative) destination.put(checkNotNull(nativeOutput).duplicate().apply { clear(); limit(outputSize) })
        else destination.put(i420)
    }

    fun convert(source: ByteBuffer, rowStride: Int, pixelStride: Int, destination: ByteBuffer) {
        require(pixelStride >= 4 && rowStride.toLong() >= width.toLong() * pixelStride)
        val required = (height - 1L) * rowStride + (width - 1L) * pixelStride + 4
        require(required in 1..Int.MAX_VALUE.toLong() && source.limit().toLong() >= required)
        require(!destination.isReadOnly && destination.capacity() >= outputSize)
        // ImageReader exposes direct RGBA planes. The existing WebRTC library
        // supplies libyuv once its normal initialization and color self-test pass.
        // A failed optional conversion touches only owned scratch, never a codec
        // input already queued for delivery. Fallback overwrites the whole frame.
        if (pixelStride == 4 && source.isDirect && native.available) {
            val scratch = nativeOutput ?: ByteBuffer.allocateDirect(outputSize).also { nativeOutput = it }
            if (native.convert(source.duplicate().apply { position(0) }, rowStride, width, height, scratch)) {
                lastWasNative = true
                destination.clear(); destination.put(scratch.duplicate().apply { clear(); limit(outputSize) })
                return
            }
        }
        lastWasNative = false
        if (rgba.size != required.toInt()) rgba = ByteArray(required.toInt())
        // The last plane row need not expose its trailing padding. Do not consume
        // the caller's buffer position or copy an assumed rowStride * height.
        source.duplicate().apply { position(0); get(rgba) }
        for (y in 0 until height step 2) {
            for (x in 0 until width step 2) {
                var sumR = 0; var sumG = 0; var sumB = 0
                for (dy in 0..1) {
                    var input = (y + dy) * rowStride + x * pixelStride
                    var output = (y + dy) * width + x
                    for (dx in 0..1) {
                        val r = rgba[input].toInt() and 255
                        val g = rgba[input + 1].toInt() and 255
                        val b = rgba[input + 2].toInt() and 255
                        i420[output] = (((66 * r + 129 * g + 25 * b + 128) shr 8) + 16).toByte()
                        sumR += r; sumG += g; sumB += b
                        input += pixelStride; output++
                    }
                }
                val r = (sumR + 2) / 4; val g = (sumG + 2) / 4; val b = (sumB + 2) / 4
                val chroma = (y / 2) * (width / 2) + x / 2
                i420[ySize + chroma] = (((-38 * r - 74 * g + 112 * b + 128) shr 8) + 128).toByte()
                i420[ySize + cSize + chroma] = (((112 * r - 94 * g - 18 * b + 128) shr 8) + 128).toByte()
            }
        }
        destination.clear(); destination.put(i420)
    }
}
