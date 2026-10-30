package com.sphereplatform.agent.streaming

import android.media.MediaCodec
import android.view.Surface
import io.mockk.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class EncoderResourceOwnershipTest {
    private val codec = mockk<MediaCodec>(relaxed = true)
    private val surface = mockk<Surface>(relaxed = true)
    private val encoder = H264Encoder(H264Encoder.EncoderConfig()) { _, _ -> }

    @Before fun setup() {
        mockkStatic(MediaCodec::class)
        every { MediaCodec.createEncoderByType(any()) } returns codec
        every { codec.createInputSurface() } returns surface
    }
    @After fun cleanup() { encoder.stop(); unmockkAll() }

    @Test fun `failed configure releases the newly created codec`() {
        every { codec.configure(any(), any(), null as android.media.MediaCrypto?, any()) } throws IllegalStateException("configure failed")
        try { encoder.start(); fail("must propagate configure failure") } catch (expected: IllegalStateException) { }
        verify(exactly = 1) { codec.release() }
        verify(exactly = 0) { surface.release() }
    }
    @Test fun `failed start releases both codec and its input Surface`() {
        every { codec.start() } throws IllegalStateException("start failed")
        try { encoder.start(); fail("must propagate start failure") } catch (expected: IllegalStateException) { }
        encoder.stop()
        verify(exactly = 1) { codec.release() }
        verify(exactly = 1) { surface.release() }
    }
    @Test fun `codec stop exception cannot prevent release of owned native resources`() {
        encoder.start()
        every { codec.stop() } throws IllegalStateException("codec dead")
        encoder.stop()
        verify(exactly = 1) { codec.release() }
        verify(exactly = 1) { surface.release() }
    }
    @Test fun `repeated stop releases the input Surface exactly once`() {
        encoder.start(); encoder.stop(); encoder.stop()
        verify(exactly = 1) { codec.stop() }
        verify(exactly = 1) { codec.release() }
        verify(exactly = 1) { surface.release() }
    }
}
