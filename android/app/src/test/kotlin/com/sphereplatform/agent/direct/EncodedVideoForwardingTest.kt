package com.sphereplatform.agent.direct

import com.sphereplatform.agent.streaming.CaptureInputSession
import com.sphereplatform.agent.streaming.EncodedCaptureFrame
import org.junit.Assert.*
import org.junit.Test

class EncodedVideoForwardingTest {
    private val capture = CaptureInputSession("a".repeat(32), 960, 540, 960, 540, 0)
    private fun nal(vararg bytes: Int) = byteArrayOf(0, 0, 0, 1) + bytes.map(Int::toByte).toByteArray()
    private fun frame(key: Boolean = true, data: ByteArray = nal(0x65, 0x88)) = EncodedCaptureFrame(
        capture, 1, 1_000_000, key, data, nal(0x67, 66, 0xc0, 31, 0x80), nal(0x68, 0xce, 0x80))

    @Test fun `IDR is prefixed with actual constrained baseline configuration and delta is not copied`() {
        val idr = frame()
        assertArrayEquals(idr.sps!! + idr.pps!! + idr.data, EncodedVideoAccessUnit.prepare(idr))
        val delta = frame(false, nal(0x41, 0x80))
        assertSame(delta.data, EncodedVideoAccessUnit.prepare(delta))
    }
    @Test fun `AVCC leading junk unsupported slices wrong frame flags and excessive NAL counts fail closed`() {
        for (bad in listOf(frame(data = byteArrayOf(0, 0, 0, 2, 0x65, 0x88.toByte())),
            frame(data = byteArrayOf(9) + nal(0x65, 0x88)), frame(data = nal(0xe5, 0x88)),
            frame(data = nal(0x62, 0x88)), frame(key = false), frame(data = nal(0x41, 0x80)),
            frame(data = List(65) { nal(0x65, 0x88) }.reduce(ByteArray::plus))))
            assertNull(EncodedVideoAccessUnit.prepare(bad))
    }
    @Test fun `missing changed unsupported or oversized decoder configuration is not advertised as valid video`() {
        val good = frame()
        for (bad in listOf(good.copy(sps = null), good.copy(pps = null),
            good.copy(sps = nal(0x67, 100, 0xc0, 31)), good.copy(sps = nal(0x67, 66, 0, 31)),
            good.copy(sps = nal(0x67, 66, 0xc0, 40)), good.copy(pps = nal(0x67, 66, 0xc0, 31)),
            good.copy(data = nal(0x65) + ByteArray(EncodedVideoBudget.MAX_FRAME_BYTES)),
            good.copy(sps = nal(0x67, 66, 0xc0, 31) + ByteArray(4096))))
            assertNull(EncodedVideoAccessUnit.prepare(bad))
    }
    @Test fun `first picture gaps and reordered pictures always wait for a fresh keyframe`() {
        val order = EncodedVideoOrder()
        assertFalse(order.admit(1, 100, false))
        assertTrue(order.admit(2, 200, true))
        assertTrue(order.admit(3, 300, false))
        assertFalse(order.admit(5, 500, false))
        assertFalse(order.admit(6, 600, false))
        assertTrue(order.admit(7, 700, true))
        assertFalse(order.admit(6, 600, true))
        assertFalse(order.admit(8, 800, false))
        assertTrue(order.admit(9, 900, true))
        order.invalidate()
        assertFalse(order.admit(10, 1000, false))
        assertTrue(order.admit(11, 1100, true))
    }
    @Test fun `a duplicate or backwards timestamp cannot reintroduce a coded reference`() {
        val order = EncodedVideoOrder()
        assertTrue(order.admit(1, 200, true))
        assertFalse(order.admit(2, 200, true))
        assertFalse(order.admit(3, 300, false))
        assertTrue(order.admit(4, 400, true))
    }
    @Test fun `native retained frames share one count and byte budget and release exactly once`() {
        val budget = EncodedVideoBudget()
        val a = checkNotNull(budget.reserve(1024 * 1024))
        val b = checkNotNull(budget.reserve(1024 * 1024))
        assertNull(budget.reserve(1))
        a(); a()
        assertEquals(1 to 1024 * 1024, budget.retained())
        val c = checkNotNull(budget.reserve(1)); val d = checkNotNull(budget.reserve(1))
        assertNull(budget.reserve(1))
        budget.close()
        assertNull(budget.reserve(1))
        b(); c(); d()
        assertEquals(0 to 0, budget.retained())
        for (size in listOf(0, -1, Int.MAX_VALUE, EncodedVideoBudget.MAX_FRAME_BYTES + 1))
            assertNull(EncodedVideoBudget().reserve(size))
    }
}
