package com.sphereplatform.agent.streaming

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class StreamQualitySnapshot(
    val supported: Boolean,
    val protocol: Int = 1,
    val settings: StreamQualitySettings,
    val active: Active? = null,
) {
    @Serializable
    data class Active(
        val width: Int,
        val height: Int,
        @SerialName("source_fps") val sourceFps: Int,
        @SerialName("codec_max_fps") val codecMaxFps: Int,
        @SerialName("target_fps") val targetFps: Int,
        @SerialName("max_bitrate_bps") val maxBitrateBps: Int,
        @SerialName("target_bitrate_bps") val targetBitrateBps: Int,
        val adaptation: String,
    )
}
