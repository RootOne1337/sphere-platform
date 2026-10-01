package com.sphereplatform.agent.streaming

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class RgbaToI420Test {
    private fun color(r: Int, g: Int, b: Int, alpha: Int = 255): ByteBuffer =
        ByteBuffer.wrap(ByteArray(16) { index -> when (index % 4) {
            0 -> r.toByte(); 1 -> g.toByte(); 2 -> b.toByte(); else -> alpha.toByte()
        } })
    private fun result(input: ByteBuffer): List<Int> {
        val output = ByteBuffer.allocate(6)
        RgbaToI420(2, 2).convert(input, 8, 4, output)
        return output.array().map { it.toInt() and 255 }
    }
    @Test fun `black uses limited range luma and neutral chroma`() {
        assertEquals(listOf(16, 16, 16, 16, 128, 128), result(color(0, 0, 0)))
    }
    @Test fun `white is 235 rather than full range 255`() {
        assertEquals(listOf(235, 235, 235, 235, 128, 128), result(color(255, 255, 255)))
    }
    @Test fun `red preserves RGBA channel order and I420 U then V`() {
        assertEquals(listOf(82, 82, 82, 82, 90, 240), result(color(255, 0, 0)))
    }
    @Test fun `green has the expected BT601 integer reference`() {
        assertEquals(listOf(144, 144, 144, 144, 54, 34), result(color(0, 255, 0)))
    }
    @Test fun `blue does not get interpreted as red`() {
        assertEquals(listOf(41, 41, 41, 41, 240, 110), result(color(0, 0, 255)))
    }
    @Test fun `chroma averages all four pixels without averaging luma`() {
        val rgba = byteArrayOf(-1,0,0,-1, 0,-1,0,-1, 0,0,-1,-1, -1,-1,-1,-1)
        assertEquals(listOf(82, 144, 41, 235, 128, 128), result(ByteBuffer.wrap(rgba)))
    }
    @Test fun `row and pixel padding do not become screen pixels`() {
        val source = ByteBuffer.allocate(36)
        for (y in 0..1) for (x in 0..1) {
            val offset = y * 24 + x * 8
            source.put(offset, -1); source.put(offset + 3, -1)
        }
        // The last row exposes only the final pixel, not 12 trailing pad bytes.
        val output = ByteBuffer.allocate(6)
        RgbaToI420(2, 2).convert(source, 24, 8, output)
        assertEquals(listOf(82,82,82,82,90,240), output.array().map { it.toInt() and 255 })
    }
    @Test fun `caller position is retained and destination contains exactly one frame`() {
        val source = color(255, 0, 0); source.position(13)
        val destination = ByteBuffer.allocate(10); destination.position(7)
        RgbaToI420(2, 2).convert(source, 8, 4, destination)
        assertEquals(13, source.position()); assertEquals(6, destination.position())
    }
    @Test fun `reuse cannot retain an earlier red frame when the next is blue`() {
        val converter = RgbaToI420(2,2); val output = ByteBuffer.allocate(6)
        converter.convert(color(255,0,0),8,4,output)
        converter.convert(color(0,0,255),8,4,output)
        assertEquals(listOf(41,41,41,41,240,110), output.array().map { it.toInt() and 255 })
    }
    @Test fun `alpha does not shift color channels`() {
        assertEquals(result(color(255,0,0)), result(color(255,0,0,0)))
    }
    @Test fun `truncated plane rejected before destination mutation`() {
        val output = ByteBuffer.wrap(ByteArray(6) { 9 })
        assertThrows(IllegalArgumentException::class.java) {
            RgbaToI420(2,2).convert(ByteBuffer.allocate(15),8,4,output)
        }
        assertArrayEquals(ByteArray(6) { 9 }, output.array())
    }
    @Test fun `invalid stride and output buffers fail closed`() {
        val converter = RgbaToI420(2,2)
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),7,4,ByteBuffer.allocate(6)) }
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),8,3,ByteBuffer.allocate(6)) }
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),8,4,ByteBuffer.allocate(5)) }
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),8,4,ByteBuffer.allocate(6).asReadOnlyBuffer()) }
    }
    @Test fun `odd dimensions and excessive sizes are not silently cropped`() {
        for ((width, height) in listOf(3 to 2, 2 to 3, 0 to 2, 8192 to 2)) {
            assertThrows(IllegalArgumentException::class.java) { RgbaToI420(width,height) }
        }
    }
}
