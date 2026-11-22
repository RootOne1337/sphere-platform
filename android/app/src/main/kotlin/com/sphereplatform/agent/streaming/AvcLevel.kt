package com.sphereplatform.agent.streaming

import android.media.MediaCodecInfo.CodecProfileLevel

/** Baseline limits from H.264 Annex A; includes cadence and bitrate, not only picture size. */
internal enum class AvcLevel(val androidLevel: Int, val id: Int, val picture: Long, val perSecond: Long, val bitrate: Int) {
    L31(CodecProfileLevel.AVCLevel31, 31, 3600, 108000, 14_000_000),
    L32(CodecProfileLevel.AVCLevel32, 32, 5120, 216000, 20_000_000),
    L4(CodecProfileLevel.AVCLevel4, 40, 8192, 245760, 20_000_000),
    L41(CodecProfileLevel.AVCLevel41, 41, 8192, 245760, 50_000_000),
    L42(CodecProfileLevel.AVCLevel42, 42, 8704, 522240, 50_000_000),
    L5(CodecProfileLevel.AVCLevel5, 50, 22080, 589824, 135_000_000),
    L51(CodecProfileLevel.AVCLevel51, 51, 36864, 983040, 240_000_000),
    L52(CodecProfileLevel.AVCLevel52, 52, 36864, 2073600, 240_000_000);

    val profileLevelId: String get() = "42e0" + id.toString(16).padStart(2, '0')

    companion object {
        fun required(width: Int, height: Int, fps: Int, bitrate: Int): AvcLevel {
            require(width > 0 && height > 0 && fps in 1..60 && bitrate > 0)
            val blocks = ((width + 15L) / 16) * ((height + 15L) / 16)
            return entries.firstOrNull { blocks <= it.picture && blocks * fps <= it.perSecond && bitrate <= it.bitrate }
                ?: throw IllegalArgumentException("AVC source exceeds supported level budget")
        }
    }
}
