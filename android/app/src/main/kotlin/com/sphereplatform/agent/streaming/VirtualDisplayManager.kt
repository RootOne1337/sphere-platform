package com.sphereplatform.agent.streaming

import android.content.Context
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.projection.MediaProjection
import android.view.Surface

/**
 * Creates and manages a [VirtualDisplay] that mirrors the device screen into
 * the encoder's input [Surface].
 *
 * The Surface is provided by [H264Encoder.start()] (SPLIT-2) and must remain
 * valid for the lifetime of the [VirtualDisplay].
 */
class VirtualDisplayManager(
    private val context: Context,
    private val mediaProjection: MediaProjection,
) {
    data class DisplayConfig(
        val width: Int,
        val height: Int,
        val dpi: Int = 240,
    )

    companion object {
        fun createConfig(context: Context): DisplayConfig {
            val metrics = android.content.res.Resources.getSystem().displayMetrics
            val isLandscape = metrics.widthPixels > metrics.heightPixels
            val width = if (isLandscape) 1280 else 720
            val height = if (isLandscape) 720 else 1280
            
            return DisplayConfig(width = width, height = height)
        }
    }

    private var virtualDisplay: VirtualDisplay? = null

    // LOW-5: parameter renamed to encoderSurface — clarifies that this is the
    // Surface obtained from MediaCodec.createInputSurface(), not any Surface.
    fun createDisplay(config: DisplayConfig, encoderSurface: Surface): VirtualDisplay {
        check(virtualDisplay == null) {
            "VirtualDisplay already created — call release() first"
        }

        return mediaProjection.createVirtualDisplay(
            "SphereCapture",
            config.width,
            config.height,
            config.dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            encoderSurface,
            null,  // callback
            null,  // handler — use calling thread's looper
        ).also { virtualDisplay = it }
    }

    fun release() {
        virtualDisplay?.release()
        virtualDisplay = null
    }
}
