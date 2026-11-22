package com.sphereplatform.agent.streaming

import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat

/** Capability admission is not a benchmark; observed capture/encoder FPS stay separate. */
internal object StreamCodecCapability {
    fun source(width: Int, height: Int, refreshRate: Float, planar: Boolean): StreamQualityPolicy.Source {
        val wanted = StreamQualityPolicy.Source(width, height, refreshRate)
        return runCatching {
            val infos = MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos
            val info = if (planar) infos.first { it.name == "OMX.google.h264.encoder" }
                else infos.first { it.isEncoder && it.supportedTypes.any { type -> type.equals(MediaFormat.MIMETYPE_VIDEO_AVC, true) } }
            val caps = info.getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC)
            val video = checkNotNull(caps.videoCapabilities)
            val baselineLevels = caps.profileLevels.filter { it.profile == MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline
                || it.profile == MediaCodecInfo.CodecProfileLevel.AVCProfileConstrainedBaseline }.map { it.level }
            val maxLevel = AvcLevel.entries.lastOrNull { level -> baselineLevels.any { it >= level.androidLevel } }
            val maxBitrate = minOf(video.bitrateRange.upper.coerceIn(100_000, 32_000_000), maxLevel?.bitrate ?: 14_000_000)
            val ceiling = (wanted.maximumFps downTo 1).first { fps ->
                val required = AvcLevel.required(width, height, fps, maxBitrate)
                video.areSizeAndRateSupported(width, height, fps.toDouble()) &&
                    (baselineLevels.isEmpty() || baselineLevels.any { it >= required.androidLevel })
            }
            wanted.copy(codecMaxFps = ceiling, codecMaxBitrate = maxBitrate)
        }.getOrElse {
            // Unreported capabilities do not authorize forcing 60 FPS on an unknown codec.
            wanted.copy(codecMaxFps = minOf(30, wanted.maximumFps), codecMaxBitrate = 14_000_000)
        }
    }
}
