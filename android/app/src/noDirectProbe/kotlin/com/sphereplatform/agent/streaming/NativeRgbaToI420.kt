package com.sphereplatform.agent.streaming

import java.nio.ByteBuffer

/** Ordinary builds have no WebRTC dependency and keep the validated scalar path. */
internal object NativeRgbaToI420 : NativeRgbaConversion {
    override val available: Boolean = false
    override fun convert(source: ByteBuffer, rowStride: Int, width: Int, height: Int, output: ByteBuffer): Boolean = false
}
