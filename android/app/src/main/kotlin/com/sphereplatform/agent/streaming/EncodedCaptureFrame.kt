package com.sphereplatform.agent.streaming

/** Encoder-owned arrays are immutable after publication. A subscriber must never modify them. */
data class EncodedCaptureFrame(
    val capture: CaptureInputSession,
    val sequence: Long,
    val timestampNs: Long,
    val keyFrame: Boolean,
    val data: ByteArray,
    val sps: ByteArray?,
    val pps: ByteArray?,
)
