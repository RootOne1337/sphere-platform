package com.sphereplatform.agent.streaming

import android.app.Application
import android.content.Intent
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class ScreenCaptureServiceTest {
    @Test fun duplicateStartWhileCaptureIsActiveKeepsExistingProjection() {
        val streaming = mockk<StreamingManager>(relaxed = true)
        every { streaming.isActive() } returns true
        // The duplicate-start branch returns before touching Android services,
        // so a detached instance keeps this test independent of Hilt setup.
        val service = ScreenCaptureService()
        service.streamingManager = streaming

        val result = service.onStartCommand(
            Intent().setAction(ScreenCaptureService.ACTION_START),
            0,
            1,
        )

        assertEquals(android.app.Service.START_NOT_STICKY, result)
        verify(exactly = 0) { streaming.stop() }
        verify(exactly = 0) { streaming.start(any()) }
    }
}
