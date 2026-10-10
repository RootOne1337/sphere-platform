package com.sphereplatform.agent.direct

import com.sphereplatform.agent.streaming.CaptureInputSession
import com.sphereplatform.agent.streaming.EncodedCaptureFrame
import io.mockk.*
import org.junit.Assert.*
import org.junit.Test
import org.webrtc.*

class DirectEncodedVideoSourceTest {
    private val capture = CaptureInputSession("a".repeat(32), 960, 540, 960, 540, 0)
    private fun nal(vararg values: Int) = byteArrayOf(0, 0, 0, 1) + values.map(Int::toByte).toByteArray()
    private fun picture(sequence: Long, key: Boolean) = EncodedCaptureFrame(capture, sequence,
        sequence * 1_000_000L, key, nal(if (key) 0x65 else 0x41, 0x80),
        nal(0x67, 66, 0xc0, 31, 0x80), nal(0x68, 0xce, 0x80))

    private class Harness {
        var valid = true
        var hold = false
        var holdEncoded = false
        val held = mutableListOf<VideoFrame>()
        val heldEncoded = mutableListOf<EncodedImage>()
        val key = mockk<() -> Unit>(relaxed = true)
        val failed = mockk<() -> Unit>(relaxed = true)
        val capture = CaptureInputSession("a".repeat(32), 960, 540, 960, 540, 0)
        val relay = DirectEncodedVideoSource(capture, { valid }, key, failed)
        val source = mockk<VideoSource>(relaxed = true)
        val track = mockk<VideoTrack>(relaxed = true)
        val factory = mockk<PeerConnectionFactory>()
        val callback = mockk<VideoEncoder.Callback>(relaxed = true)
        val encoder = checkNotNull(relay.encoderFactory.createEncoder(relay.encoderFactory.supportedCodecs[0]))
        val emitted = mutableListOf<ByteArray>()
        private lateinit var processor: VideoProcessor
        init {
            every { factory.createVideoSource(true) } returns source
            every { factory.createVideoTrack("sphere-screen", source) } returns track
            every { source.setVideoProcessor(any()) } answers {
                processor = firstArg()
                processor.setSink { frame ->
                    if (hold) { frame.retain(); held.add(frame) }
                    else encoder.encode(frame, VideoEncoder.EncodeInfo(arrayOf(EncodedImage.FrameType.VideoFrameDelta)))
                }
            }
            every { source.capturerObserver } returns object : CapturerObserver {
                override fun onCapturerStarted(success: Boolean) = Unit
                override fun onCapturerStopped() = Unit
                override fun onFrameCaptured(frame: VideoFrame) {
                    // A generic raw-frame adaptation must never alter coded data.
                    processor.onFrameCaptured(frame, VideoProcessor.FrameAdaptationParameters(
                        0, 0, 960, 540, 480, 270, frame.timestampNs + 100, true))
                }
            }
            every { callback.onEncodedFrame(any(), any()) } answers {
                val image = firstArg<EncodedImage>()
                assertEquals(960, image.encodedWidth); assertEquals(540, image.encodedHeight)
                emitted.add(ByteArray(image.buffer.remaining()).also { image.buffer.duplicate().get(it) })
                if (holdEncoded) { image.retain(); heldEncoded.add(image) }
            }
            relay.start(factory)
            assertEquals(VideoCodecStatus.OK, encoder.initEncode(VideoEncoder.Settings(
                2, 960, 540, 1500, 30, 1, false, VideoEncoder.Capabilities(false)), callback))
        }
        fun close() {
            relay.close(); held.forEach(VideoFrame::release); held.clear()
            heldEncoded.forEach(EncodedImage::release); heldEncoded.clear(); encoder.release()
        }
    }

    @Test fun `existing encoded bytes reach RTP callback with exact dimensions and no raw conversion`() {
        val h = Harness()
        try {
            h.relay.submit(picture(1, false))
            h.relay.submit(picture(2, true))
            h.relay.submit(picture(3, false))
            assertEquals(2, h.emitted.size)
            val key = picture(2, true)
            assertArrayEquals(key.sps!! + key.pps!! + key.data, h.emitted[0])
            assertArrayEquals(picture(3, false).data, h.emitted[1])
            verify(exactly = 0) { h.failed.invoke() }
            verify(exactly = 1) { h.factory.createVideoSource(true) }
        } finally { h.close() }
        verify(exactly = 1) { h.track.dispose() }; verify(exactly = 1) { h.source.dispose() }
    }
    @Test fun `native retained frames cannot fill an unbounded queue and recovery requires IDR`() {
        val h = Harness()
        try {
            h.hold = true
            for (i in 1L..100) h.relay.submit(picture(i, true))
            assertEquals(3, h.held.size)
            h.held.forEach(VideoFrame::release); h.held.clear(); h.hold = false
            h.relay.submit(picture(101, false))
            assertTrue(h.emitted.isEmpty())
            h.relay.submit(picture(102, true))
            assertEquals(1, h.emitted.size)
        } finally { h.close() }
    }
    @Test fun `retired capture and malformed IDR cannot emit and close is idempotent`() {
        val h = Harness()
        h.valid = false
        h.relay.submit(picture(1, true)); assertTrue(h.emitted.isEmpty())
        h.valid = true
        h.relay.submit(picture(2, true).copy(sps = null)); assertTrue(h.emitted.isEmpty())
        h.relay.submit(picture(3, true).copy(capture = capture.copy(epoch = "b".repeat(32))))
        assertTrue(h.emitted.isEmpty())
        h.close(); h.relay.close()
        h.relay.submit(picture(4, true)); assertTrue(h.emitted.isEmpty())
        verify(exactly = 1) { h.source.dispose() }
    }
    @Test fun `RTP retained encoded images have an independent bound and release after retirement`() {
        val h = Harness()
        try {
            h.holdEncoded = true
            for (i in 1L..100) h.relay.submit(picture(i, true))
            assertEquals(3, h.heldEncoded.size)
            assertEquals(3L, h.relay.receipt()["retainedOutputFrames"])
            assertEquals(0L, h.relay.receipt()["retainedInputFrames"])
            h.heldEncoded.forEach(EncodedImage::release); h.heldEncoded.clear(); h.holdEncoded = false
            h.relay.submit(picture(101, false)); assertEquals(3, h.emitted.size)
            h.relay.submit(picture(102, true)); assertEquals(4, h.emitted.size)
        } finally { h.close() }
        assertEquals(0L, h.relay.receipt()["retainedOutputBytes"])
    }
    @Test fun `zero rate pauses publication and resumption never forwards a delta reference`() {
        val h = Harness()
        try {
            h.relay.submit(picture(1, true)); assertEquals(1, h.emitted.size)
            h.encoder.setRateAllocation(VideoEncoder.BitrateAllocation(arrayOf(intArrayOf(0))), 30)
            h.relay.submit(picture(2, true)); assertEquals(1, h.emitted.size)
            h.encoder.setRateAllocation(VideoEncoder.BitrateAllocation(arrayOf(intArrayOf(1500000))), 30)
            h.relay.submit(picture(3, false)); assertEquals(1, h.emitted.size)
            h.relay.submit(picture(4, true)); assertEquals(2, h.emitted.size)
        } finally { h.close() }
    }
}
