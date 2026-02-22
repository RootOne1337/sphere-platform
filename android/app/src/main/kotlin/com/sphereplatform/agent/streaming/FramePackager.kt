package com.sphereplatform.agent.streaming

import java.nio.ByteBuffer

/**
 * Packs a raw H.264 NAL unit into the Sphere binary frame wire format.
 *
 * Wire format (Big Endian, total header = 14 bytes):
 * ```
 * [0]     Version   (1 byte)  = 0x01
 * [1]     Flags     (1 byte)  bit0 = keyframe
 * [2:10]  Timestamp (8 bytes) = ms since stream start  ← FIX-5.1: Long (64-bit)
 * [10:14] FrameSize (4 bytes) = NAL data length
 * [14:]   NAL data
 * ```
 *
 * FIX-5.1: Timestamp is 8 bytes (Long) — 4-byte UInt32 would overflow after 49 days.
 * The 24/7 farm scenario demands 64-bit precision.
 */
object FramePackager {
    const val HEADER_SIZE = 14
    const val VERSION = 0x01.toByte()
    const val FLAG_KEYFRAME: Byte = 0x01

    fun pack(
        nalData: ByteArray,
        metadata: H264Encoder.FrameMetadata,
        streamStartMs: Long,
    ): ByteArray {
        val timestamp = System.currentTimeMillis() - streamStartMs
        val flags: Byte = if (metadata.isKeyFrame) FLAG_KEYFRAME else 0x00

        return ByteBuffer.allocate(HEADER_SIZE + nalData.size).apply {
            put(VERSION)
            put(flags)
            putLong(timestamp)       // 8 bytes — no overflow
            putInt(nalData.size)
            put(nalData)
        }.array()
    }
}
