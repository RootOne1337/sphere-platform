package com.sphereplatform.agent.streaming

import android.media.MediaCodec
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
class PlanarKeyFrameRefreshTest {
    private val codec = mockk<MediaCodec>(relaxed = true)
    private val callback = slot<MediaCodec.Callback>()
    private var now = 1_000_000L
    private val encoder = H264Encoder(H264Encoder.EncoderConfig(width=2,height=2), { now }) { _, _ -> }
    private val destination = ByteBuffer.allocate(6)
    private val rgba = ByteBuffer.allocate(16).apply { put(byteArrayOf(-1,0,0,-1, 0,-1,0,-1, 0,0,-1,-1, -1,-1,-1,-1)); rewind() }
    private var errors = 0

    @Before fun setup() {
        mockkStatic(MediaCodec::class)
        every { MediaCodec.createByCodecName("OMX.google.h264.encoder") } returns codec
        val caps = MediaCodecInfoBuilder.CodecCapabilitiesBuilder.newBuilder()
            .setMediaFormat(MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC,2,2))
            .setIsEncoder(true).setColorFormats(intArrayOf(19)).build()
        every { codec.codecInfo } returns MediaCodecInfoBuilder.newBuilder().setName("OMX.google.h264.encoder")
            .setIsEncoder(true).setCapabilities(caps).build()
        every { codec.setCallback(capture(callback)) } just Runs
        every { codec.getInputBuffer(any()) } returns destination
        encoder.onEncoderError = { errors++ }
        encoder.startPlanar()
    }
    @After fun cleanup() { encoder.stop(); unmockkAll() }

    private fun source() {
        callback.captured.onInputBufferAvailable(codec,7)
        assertTrue(encoder.submitPlanarFrame(rgba,8,4,123L))
    }

    @Test fun `viewer before first capture never queues an uninitialized black cache`() {
        callback.captured.onInputBufferAvailable(codec,7)
        assertTrue(encoder.requestKeyFrame())
        verify(exactly=0) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
        assertTrue(encoder.submitPlanarFrame(rgba,8,4,123L))
        verify(exactly=1) { codec.queueInputBuffer(7,0,6,123L,0) }
        callback.captured.onInputBufferAvailable(codec,7)
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }

    @Test fun `static viewer request feeds the same owned pixels as a new native input`() {
        source()
        val pixels = destination.array().copyOf()
        destination.clear(); destination.put(ByteArray(6))
        callback.captured.onInputBufferAvailable(codec,7)
        assertTrue(encoder.requestKeyFrame())
        assertArrayEquals(pixels,destination.array())
        verify(exactly=1) { codec.queueInputBuffer(7,0,6,1000L,0) }
        verify(exactly=0) { codec.createInputSurface() }
    }

    @Test fun `busy codec coalesces multiple refresh requests into one pending raw input`() {
        source()
        repeat(50) { assertTrue(encoder.requestKeyFrame()) }
        verify(exactly=1) { codec.setParameters(any()) }
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
        callback.captured.onInputBufferAvailable(codec,7)
        verify(exactly=2) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
        callback.captured.onInputBufferAvailable(codec,7)
        verify(exactly=2) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }

    @Test fun `invalid cached input capacity fences before native queue without a looper failure`() {
        source(); assertTrue(encoder.requestKeyFrame())
        every { codec.getInputBuffer(7) } returns ByteBuffer.allocate(1)
        callback.captured.onInputBufferAvailable(codec,7)
        assertEquals(1,errors)
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
        assertFalse(encoder.submitPlanarFrame(rgba,8,4,124L))
    }

    @Test fun `normal producer timestamps stay strictly increasing after a viewer refresh`() {
        source(); callback.captured.onInputBufferAvailable(codec,7)
        assertTrue(encoder.requestKeyFrame())
        callback.captured.onInputBufferAvailable(codec,7)
        assertTrue(encoder.submitPlanarFrame(rgba,8,4,124L))
        verify(exactly=1) { codec.queueInputBuffer(7,0,6,1001L,0) }
    }

    @Test fun `refresh requests are rate bounded while retaining free input indexes`() {
        source(); callback.captured.onInputBufferAvailable(codec,7)
        assertTrue(encoder.requestKeyFrame())
        callback.captured.onInputBufferAvailable(codec,7)
        repeat(50) { assertTrue(encoder.requestKeyFrame()) }
        verify(exactly=2) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
        now += 250_000_000L
        assertTrue(encoder.requestKeyFrame())
        verify(exactly=3) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }

    @Test fun `stop retires pending refresh and pixel ownership before delayed input callbacks`() {
        source(); assertTrue(encoder.requestKeyFrame()); encoder.stop()
        callback.captured.onInputBufferAvailable(codec,7)
        assertFalse(encoder.requestKeyFrame())
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }

    @Test fun `uncertain cached queue failure fences without a second native submission`() {
        source(); callback.captured.onInputBufferAvailable(codec,7)
        every { codec.queueInputBuffer(7,0,6,1000L,0) } throws IllegalStateException("uncertain native completion")
        assertFalse(encoder.requestKeyFrame()); assertEquals(1,errors)
        callback.captured.onInputBufferAvailable(codec,7)
        now += 300_000_000L
        assertFalse(encoder.requestKeyFrame())
        verify(exactly=1) { codec.queueInputBuffer(7,0,6,1000L,0) }
    }

    @Test fun `deferred callback failures never escape the codec looper or retry pending pixels`() {
        source(); assertTrue(encoder.requestKeyFrame())
        every { codec.queueInputBuffer(7,0,6,1000L,0) } throws IllegalStateException("uncertain callback queue")
        callback.captured.onInputBufferAvailable(codec,7)
        callback.captured.onInputBufferAvailable(codec,8)
        assertEquals(1,errors)
        verify(exactly=1) { codec.queueInputBuffer(7,0,6,1000L,0) }
    }

    @Test fun `replacement codec cannot receive the retired capture cache or its input indexes`() {
        source(); assertTrue(encoder.requestKeyFrame()); encoder.stop()
        val replacement = mockk<MediaCodec>(relaxed=true)
        every { MediaCodec.createByCodecName("OMX.google.h264.encoder") } returns replacement
        every { replacement.codecInfo } returns codec.codecInfo
        every { replacement.setCallback(capture(callback)) } just Runs
        encoder.startPlanar()
        callback.captured.onInputBufferAvailable(codec,7)
        callback.captured.onInputBufferAvailable(replacement,8)
        assertTrue(encoder.requestKeyFrame())
        verify(exactly=0) { replacement.queueInputBuffer(any(),any(),any(),any(),any()) }
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }

    @Test fun `rejected sync parameters contain one failure and cannot submit cached pixels`() {
        source(); callback.captured.onInputBufferAvailable(codec,7)
        every { codec.setParameters(any()) } throws IllegalArgumentException("unsupported sync request")
        assertFalse(encoder.requestKeyFrame()); assertEquals(1,errors)
        callback.captured.onInputBufferAvailable(codec,8)
        assertFalse(encoder.requestKeyFrame())
        verify(exactly=1) { codec.setParameters(any()) }
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }

    @Test fun `uncertain source queue also retires cached refresh and later producer input`() {
        callback.captured.onInputBufferAvailable(codec,7)
        every { codec.queueInputBuffer(7,0,6,123L,0) } throws IllegalStateException("uncertain source queue")
        assertThrows(IllegalStateException::class.java) { encoder.submitPlanarFrame(rgba,8,4,123L) }
        assertEquals(1,errors)
        callback.captured.onInputBufferAvailable(codec,8)
        assertFalse(encoder.submitPlanarFrame(rgba,8,4,124L))
        assertFalse(encoder.requestKeyFrame())
        verify(exactly=1) { codec.queueInputBuffer(any(),any(),any(),any(),any()) }
    }
}
