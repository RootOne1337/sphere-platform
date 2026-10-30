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
import java.nio.ByteBuffer

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class EncoderCallbackOwnershipTest {
    private val codec = mockk<MediaCodec>(relaxed = true)
    private val surface = mockk<Surface>(relaxed = true)
    private val callback = slot<MediaCodec.Callback>()
    private val frames = mutableListOf<ByteArray>()
    private val errors = mutableListOf<Exception>()
    private var consume: (ByteArray) -> Unit = { frames.add(it) }
    private val encoder = H264Encoder(H264Encoder.EncoderConfig()) { data, _ -> consume(data) }
    private val picture = byteArrayOf(0, 0, 0, 1, 0x65, 0x01)
    private val config = byteArrayOf(0, 0, 0, 1, 0x67, 0x42, 0, 0, 0, 1, 0x68, 0x01)

    @Before fun setup() {
        mockkStatic(MediaCodec::class)
        every { MediaCodec.createEncoderByType(any()) } returns codec
        every { codec.createInputSurface() } returns surface
        every { codec.setCallback(capture(callback)) } just Runs
        encoder.onEncoderError = { errors.add(it) }
        encoder.start()
    }
    @After fun cleanup() { encoder.stop(); unmockkAll() }

    private fun output(data: ByteArray = picture, flags: Int = 0) {
        every { codec.getOutputBuffer(7) } returns ByteBuffer.wrap(data)
        callback.captured.onOutputBufferAvailable(codec, 7, MediaCodec.BufferInfo().apply {
            set(0, data.size, 12_000, flags)
        })
    }

    private fun codecError(): MediaCodec.CodecException {
        val constructor = MediaCodec.CodecException::class.java.getDeclaredConstructor(
            Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, String::class.java)
        constructor.isAccessible = true
        return constructor.newInstance(1, 0, "fixture codec error")
    }

    @Test fun `queued output after stop cannot access a released codec`() {
        encoder.stop()
        output()
        verify(exactly = 0) { codec.getOutputBuffer(any()) }
        verify(exactly = 0) { codec.releaseOutputBuffer(any(), any<Boolean>()) }
        assertTrue(frames.isEmpty()); assertTrue(errors.isEmpty())
    }

    @Test fun `old config callback after replacement cannot poison new SPS cache`() {
        encoder.stop()
        val replacement = mockk<MediaCodec>(relaxed = true)
        every { MediaCodec.createEncoderByType(any()) } returns replacement
        every { replacement.createInputSurface() } returns mockk(relaxed = true)
        encoder.start()
        output(config, MediaCodec.BUFFER_FLAG_CODEC_CONFIG)
        assertNull(encoder.cachedSps); assertNull(encoder.cachedPps)
        assertTrue(frames.isEmpty()); assertTrue(errors.isEmpty())
        verify(exactly = 0) { codec.getOutputBuffer(any()) }
    }

    @Test fun `old fatal callback after stop does not request another stream restart`() {
        encoder.stop()
        callback.captured.onError(codec, codecError())
        assertTrue(errors.isEmpty())
    }

    @Test fun `consumer failure releases native output and reports the original error`() {
        val failure = IllegalStateException("fixture consumer failed")
        consume = { throw failure }
        output()
        verify(exactly = 1) { codec.releaseOutputBuffer(7, false) }
        assertEquals(listOf(failure), errors)
    }

    @Test fun `output read failure releases native output without escaping callback thread`() {
        val failure = IllegalStateException("fixture codec read failed")
        every { codec.getOutputBuffer(7) } throws failure
        callback.captured.onOutputBufferAvailable(codec, 7, MediaCodec.BufferInfo().apply {
            set(0, picture.size, 12_000, 0)
        })
        verify(exactly = 1) { codec.releaseOutputBuffer(7, false) }
        assertEquals(listOf(failure), errors); assertTrue(frames.isEmpty())
    }

    @Test fun `output release failure is contained and never delivers an unowned picture`() {
        val failure = IllegalStateException("fixture codec release failed")
        every { codec.releaseOutputBuffer(7, false) } throws failure
        output()
        assertEquals(listOf(failure), errors); assertTrue(frames.isEmpty())
    }

    @Test fun `output is returned before a consumer can synchronously stop the encoder`() {
        consume = {
            verify(exactly = 1) { codec.releaseOutputBuffer(7, false) }
            encoder.stop()
            frames.add(it)
        }
        output()
        assertEquals(1, frames.size); assertArrayEquals(picture, frames.single())
        assertTrue(errors.isEmpty())
        verify(exactly = 1) { codec.releaseOutputBuffer(7, false) }
    }

    @Test fun `stopping clears configuration so a later viewer cannot reuse stale dimensions`() {
        output(config, MediaCodec.BUFFER_FLAG_CODEC_CONFIG)
        assertNotNull(encoder.cachedSps); assertNotNull(encoder.cachedPps)
        encoder.stop()
        assertNull(encoder.cachedSps); assertNull(encoder.cachedPps)
    }

    @Test fun `one active codec fault preserves its cause and requests recovery only once`() {
        val failure = codecError()
        callback.captured.onError(codec, failure)
        callback.captured.onError(codec, codecError())
        assertEquals(listOf(failure), errors)
    }

    @Test fun `an error subscriber exception cannot escape the codec callback thread`() {
        encoder.onEncoderError = { throw IllegalStateException("fixture observer failed") }
        every { codec.releaseOutputBuffer(7, false) } throws IllegalStateException("fixture codec failed")
        output()
        assertTrue(frames.isEmpty())
    }

    @Test fun `read and release failure preserve the original cause with suppressed release evidence`() {
        val readFailure = IllegalStateException("fixture read failed")
        val releaseFailure = IllegalStateException("fixture release failed")
        every { codec.getOutputBuffer(7) } throws readFailure
        every { codec.releaseOutputBuffer(7, false) } throws releaseFailure
        callback.captured.onOutputBufferAvailable(codec, 7, MediaCodec.BufferInfo().apply {
            set(0, picture.size, 12_000, 0)
        })
        assertEquals(listOf(readFailure), errors)
        assertArrayEquals(arrayOf(releaseFailure), readFailure.suppressed)
    }

    @Test fun `stopping from SPS consumer cannot deliver PPS from the retired session`() {
        consume = { frames.add(it); encoder.stop() }
        output(config, MediaCodec.BUFFER_FLAG_CODEC_CONFIG)
        assertEquals(1, frames.size)
        assertNull(encoder.cachedSps); assertNull(encoder.cachedPps)
        verify(exactly = 1) { codec.releaseOutputBuffer(7, false) }
        assertTrue(errors.isEmpty())
    }

    @Test fun `buffer offset is honored and bytes remain owned after returning the native buffer`() {
        val native = byteArrayOf(9, 9) + picture + byteArrayOf(9)
        every { codec.getOutputBuffer(7) } returns ByteBuffer.wrap(native)
        every { codec.releaseOutputBuffer(7, false) } answers { native.fill(0) }
        callback.captured.onOutputBufferAvailable(codec, 7, MediaCodec.BufferInfo().apply {
            set(2, picture.size, 12_000, 0)
        })
        assertArrayEquals(picture, frames.single())
        assertTrue(errors.isEmpty())
    }
}
