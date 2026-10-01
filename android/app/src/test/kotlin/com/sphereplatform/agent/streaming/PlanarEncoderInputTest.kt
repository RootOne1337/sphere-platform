package com.sphereplatform.agent.streaming

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import io.mockk.*
import java.nio.ByteBuffer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.MediaCodecInfoBuilder

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class PlanarEncoderInputTest {
    private val codec = mockk<MediaCodec>(relaxed = true)
    private val callback = slot<MediaCodec.Callback>()
    private val encoder = H264Encoder(H264Encoder.EncoderConfig(width=2,height=2)) { _,_ -> }
    private val destination = ByteBuffer.allocate(6)
    private fun rgba() = ByteBuffer.allocate(16)

    @Before fun setup() {
        mockkStatic(MediaCodec::class)
        every { MediaCodec.createByCodecName("OMX.google.h264.encoder") } returns codec
        val caps = MediaCodecInfoBuilder.CodecCapabilitiesBuilder.newBuilder()
            .setMediaFormat(MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC,2,2))
            .setIsEncoder(true).setColorFormats(intArrayOf(19)).build()
        val info = MediaCodecInfoBuilder.newBuilder().setName("OMX.google.h264.encoder")
            .setIsEncoder(true).setCapabilities(caps).build()
        every { codec.codecInfo } returns info
        every { codec.setCallback(capture(callback)) } just Runs
        every { codec.getInputBuffer(7) } returns destination
    }
    @After fun cleanup() { encoder.stop(); unmockkAll() }

    @Test fun `no free input drops raw frame without allocating a Surface or queueing coded data`() {
        encoder.startPlanar()
        assertFalse(encoder.submitPlanarFrame(rgba(),8,4,123))
        verify(exactly=0) { codec.createInputSurface() }
        verify(exactly=0) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }
    @Test fun `an admitted picture uses the producer timestamp and exact I420 size`() {
        encoder.startPlanar(); callback.captured.onInputBufferAvailable(codec,7)
        assertTrue(encoder.submitPlanarFrame(rgba(),8,4,123))
        assertArrayEquals(byteArrayOf(16,16,16,16,-128,-128),destination.array())
        verify(exactly=1) { codec.queueInputBuffer(7,0,6,123L,0) }
        assertFalse(encoder.submitPlanarFrame(rgba(),8,4,124))
    }
    @Test fun `invalid raw buffer does not consume the unqueued input index`() {
        encoder.startPlanar(); callback.captured.onInputBufferAvailable(codec,7)
        assertThrows(IllegalArgumentException::class.java) { encoder.submitPlanarFrame(ByteBuffer.allocate(1),8,4,123) }
        assertTrue(encoder.submitPlanarFrame(rgba(),8,4,124))
        verify(exactly=1) { codec.queueInputBuffer(7,0,6,124L,0) }
    }
    @Test fun `stop disables submission and callbacks from an obsolete codec`() {
        encoder.startPlanar(); encoder.stop()
        callback.captured.onInputBufferAvailable(codec,7)
        assertFalse(encoder.submitPlanarFrame(rgba(),8,4,123))
        verify(exactly=1) { codec.release() }
        verify(exactly=0) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }
    @Test fun `failed planar configure releases the codec without a Surface leak`() {
        every { codec.configure(any(),any(),null as android.media.MediaCrypto?,any()) } throws IllegalArgumentException("unsupported")
        assertThrows(IllegalArgumentException::class.java) { encoder.startPlanar() }
        encoder.stop()
        verify(exactly=1) { codec.release() }
        verify(exactly=0) { codec.createInputSurface() }
    }
    @Test fun `uncertain queue failure is reported without retrying the picture`() {
        var errors=0; encoder.onEncoderError={ errors++ }
        encoder.startPlanar(); callback.captured.onInputBufferAvailable(codec,7)
        every { codec.queueInputBuffer(any(),any(),any(),any(),any()) } throws IllegalStateException("codec stopped")
        assertThrows(IllegalStateException::class.java) { encoder.submitPlanarFrame(rgba(),8,4,123) }
        assertEquals(1,errors)
        assertFalse(encoder.submitPlanarFrame(rgba(),8,4,124))
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }
}
