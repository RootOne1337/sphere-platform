package com.sphereplatform.agent.streaming

import android.app.Application
import android.content.res.Resources
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class CaptureInputGeometryTest {
    @Test fun `540p canary retains native pixels and density while default remains legacy`() {
        val metrics = Resources.getSystem().displayMetrics
        val oldWidth = metrics.widthPixels; val oldHeight = metrics.heightPixels; val oldDensity = metrics.densityDpi
        val display = (RuntimeEnvironment.getApplication().getSystemService(android.content.Context.DISPLAY_SERVICE) as android.hardware.display.DisplayManager)
            .getDisplay(android.view.Display.DEFAULT_DISPLAY)
        val shadow = org.robolectric.Shadows.shadowOf(display)
        val real = android.util.DisplayMetrics().also { display.getRealMetrics(it) }
        try {
            shadow.setRealWidth(960); shadow.setRealHeight(540); shadow.setDensityDpi(160)
            // Stale application Resources must not override the captured display.
            metrics.widthPixels = 320; metrics.heightPixels = 470; metrics.densityDpi = 240
            val context = RuntimeEnvironment.getApplication()
            assertEquals(VirtualDisplayManager.DisplayConfig(960, 540, 160), VirtualDisplayManager.createConfig(context, true))
            assertEquals(VirtualDisplayManager.DisplayConfig(1280, 720), VirtualDisplayManager.createConfig(context))
            shadow.setRealWidth(540); shadow.setRealHeight(960)
            assertEquals(VirtualDisplayManager.DisplayConfig(540, 960, 160), VirtualDisplayManager.createConfig(context, true))
        } finally {
            metrics.widthPixels = oldWidth; metrics.heightPixels = oldHeight; metrics.densityDpi = oldDensity
            shadow.setRealWidth(real.widthPixels); shadow.setRealHeight(real.heightPixels); shadow.setDensityDpi(real.densityDpi)
        }
    }
    @Test fun `native gesture is identity and legacy gesture scales all points once`() {
        val points = listOf(StreamPoint(320, 180), StreamPoint(640, 360))
        assertEquals(points, CaptureInputGeometry(960, 540, 960, 540).map(points, 960, 540))
        assertEquals(listOf(StreamPoint(240, 135), StreamPoint(480, 270)),
            CaptureInputGeometry(960, 540, 1280, 720).map(points, 960, 540))
    }
    @Test fun `rotation resize or any out of bounds point rejects the whole gesture`() {
        val geometry = CaptureInputGeometry(960, 540, 960, 540)
        assertNull(geometry.map(listOf(StreamPoint(1, 2)), 540, 960))
        assertNull(geometry.map(listOf(StreamPoint(1, 2)), 1280, 720))
        assertNull(geometry.map(listOf(StreamPoint(1, 2)), 960, 540, 2))
        assertNull(geometry.map(listOf(StreamPoint(1, 2), StreamPoint(960, 2)), 960, 540))
        assertNull(geometry.map(listOf(StreamPoint(-1, 0)), 960, 540))
        assertNull(geometry.map(emptyList(), 960, 540))
    }
    @Test fun `wide dimension multiplication does not overflow into negative input`() {
        val geometry = CaptureInputGeometry(100_000, 100_000, 100_000, 100_000)
        assertEquals(listOf(StreamPoint(99_999, 99_999)),
            geometry.map(listOf(StreamPoint(99_999, 99_999)), 100_000, 100_000))
    }
}
