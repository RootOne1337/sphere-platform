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
        try {
            metrics.widthPixels = 960; metrics.heightPixels = 540; metrics.densityDpi = 160
            val context = RuntimeEnvironment.getApplication()
            assertEquals(VirtualDisplayManager.DisplayConfig(960, 540, 160), VirtualDisplayManager.createConfig(context, true))
            assertEquals(VirtualDisplayManager.DisplayConfig(1280, 720), VirtualDisplayManager.createConfig(context))
            metrics.widthPixels = 540; metrics.heightPixels = 960
            assertEquals(VirtualDisplayManager.DisplayConfig(540, 960, 160), VirtualDisplayManager.createConfig(context, true))
        } finally {
            metrics.widthPixels = oldWidth; metrics.heightPixels = oldHeight; metrics.densityDpi = oldDensity
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
