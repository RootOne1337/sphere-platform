package com.sphereplatform.agent.streaming

import org.junit.Assert.*
import org.junit.Test
import java.nio.ByteBuffer
import java.util.UUID

class FramePackagerTest {
    private val epoch = UUID.fromString("00112233-4455-6677-8899-aabbccddeeff")
    private val nal = byteArrayOf(0, 0, 0, 1, 0x65, 0x42)
    private fun metadata(key: Boolean = true, config: Boolean = false) =
        H264Encoder.FrameMetadata(key, 0, nal.size, config)

    @Test fun `default packet retains legacy header and exact Annex B bytes`() {
        val packet = FramePackager.pack(nal, metadata(), System.currentTimeMillis())
        assertEquals(20, packet.size)
        assertEquals(1, packet[0].toInt())
        assertEquals(1, packet[1].toInt())
        assertEquals(6, ByteBuffer.wrap(packet).getInt(10))
        assertArrayEquals(nal, packet.copyOfRange(14, packet.size))
    }

    @Test fun `capture packet has fixed network byte order identity and unchanged payload`() {
        val packet = FramePackager.pack(nal, metadata(), System.currentTimeMillis(), epoch)
        assertEquals(36, packet.size)
        assertEquals(2, packet[0].toInt())
        assertEquals(1, packet[1].toInt())
        assertEquals(6, ByteBuffer.wrap(packet).getInt(10))
        val expectedIdentity = byteArrayOf(0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
            0x88.toByte(), 0x99.toByte(), 0xaa.toByte(), 0xbb.toByte(), 0xcc.toByte(), 0xdd.toByte(), 0xee.toByte(), 0xff.toByte())
        assertArrayEquals(expectedIdentity, packet.copyOfRange(14, 30))
        assertArrayEquals(nal, packet.copyOfRange(30, packet.size))
    }

    @Test fun `codec replay uses the same capture envelope as pictures`() {
        val packet = FramePackager.pack(nal, metadata(config = true), 0, epoch)
        assertEquals(epoch.mostSignificantBits, ByteBuffer.wrap(packet).getLong(14))
        assertEquals(epoch.leastSignificantBits, ByteBuffer.wrap(packet).getLong(22))
    }

    @Test fun `capture delta does not acquire a keyframe flag`() {
        assertEquals(0, FramePackager.pack(nal, metadata(key = false), 0, epoch)[1].toInt())
    }

    @Test(expected = IllegalArgumentException::class) fun `nil capture identity is refused`() {
        FramePackager.pack(nal, metadata(), 0, UUID(0, 0))
    }

    @Test(expected = IllegalArgumentException::class) fun `empty capture payload is refused`() {
        FramePackager.pack(byteArrayOf(), metadata(), 0, epoch)
    }

    @Test(expected = IllegalArgumentException::class) fun `capture payload exceeding decoder budget is refused`() {
        FramePackager.pack(ByteArray(1024 * 1024 + 1), metadata(), 0, epoch)
    }
}
