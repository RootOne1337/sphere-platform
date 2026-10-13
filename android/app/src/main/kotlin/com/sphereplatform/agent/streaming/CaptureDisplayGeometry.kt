package com.sphereplatform.agent.streaming

import android.content.Context
import android.hardware.display.DisplayManager
import android.util.DisplayMetrics
import android.view.Display

/** Source display, not the application window or stale system Resources. */
internal data class CaptureDisplayGeometry(val width: Int, val height: Int, val rotation: Int, val dpi: Int) {
    companion object {
        @Suppress("DEPRECATION")
        fun read(context: Context): CaptureDisplayGeometry? {
            val display = (context.getSystemService(Context.DISPLAY_SERVICE) as? DisplayManager)
                ?.getDisplay(Display.DEFAULT_DISPLAY) ?: return null
            val metrics = DisplayMetrics(); display.getRealMetrics(metrics)
            return if (metrics.widthPixels in 1..16384 && metrics.heightPixels in 1..16384 && display.rotation in 0..3)
                CaptureDisplayGeometry(metrics.widthPixels, metrics.heightPixels, display.rotation, metrics.densityDpi) else null
        }
    }
}
