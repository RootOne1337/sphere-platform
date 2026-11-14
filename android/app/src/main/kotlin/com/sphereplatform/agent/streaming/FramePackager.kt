package com.sphereplatform.agent.streaming

import java.nio.ByteBuffer
import java.util.UUID

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
 * Canary v2 keeps the prefix, adds a non-nil UUID as 16 network-order bytes
 * at [14:30], and starts the original NAL payload at [30:]. Release/default
 * callers omit the epoch and retain v1. See docs/protocols/VIDEO-CAPTURE-V2.md.
 *
 * FIX-5.1: Timestamp is 8 bytes (Long) — 4-byte UInt32 would overflow after 49 days.
 * The 24/7 farm scenario demands 64-bit precision.
 */
object FramePackager {
    const val HEADER_SIZE = 14
    const val VERSION = 0x01.toByte()
    const val FLAG_KEYFRAME: Byte = 0x01
    const val CAPTURE_VERSION = 0x02.toByte()
    const val CAPTURE_HEADER_SIZE = 30
    const val MAX_CAPTURE_NAL_BYTES = 1024 * 1024

    fun pack(
        nalData: ByteArray,
        metadata: H264Encoder.FrameMetadata,
        streamStartMs: Long,
        captureEpoch: UUID? = null,
    ): ByteArray {
        if (captureEpoch != null) {
            require(captureEpoch != UUID(0, 0)) { "frame_epoch_missing" }
            require(nalData.size in 1..MAX_CAPTURE_NAL_BYTES) { "frame_payload_budget" }
        }
        val timestamp = System.currentTimeMillis() - streamStartMs
        val flags: Byte = if (metadata.isKeyFrame) FLAG_KEYFRAME else 0x00

        val headerSize = if (captureEpoch == null) HEADER_SIZE else CAPTURE_HEADER_SIZE
        return ByteBuffer.allocate(headerSize + nalData.size).apply {
            put(if (captureEpoch == null) VERSION else CAPTURE_VERSION)
            put(flags)
            putLong(timestamp)       // 8 bytes — no overflow
            putInt(nalData.size)
            // v2 extends the v1 prefix by one fixed 128-bit capture identity.
            captureEpoch?.let { putLong(it.mostSignificantBits); putLong(it.leastSignificantBits) }
            put(nalData)
        }.array()
    }
}
